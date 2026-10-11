"""Typed values for per-user session inspection."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserSession:
    """One Django session belonging to a user (never exposes the full key)."""

    session_key: str
    key_hint: str  # first characters only, for identification
    expire_date: str
    is_current: bool
