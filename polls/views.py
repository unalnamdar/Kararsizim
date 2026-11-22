from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .forms import PollForm
from .models import Poll

PAGE_SIZE = 20


def _poll_queryset():
    return Poll.objects.select_related("author").prefetch_related("options")


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
    has_next = len(rows) > PAGE_SIZE
    return {
        "polls": rows[:PAGE_SIZE],
        "page": page,
        "next_page": page + 1 if has_next else None,
    }


def feed(request):
    return render(request, "polls/feed.html", _paginate(request, _poll_queryset()))


def detail(request, poll_id):
    poll = get_object_or_404(_poll_queryset(), pk=poll_id)
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
