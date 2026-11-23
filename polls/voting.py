"""Voter identity, "has voted" lookups and result calculation."""

import uuid

from django.conf import settings
from django.db.models import Count, Prefetch, Q

from .models import Option, Vote

VOTER_COOKIE = "voter_id"
VOTER_COOKIE_SALT = "polls.voter_id"
VOTER_COOKIE_MAX_AGE = 60 * 60 * 24 * 365

# Soft per-network cap: classmates on one Wi-Fi can all vote, but a script cannot stuff the box.
MAX_VOTES_PER_IP = 5


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


def voted_options(user, voter_key, poll_ids):
    """{poll_id: option_id} for the polls this person already voted on — a single query."""
    condition = identity_filter(user, voter_key)
    if condition is None or not poll_ids:
        return {}
    rows = Vote.objects.filter(condition, poll_id__in=poll_ids).values_list("poll_id", "option_id")
    return dict(rows)


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


def build_results(options, voted_option_id=None):
    """options must carry `vote_count` (see options_with_counts)."""
    options = list(options)
    counts = [option.vote_count for option in options]
    percents = rounded_percents(counts)
    return {
        "total": sum(counts),
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
    }


def annotate_for_viewer(request, polls):
    """Attach viewer-specific state to each poll. Results are only attached when allowed."""
    polls = list(polls)
    user = request.user
    voted = voted_options(user, get_voter_key(request), [poll.pk for poll in polls])
    for poll in polls:
        poll.is_owner = user.is_authenticated and poll.author_id == user.pk
        poll.voted_option_id = voted.get(poll.pk)
        # Everyone, the owner included, votes once. The owner just sees the results from the start.
        poll.votable = poll.voted_option_id is None
        poll.show_results = poll.is_owner or poll.voted_option_id is not None
        poll.results = build_results(poll.options.all(), poll.voted_option_id) if poll.show_results else None
    return polls
