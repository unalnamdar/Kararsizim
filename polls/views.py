import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from . import voting
from .forms import PollForm
from .models import Poll, Vote

PAGE_SIZE = 20


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


def feed(request):
    return render(request, "polls/feed.html", _paginate(request, _poll_queryset()))


def detail(request, poll_id):
    poll = get_object_or_404(_poll_queryset(), pk=poll_id)
    voting.annotate_for_viewer(request, [poll])
    return render(request, "polls/detail.html", {"poll": poll})


@login_required
@require_http_methods(["GET", "POST"])
def create(request):
    form = PollForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        poll = form.save(author=request.user)
        messages.success(request, "Anketin yayında! Bağlantıyı paylaşıp oy toplayabilirsin.")
        return redirect(poll)
    return render(request, "polls/create.html", {"form": form})


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
MSG_OWNER = "Kendi anketine oy veremezsin."
MSG_ALREADY = "Bu ankete zaten oy vermiştin."
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

    def respond(status, message, results=None, voter_key_to_set=None):
        if is_json:
            body = voting.results_payload(results) if results is not None else {"error": message}
            response = JsonResponse(body, status=status)
        else:
            level = messages.success if status == 200 else messages.info if status == 409 else messages.error
            level(request, message)
            response = redirect("polls:detail", poll_id=poll_id)
        if voter_key_to_set:
            voting.set_voter_cookie(response, voter_key_to_set)
        return response

    poll = Poll.objects.filter(pk=poll_id).first()
    if poll is None:
        if is_json:
            return JsonResponse({"error": MSG_NOT_FOUND}, status=404)
        raise Http404(MSG_NOT_FOUND)

    user = request.user if request.user.is_authenticated else None
    if user is not None and poll.author_id == user.pk:
        return respond(403, MSG_OWNER)

    option_id = _read_option_id(request, is_json)
    if option_id is None or not poll.options.filter(pk=option_id).exists():
        return respond(400, MSG_INVALID_OPTION)

    voter_key = voting.get_voter_key(request)
    existing = voting.voted_options(user, voter_key, [poll.pk]).get(poll.pk)
    if existing is not None:
        return respond(409, MSG_ALREADY, _current_results(poll, existing))

    new_key = voter_key is None
    if new_key:
        voter_key = voting.new_voter_key()

    try:
        with transaction.atomic():
            Vote.objects.create(poll=poll, option_id=option_id, user=user, voter_key=voter_key)
    except IntegrityError:
        # Lost a race with a parallel request from the same person.
        existing = voting.voted_options(user, voter_key, [poll.pk]).get(poll.pk, option_id)
        return respond(409, MSG_ALREADY, _current_results(poll, existing))

    return respond(
        200,
        MSG_SUCCESS,
        _current_results(poll, option_id),
        voter_key_to_set=voter_key if new_key else None,
    )
