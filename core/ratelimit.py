"""Small request throttle for public forms that could be used to guess things
(order tracking, discount codes).

    if ratelimit.hit(request, "track", limit=10, window=600):
        ...  # too many: refuse

Counters live in the Django cache (settings.CACHES: a file cache shared by all gunicorn
workers), keyed by the visitor's IP. settings.RATE_LIMITS_ENABLED = False turns it off
(the test settings do, so unrelated tests never trip a limit).
"""

import hashlib
import time

from django.conf import settings
from django.core.cache import cache

from .utils import client_ip

TOO_MANY_MESSAGE = "تعداد درخواست‌ها زیاد است. لطفاً چند دقیقه بعد دوباره تلاش کنید."


def _key(scope, identity):
    digest = hashlib.sha256(str(identity).encode()).hexdigest()[:32]
    return f"rl:{scope}:{digest}"


def hit(request, scope, limit, window, identity=None):
    """Count one attempt. True when this one is over `limit` attempts per `window` seconds.
    `identity` defaults to the visitor's IP address."""
    if not getattr(settings, "RATE_LIMITS_ENABLED", True):
        return False
    identity = identity if identity is not None else (client_ip(request) or "unknown")
    key = _key(scope, identity)
    now = time.time()
    try:
        # (count, window end) is stored together: not every cache backend keeps a key's
        # expiry on incr(). Two parallel requests may count as one; fine for a throttle.
        count, ends_at = cache.get(key) or (0, 0)
        if ends_at <= now:
            count, ends_at = 0, now + window
        count += 1
        cache.set(key, (count, ends_at), max(1, int(ends_at - now) + 1))
    except Exception:  # a broken cache must never take the page down
        return False
    return count > limit


def reset(request, scope, identity=None):
    identity = identity if identity is not None else (client_ip(request) or "unknown")
    try:
        cache.delete(_key(scope, identity))
    except Exception:
        pass
