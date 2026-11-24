"""Client IP, keyed IP digests and a small database-backed rate limiter.

The raw IP address is never stored: only a keyed hash (HMAC of the IP with a key derived from
SECRET_KEY). Counters live in the database because serverless instances share no memory.
"""

import hashlib
import hmac
import ipaddress
import math
import random
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import RateLimitEvent

# scope -> (maximum events, window in seconds)
LIMITS = {
    "vote": (30, 60),      # votes per minute from one IP
    "signup": (5, 3600),   # accounts per hour from one IP
    "report": (10, 3600),  # reports per hour from one IP
    "password_reset": (5, 3600),        # reset requests per hour from one IP, for any address
    "password_reset_email": (3, 3600),  # reset emails per hour to one address (stops mail bombing)
    "login": (10, 900),    # failed password checks per 15 minutes from one IP, whichever address is tried
}

CLEANUP_AFTER = timedelta(days=1)
CLEANUP_CHANCE = 0.02  # roughly one call in fifty prunes old rows; there is no cron on Vercel

# Headers that Vercel sets itself and overwrites on every request, so clients cannot spoof them.
# Do NOT keep trusting them if the app ever moves to a host that does not overwrite them.
TRUSTED_IP_HEADERS = ("HTTP_X_VERCEL_FORWARDED_FOR", "HTTP_X_FORWARDED_FOR")


def client_ip(request):
    """The visitor's IP, or None when no trusted header carries it.

    REMOTE_ADDR is deliberately ignored: behind Vercel it is an infrastructure address shared by
    everyone, which would turn per-IP limits into site-wide limits. With no trusted header (local
    development, tests) the IP-based checks simply do not apply.
    """
    for header in TRUSTED_IP_HEADERS:
        value = request.META.get(header)
        if value:
            try:
                return ipaddress.ip_address(value.split(",")[0].strip())
            except ValueError:
                return None
    return None


def ip_digest(ip):
    """Keyed hash of an IP (IPv6 reduced to its /64 network); None when the IP is unknown."""
    if ip is None:
        return None
    if ip.version == 6:
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        else:
            ip = ipaddress.ip_network(f"{ip}/64", strict=False).network_address
    key = ("polls.ip-digest|" + settings.SECRET_KEY).encode()
    return hmac.new(key, str(ip).encode(), hashlib.sha256).hexdigest()[:32]


def human_wait(seconds):
    """'12 saniye' / '5 dakika' for messages shown to the visitor."""
    if seconds < 90:
        return f"{seconds} saniye"
    return f"{math.ceil(seconds / 60)} dakika"


def email_digest(email):
    """Keyed hash of an email address, used only as a rate-limit key (so no address is stored)."""
    normalized = (email or "").strip().lower()
    if not normalized:
        return None
    key = ("accounts.email-digest|" + settings.SECRET_KEY).encode()
    return hmac.new(key, normalized.encode(), hashlib.sha256).hexdigest()[:32]


def request_digest(request):
    return ip_digest(client_ip(request))


def check(scope, key):
    """Seconds to wait if `key` is over the limit for `scope`; None when the action is allowed."""
    if not key:
        return None
    limit, window = LIMITS[scope]
    now = timezone.now()
    oldest = list(
        RateLimitEvent.objects.filter(scope=scope, key=key, created_at__gte=now - timedelta(seconds=window))
        .order_by("created_at")
        .values_list("created_at", flat=True)[:limit]
    )
    if len(oldest) < limit:
        return None
    # The oldest event is the first to leave the window.
    return max(1, math.ceil(window - (now - oldest[0]).total_seconds()))


def reserve(scope, key):
    """Count an attempt first, then check the total: returns (wait, event).

    check() followed by record() lets a burst of parallel requests all pass the check before any of them is
    counted. Here every request writes its own row first, so the last one to arrive always sees all the others
    and at most `limit` attempts get through. A denied attempt removes its own row (so hammering does not
    extend the lockout) and gets (seconds to wait, None); an allowed one gets (None, event) and may delete the
    event again if the attempt turns out to be free (a successful login).
    """
    if not key:
        return None, None
    limit, window = LIMITS[scope]
    event = RateLimitEvent.objects.create(scope=scope, key=key)
    since = timezone.now() - timedelta(seconds=window)
    if RateLimitEvent.objects.filter(scope=scope, key=key, created_at__gte=since).count() <= limit:
        return None, event
    event.delete()
    return check(scope, key) or 1, None


def record(scope, key):
    """Count one successful action. Call after the action succeeded, so failed attempts are free."""
    if not key:
        return
    RateLimitEvent.objects.create(scope=scope, key=key)
    if random.random() < CLEANUP_CHANCE:
        cleanup()


def cleanup(now=None):
    now = now or timezone.now()
    return RateLimitEvent.objects.filter(created_at__lt=now - CLEANUP_AFTER).delete()
