"""Voter identity, "has voted" lookups and result calculation."""

import uuid
from datetime import timedelta
from typing import NamedTuple

from django.conf import settings
from django.db.models import Count, IntegerField, OuterRef, Prefetch, Q, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import Option, Vote

VOTER_COOKIE = "voter_id"
VOTER_COOKIE_SALT = "polls.voter_id"
VOTER_COOKIE_MAX_AGE = 60 * 60 * 24 * 365

# Soft per-network cap: classmates on one Wi-Fi can all vote, but a script cannot stuff the box.
MAX_VOTES_PER_IP = 5

# A vote can be changed for this long after it was first cast (and only while the poll is open).
CHANGE_WINDOW = timedelta(minutes=10)

# "Popüler" ranks polls by the votes they got in this window, so old favourites do not stay on top forever.
POPULAR_WINDOW = timedelta(days=7)


# --- Anonymous voter cookie -------------------------------------------------

def get_voter_key(request):
    """Return the UUID string from the signed voter cookie, or None if missing/tampered."""
    value = request.get_signed_cookie(VOTER_COOKIE, default=None, salt=VOTER_COOKIE_SALT)
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def new_voter_key():
    return str(uuid.uuid4())


def set_voter_cookie(response, voter_key):
    response.set_signed_cookie(
        VOTER_COOKIE,
        voter_key,
        salt=VOTER_COOKIE_SALT,
        max_age=VOTER_COOKIE_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=not settings.DEBUG,
    )


# --- "Has this person voted?" -----------------------------------------------

def identity_filter(user, voter_key):
    """Q matching votes cast by this member OR from this browser. None if there is no identity."""
    condition = Q()
    if user is not None and user.is_authenticated:
        condition |= Q(user=user)
    if voter_key:
        condition |= Q(voter_key=voter_key)
    return condition or None


class PriorVote(NamedTuple):
    option_id: int
    is_mine: bool  # False: cast on this browser by a different member, so it must stay hidden from the viewer
    vote_id: int = 0
    voted_at: object = None  # when the vote was first cast; a change does not move it


def prior_votes(user, voter_key, poll_ids):
    """{poll_id: PriorVote} for the polls this person already voted on — a single query.

    A vote found through the browser cookie that a different signed-in member cast counts as "already voted"
    (decision 2: one vote per browser), but it is not this viewer's choice and must not be shown as theirs.
    Votes cast as a guest, or by the same member, are theirs. When both kinds exist for a poll, theirs wins.
    """
    condition = identity_filter(user, voter_key)
    if condition is None or not poll_ids:
        return {}
    rows = Vote.objects.filter(condition, poll_id__in=poll_ids).values_list(
        "poll_id", "option_id", "user_id", "pk", "created_at"
    )
    signed_in = user is not None and user.is_authenticated
    found = {}
    for poll_id, option_id, voter_user_id, vote_id, created_at in rows:
        is_mine = not (signed_in and voter_user_id is not None and voter_user_id != user.pk)
        if poll_id not in found or (is_mine and not found[poll_id].is_mine):
            found[poll_id] = PriorVote(option_id, is_mine, vote_id, created_at)
    return found


def change_seconds_left(poll, voted_at, now=None):
    """Whole seconds this vote can still be changed; 0 when the window is over or the poll is closed."""
    now = now or timezone.now()
    if voted_at is None:
        return 0
    last_moment = voted_at + CHANGE_WINDOW
    if poll.closes_at is not None:
        last_moment = min(last_moment, poll.closes_at)  # a vote cannot be changed once the poll has ended
    return max(0, int((last_moment - now).total_seconds()))


def only_open(queryset):
    """Polls that still take votes."""
    return queryset.filter(Q(closes_at__isnull=True) | Q(closes_at__gt=timezone.now()))


