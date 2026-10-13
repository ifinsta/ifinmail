"""Authentication for the API: a key and secret, or one Bearer token.

Two spellings of the same credential (see ``services.tokens``):

* HTTP Basic, ``Authorization: Basic base64(ifm_<key>:<secret>)`` — what ``curl -u`` sends.
* Bearer, ``Authorization: Bearer ifm.<key>.<secret>``.

Scopes are checked per operation *and* intersected with the owner's current permissions, so
narrowing a role instantly narrows outstanding keys. Keys are machine credentials: they do not
(and cannot) satisfy interactive MFA. Every failure is answered with the same generic 401; the
reason goes to the audit trail, never to the caller.
"""

from __future__ import annotations

import functools

from ninja.errors import HttpError
from ninja.security import HttpBasicAuth, HttpBearer

from backend.apps.accounts.services import api_access
from backend.apps.accounts.services.roles import RoleService
from backend.apps.accounts.services.tokens import (
    TokenService,
    VerifiedToken,
    key_id,
    parse_key,
    split_token,
)


def _admit(request, prefix: str, secret: str) -> VerifiedToken | None:
    """Check the credential, then spend one call from the key's rate budget."""
    address = api_access.client_address(request)
    verified, reason = TokenService.check(prefix, secret, address)
    if verified is None:
        api_access.record_failure(reason, prefix, address)
        return None
    state = api_access.RateLimiter.hit(prefix, verified.row.rate_limit_per_minute)
    request.api_rate = state  # read by ApiResponseHeadersMiddleware
    if not state.allowed:
        raise HttpError(429, 'Too many requests. Slow down and retry after the delay shown.')
    return verified


class TokenBearer(HttpBearer):
    def authenticate(self, request, token: str) -> VerifiedToken | None:
        split = split_token(token)
        if split is None:
            return None
        return _admit(request, split[0], split[1])


class KeyBasic(HttpBasicAuth):
    def authenticate(self, request, username: str, password: str) -> VerifiedToken | None:
        prefix = parse_key(username)
        if prefix is None or not password:
            return None
        return _admit(request, prefix, password)


def actor(request) -> str:
    """Who an audit entry should name for a call made with a key."""
    auth: VerifiedToken | None = getattr(request, 'auth', None)
    if auth is None:
        return 'api'
    return f'api:{key_id(auth.row.prefix)} ({auth.user.email})'


def require_scope(code: str):
    """Endpoint decorator: token must carry ``code`` and the owner must hold it."""

    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request, *args: object, **kwargs: object):
            auth: VerifiedToken | None = request.auth
            if auth is None:
                raise HttpError(401, 'A valid API key is required.')
            if code not in (auth.row.scopes or []):
                raise HttpError(403, f'This key lacks the {code} scope.')
            if not RoleService.has_perm(auth.user, code):
                raise HttpError(403, f'This login no longer holds {code}.')
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


__all__ = ['KeyBasic', 'TokenBearer', 'actor', 'require_scope']
