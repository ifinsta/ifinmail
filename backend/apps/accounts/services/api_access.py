"""What surrounds an API call: who is calling, how often, and what failed.

* ``client_address`` — the caller's address as the proxy saw it. nginx appends the connecting
  address to ``X-Forwarded-For``, so the *last* entry is trustworthy; earlier ones are whatever
  the client sent and are ignored (they would let a caller pose as an allowed address).
* ``RateLimiter`` — a fixed one-minute window per key, kept in the cache (Redis in production).
  A cache outage never blocks the API: limits are a protection, not a gate.
* ``record_failure`` — failed authentications go to the audit trail, at most once per address and
  reason in ten minutes, so a guessing run is visible without flooding the log.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from django.core.cache import cache
from django.http import HttpRequest

from backend.apps.core.platform.services.audit import AuditService

logger = logging.getLogger('backend')

DEFAULT_LIMIT_PER_MINUTE = 120
_WINDOW = 60
_FAILURE_QUIET = 600


def client_address(request: HttpRequest) -> str:
    forwarded = str(request.META.get('HTTP_X_FORWARDED_FOR', ''))
    if forwarded:
        last = forwarded.split(',')[-1].strip()
        if last:
            return last
    return str(request.META.get('REMOTE_ADDR', ''))


def default_limit() -> int:
    try:
        value = int(os.environ.get('API_RATE_LIMIT_PER_MINUTE', DEFAULT_LIMIT_PER_MINUTE))
    except ValueError:
        return DEFAULT_LIMIT_PER_MINUTE
    return value if value > 0 else DEFAULT_LIMIT_PER_MINUTE


@dataclass(frozen=True)
class RateState:
    limit: int
    remaining: int
    reset_in: int  # seconds until the window ends
    allowed: bool


class RateLimiter:
    @staticmethod
    def hit(key_prefix: str, limit: int | None = None) -> RateState:
        limit = limit or default_limit()
        now = int(time.time())
        window = now // _WINDOW
        reset_in = _WINDOW - (now % _WINDOW)
        key = f'apirl:{key_prefix}:{window}'
        try:
            cache.add(key, 0, timeout=_WINDOW + 5)
            count = cache.incr(key)
        except Exception:  # cache down or a backend without incr: do not lock integrations out
            logger.warning('API rate limiter unavailable; allowing the call')
            return RateState(limit=limit, remaining=limit, reset_in=reset_in, allowed=True)
        remaining = max(limit - count, 0)
        return RateState(
            limit=limit, remaining=remaining, reset_in=reset_in, allowed=count <= limit
        )


def record_failure(reason: str, key_prefix: str, address: str) -> None:
    """Audit a failed authentication, rate-limited by address and reason."""
    quiet_key = f'apifail:{address}:{reason}'
    try:
        if not cache.add(quiet_key, 1, timeout=_FAILURE_QUIET):
            return
    except Exception:  # without a cache we cannot throttle; skip rather than flood
        return
    # The key id is only trusted when it exists; an unknown one is attacker-chosen text.
    who = f'api:ifm_{key_prefix}' if reason != 'unknown_key' else 'api:unknown'
    AuditService.record(
        action='api_auth_failed',
        user=who,
        detail=f'{reason} from {address or "unknown address"}',
        severity='warning',
    )