def exclude_voted(queryset, request):
    """Polls this visitor (member or browser) has not voted on yet; unchanged without any identity."""
    condition = identity_filter(request.user, get_voter_key(request))
    if condition is None:
        return queryset
    return queryset.exclude(pk__in=Vote.objects.filter(condition).values("poll_id"))


def order_by_popularity(queryset):
    """Most votes in the last POPULAR_WINDOW first; ties (and zero) fall back to newest first."""
    since = timezone.now() - POPULAR_WINDOW
    recent = (
        Vote.objects.filter(poll=OuterRef("pk"), created_at__gte=since)
        .order_by()
        .values("poll")
        .annotate(total=Count("pk"))
        .values("total")
    )
    return queryset.annotate(recent_votes=Coalesce(Subquery(recent, output_field=IntegerField()), 0)).order_by(
        "-recent_votes", "-created_at", "-id"
    )


# --- Results ----------------------------------------------------------------

def options_with_counts():
    return Option.objects.annotate(vote_count=Count("votes")).order_by("position")


def options_prefetch():
    return Prefetch("options", queryset=options_with_counts())


def rounded_percents(counts):
    """Largest-remainder rounding so the percentages always add up to exactly 100."""
    total = sum(counts)
    if total == 0:
        return [0] * len(counts)
    raw = [count * 100 / total for count in counts]
    floors = [int(value) for value in raw]
    remainder = 100 - sum(floors)
    order = sorted(range(len(counts)), key=lambda i: (-(raw[i] - floors[i]), -counts[i], i))
    for i in order[:remainder]:
        floors[i] += 1
    return floors


def build_results(options, voted_option_id=None, change_seconds=0):
    """options must carry `vote_count` (see options_with_counts)."""
    options = list(options)
    counts = [option.vote_count for option in options]
    percents = rounded_percents(counts)
    return {
        "total": sum(counts),
        "change_seconds": change_seconds,
        "options": [
            {
                "id": option.pk,
                "text": option.text,
                "position": option.position,
                "votes": count,
                "percent": percent,
                "selected": option.pk == voted_option_id,
            }
            for option, count, percent in zip(options, counts, percents)
        ],
        "voted_option_id": voted_option_id,
    }


def results_payload(results):
    """Public JSON shape of the vote endpoint (no option texts needed by the client)."""
    return {
        "total": results["total"],
        "options": [{"id": o["id"], "votes": o["votes"], "percent": o["percent"]} for o in results["options"]],
        "voted_option_id": results["voted_option_id"],
        "can_change": results["change_seconds"] > 0,
        "change_seconds": results["change_seconds"],
    }


def annotate_for_viewer(request, polls):
    """Attach viewer-specific state to each poll. Results are only attached when allowed."""
    polls = list(polls)
    user = request.user
    prior = prior_votes(user, get_voter_key(request), [poll.pk for poll in polls])
    now = timezone.now()
    for poll in polls:
        poll.is_owner = user.is_authenticated and poll.author_id == user.pk
        vote = prior.get(poll.pk)
        has_voted = vote is not None
        poll.closed = poll.closes_at is not None and now >= poll.closes_at
        poll.voted_by_other = has_voted and not vote.is_mine
        poll.voted_option_id = vote.option_id if has_voted and vote.is_mine else None
        # Everyone, the owner included, votes once (and may change that vote for a few minutes). The owner just
        # sees the results from the start; once a poll has ended the results are open to everybody.
        poll.votable = not has_voted and not poll.closed
        poll.change_seconds = change_seconds_left(poll, vote.voted_at, now) if has_voted and vote.is_mine else 0
        poll.can_change = poll.change_seconds > 0
        poll.change_minutes = -(-poll.change_seconds // 60)
        poll.clickable = poll.votable or poll.can_change  # the result bars are buttons
        poll.show_results = poll.is_owner or has_voted or poll.closed
        poll.results = (
            build_results(poll.options.all(), poll.voted_option_id, poll.change_seconds) if poll.show_results else None
        )
    return polls
