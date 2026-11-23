import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.text import Truncator
from django.views.decorators.http import require_http_methods, require_POST

from accounts import ratelimit

from . import voting
from .forms import PollForm, ReportForm
from .models import Poll, Report, Vote

User = get_user_model()

PAGE_SIZE = 20
FEED_SORTS = ("yeni", "populer")
FILTER_UNVOTED = "oylamadiklarim"


def _poll_queryset():
    return Poll.objects.select_related("author").prefetch_related(voting.options_prefetch())


def _page_number(request):
    try:
        page = int(request.GET.get("sayfa", 1))
    except (TypeError, ValueError):
        return 1
    return max(page, 1)


def _paginate(request, queryset):
    """Offset pagination without a COUNT query: fetch one extra row to know if there is more."""
    page = _page_number(request)
    offset = (page - 1) * PAGE_SIZE
    rows = list(queryset[offset:offset + PAGE_SIZE + 1])
    if page > 1 and not rows:
        raise Http404("Bu sayfada anket yok.")
    return {
        "polls": voting.annotate_for_viewer(request, rows[:PAGE_SIZE]),
        "page": page,
        "next_page": page + 1 if len(rows) > PAGE_SIZE else None,
    }


def _feed_params(sort, only_unvoted):
    params = {}
    if sort != "yeni":
        params["sirala"] = sort
    if only_unvoted:
        params["filtre"] = FILTER_UNVOTED
    return params


def _feed_url(sort, only_unvoted):
    params = _feed_params(sort, only_unvoted)
    base = reverse("polls:feed")
    return f"{base}?{urlencode(params)}" if params else base


def feed(request):
    sort = request.GET.get("sirala")
    sort = sort if sort in FEED_SORTS else "yeni"
    only_unvoted = request.GET.get("filtre") == FILTER_UNVOTED

    queryset = _poll_queryset()
    if only_unvoted:
        queryset = voting.exclude_voted(queryset, request)
    if sort == "populer":
        queryset = voting.order_by_popularity(queryset)

    context = _paginate(request, queryset)
    prefix = urlencode(_feed_params(sort, only_unvoted))
    context.update(
        {
            "sort": sort,
            "only_unvoted": only_unvoted,
            "query_prefix": f"{prefix}&" if prefix else "",  # keeps sort and filter on "Daha fazla"
            "feed_links": {
                "yeni": _feed_url("yeni", only_unvoted),
                "populer": _feed_url("populer", only_unvoted),
                "toggle": _feed_url(sort, not only_unvoted),
            },
        }
    )
    return render(request, "polls/feed.html", context)


def _share_description(poll):
    """Text for link previews. Lists the options only, never any vote counts or percentages."""
    options = Truncator(" · ".join(option.text for option in poll.options.all())).chars(150)
    return f"{options} — Oy ver, sonuçları gör."


