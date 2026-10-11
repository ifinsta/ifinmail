"""Bearer authentication for the v1 API (first-party tokens only).

Every call needs ``Authorization: Bearer ifm.<prefix>.<secret>``. Scopes are
checked per operation *and* intersected with the owner's current permissions,
so narrowing a role instantly narrows outstanding tokens. Tokens are machine
credentials: they do not (and cannot) satisfy interactive MFA.
"""

from __future__ import annotations

import functools

from ninja.errors import HttpError
from ninja.security import HttpBearer

from backend.apps.accounts.services.roles import RoleService
from backend.apps.accounts.services.tokens import TokenService, VerifiedToken


class TokenBearer(HttpBearer):
    def authenticate(self, request, token: str) -> VerifiedToken | None:
        verified = TokenService.verify(token)
        return verified


def require_scope(code: str):
    """Endpoint decorator: token must carry ``code`` and the owner must hold it."""

    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request, *args: object, **kwargs: object):
            auth: VerifiedToken | None = request.auth
            if auth is None:
                raise HttpError(401, 'A valid API token is required.')
            if code not in (auth.row.scopes or []):
                raise HttpError(403, f'This token lacks the {code} scope.')
            if not RoleService.has_perm(auth.user, code):
                raise HttpError(403, f'This login no longer holds {code}.')
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
