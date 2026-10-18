"""Who a failed sign-in is counted against (django-axes hook)."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest


def lockout_username(request: HttpRequest, credentials: dict[str, Any] | None = None) -> str:
    """The account a sign-in attempt names: the credentials, else the form's `email` field.

    The console's form posts `email`, not Axes' default `username`, so without this every
    failure was recorded against an empty name.
    """
    for key in ('username', 'email'):
        value = (credentials or {}).get(key)
        if value:
            return str(value).strip().lower()
    post = getattr(request, 'data', None) or getattr(request, 'POST', {})
    return str(post.get('email', '') or post.get('username', '')).strip().lower()