def detail(request, poll_id):
    poll = get_object_or_404(_poll_queryset(), pk=poll_id)
    voting.annotate_for_viewer(request, [poll])
    context = {"poll": poll, "share_description": _share_description(poll), "report_reasons": Report.Reason.choices}
    return render(request, "polls/detail.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def create(request):
    form = PollForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        poll = form.save(author=request.user)
        messages.success(request, "Anketin yayında! Bağlantıyı paylaşıp oy toplayabilirsin.")
        return redirect(poll)
    return render(request, "polls/create.html", {"form": form})


def profile(request, username):
    """Public page with one member's polls. Usernames are stored lowercase; the e-mail never appears."""
    owner = get_object_or_404(User, username=username.lower(), is_active=True)
    context = _paginate(request, _poll_queryset().filter(author=owner))
    context.update(
        {
            "profile_user": owner,
            "poll_count": Poll.objects.filter(author=owner).count(),
            "is_me": request.user.is_authenticated and request.user.pk == owner.pk,
        }
    )
    return render(request, "polls/profile.html", context)


@login_required
def my_polls(request):
    context = _paginate(request, _poll_queryset().filter(author=request.user))
    return render(request, "polls/my_polls.html", context)


@require_POST
def delete(request, poll_id):
    poll = get_object_or_404(Poll, pk=poll_id)
    if not request.user.is_authenticated or poll.author_id != request.user.pk:
        raise PermissionDenied("Bu anketi yalnızca sahibi silebilir.")
    poll.delete()
    messages.success(request, "Anket silindi.")
    return redirect("polls:my_polls")


# --- Voting -----------------------------------------------------------------

MSG_NOT_FOUND = "Anket bulunamadı."
MSG_INVALID_OPTION = "Geçersiz seçenek."
MSG_ALREADY = "Bu ankete zaten oy vermiştin."
MSG_IP_LIMIT = "Bu ağdan bu ankete verilebilecek en fazla oy sayısına ulaşıldı."
MSG_SUCCESS = "Oyun kaydedildi."


def _read_option_id(request, is_json):
    if is_json:
        try:
            body = json.loads(request.body or b"{}")
        except (ValueError, UnicodeDecodeError):
            return None
        raw = body.get("option_id") if isinstance(body, dict) else None
    else:
        raw = request.POST.get("option_id")
    if isinstance(raw, bool):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _current_results(poll, voted_option_id):
    return voting.build_results(voting.options_with_counts().filter(poll=poll), voted_option_id)


@require_POST
def vote(request, poll_id):
    """JSON endpoint (`{"option_id": n}`) with a plain form POST fallback for no-JS browsers."""
    is_json = request.content_type == "application/json" or "application/json" in request.headers.get("Accept", "")

    def respond(status, message, results=None, voter_key_to_set=None, retry_after=None):
        if is_json:
            body = voting.results_payload(results) if results is not None else {"error": message}
            response = JsonResponse(body, status=status)
        else:
            level = messages.success if status == 200 else messages.info if status == 409 else messages.error
            level(request, message)
            response = redirect("polls:detail", poll_id=poll_id)
        if voter_key_to_set:
            voting.set_voter_cookie(response, voter_key_to_set)
        if retry_after:
            response["Retry-After"] = str(retry_after)
        return response

    poll = Poll.objects.filter(pk=poll_id).first()
    if poll is None:
        if is_json:
            return JsonResponse({"error": MSG_NOT_FOUND}, status=404)
        raise Http404(MSG_NOT_FOUND)

    user = request.user if request.user.is_authenticated else None

    # None when no trusted header carries the IP (local dev, tests): the IP-based checks then do not apply.
    ip_hash = ratelimit.request_digest(request)
    wait = ratelimit.check("vote", ip_hash)
    if wait:
        return respond(429, f"Çok hızlı oy veriyorsun. {ratelimit.human_wait(wait)} sonra tekrar dene.", retry_after=wait)

    option_id = _read_option_id(request, is_json)
    if option_id is None or not poll.options.filter(pk=option_id).exists():
        return respond(400, MSG_INVALID_OPTION)

    voter_key = voting.get_voter_key(request)
    existing = voting.voted_options(user, voter_key, [poll.pk]).get(poll.pk)
    if existing is not None:
        return respond(409, MSG_ALREADY, _current_results(poll, existing))

    if ip_hash and Vote.objects.filter(poll=poll, ip_hash=ip_hash).count() >= voting.MAX_VOTES_PER_IP:
        return respond(403, MSG_IP_LIMIT)

    new_key = voter_key is None
    if new_key:
        voter_key = voting.new_voter_key()

    try:
        with transaction.atomic():
            Vote.objects.create(poll=poll, option_id=option_id, user=user, voter_key=voter_key, ip_hash=ip_hash)
    except IntegrityError:
        # Lost a race with a parallel request from the same person.
        existing = voting.voted_options(user, voter_key, [poll.pk]).get(poll.pk, option_id)
        return respond(409, MSG_ALREADY, _current_results(poll, existing))

    ratelimit.record("vote", ip_hash)
    return respond(
        200,
        MSG_SUCCESS,
        _current_results(poll, option_id),
        voter_key_to_set=voter_key if new_key else None,
    )


# --- Reporting --------------------------------------------------------------

@require_POST
def report(request, poll_id):
    """Anyone may report a poll; reports only show up in the admin (nothing is hidden automatically)."""
    poll = get_object_or_404(Poll, pk=poll_id)
    user = request.user if request.user.is_authenticated else None
    if user is not None and poll.author_id == user.pk:
        messages.info(request, "Kendi anketini bildiremezsin.")
        return redirect(poll)

    ip_hash = ratelimit.request_digest(request)
    wait = ratelimit.check("report", ip_hash)
    if wait:
        messages.error(request, f"Çok fazla bildirim gönderdin. {ratelimit.human_wait(wait)} sonra tekrar dene.")
        return redirect(poll)

    form = ReportForm(request.POST)
    if not form.is_valid():
        problems = " ".join(error for errors in form.errors.values() for error in errors)
        messages.error(request, f"Bildirim gönderilemedi: {problems}")
        return redirect(poll)

    reporter = f"u{user.pk}" if user else (f"i{ip_hash}" if ip_hash else "anon")
    _, created = Report.objects.get_or_create(
        poll=poll,
        reporter=reporter,
        defaults={"user": user, "reason": form.cleaned_data["reason"], "note": form.cleaned_data["note"]},
    )
    if created:
        ratelimit.record("report", ip_hash)
        messages.success(request, "Bildirimin alındı. Teşekkürler.")
    else:
        messages.info(request, "Bu anketi zaten bildirmiştin.")
    return redirect(poll)
