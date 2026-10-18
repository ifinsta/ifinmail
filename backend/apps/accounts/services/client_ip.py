"""The address of the person at the other end of a request, as the reverse proxy saw it."""

from __future__ import annotations

from django.http import HttpRequest


def client_ip(request: HttpRequest) -> str:
    """The client address as the reverse proxy saw it.

    nginx *appends* the connecting address to X-Forwarded-For, so the last entry is the one to
    trust; earlier entries are whatever the client sent, and taking the first would let anyone
    choose the address recorded in the audit trail, the threat digest and the sign-in lockout.
    Without a proxy header this is the connecting address itself.
    """
    x_forwarded = str(request.META.get('HTTP_X_FORWARDED_FOR', ''))
    if x_forwarded:
        last = x_forwarded.split(',')[-1].strip()
        if last:
            return last
    return str(request.META.get('REMOTE_ADDR', ''))
