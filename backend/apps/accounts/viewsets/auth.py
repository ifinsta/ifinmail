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
from collections.abc import Callable
from typing import Concatenate, ParamSpec, TypeVar, cast

from django.http import HttpRequest
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

P = ParamSpec('P')
R = TypeVar('R')

SCOPE_ATTR = 'required_scope'


class ApiRequest(HttpRequest):
    """The request of an authenticated API call: what Ninja and our middleware attach to it."""

    auth: VerifiedToken
    api_rate: api_access.RateState


def _admit(request: HttpRequest, prefix: str, secret: str) -> VerifiedToken | None:
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
    def authenticate(self, request: HttpRequest, token: str) -> VerifiedToken | None:
        split = split_token(token)
        if split is None:
            return None
        return _admit(request, split[0], split[1])


class KeyBasic(HttpBasicAuth):
    def authenticate(
        self, request: HttpRequest, username: str, password: str
    ) -> VerifiedToken | None:
        prefix = parse_key(username)
        if prefix is None or not password:
            return None
        return _admit(request, prefix, password)


def actor(request: ApiRequest) -> str:
    """Who an audit entry should name for a call made with a key."""
    auth = getattr(request, 'auth', None)
    if auth is None:
        return 'api'
    return f'api:{key_id(auth.row.prefix)} ({auth.user.email})'


def require_scope(
    code: str,
) -> Callable[[Callable[Concatenate[ApiRequest, P], R]], Callable[Concatenate[ApiRequest, P], R]]:
    """Endpoint decorator: the key must carry ``code`` and its owner must still hold it.

    The scope is also recorded on the function (see ``scope_of``) so the OpenAPI contract and the
    assistant can state it without a second list that could drift.
    """

    def decorator(
        view_func: Callable[Concatenate[ApiRequest, P], R],
    ) -> Callable[Concatenate[ApiRequest, P], R]:
        @functools.wraps(view_func)
        def wrapper(request: ApiRequest, *args: P.args, **kwargs: P.kwargs) -> R:
            auth = getattr(request, 'auth', None)
            if auth is None:
                raise HttpError(401, 'A valid API key is required.')
            if code not in (auth.row.scopes or []):
                raise HttpError(403, f'This key lacks the {code} scope.')
            if not RoleService.has_perm(auth.user, code):
                raise HttpError(403, f'This login no longer holds {code}.')
            return view_func(request, *args, **kwargs)

        setattr(wrapper, SCOPE_ATTR, code)
        return cast(Callable[Concatenate[ApiRequest, P], R], wrapper)

    return decorator


def scope_of(view_func: Callable[..., object]) -> str | None:
    """The scope ``require_scope`` attached, looking through pagination and other wrappers."""
    seen: object | None = view_func
    while seen is not None:
        scope = getattr(seen, SCOPE_ATTR, None)
        if isinstance(scope, str):
            return scope
        seen = getattr(seen, '__wrapped__', None)
    return None


__all__ = ['ApiRequest', 'KeyBasic', 'TokenBearer', 'actor', 'require_scope', 'scope_of']
