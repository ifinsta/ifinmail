"""Whether self-registration is open."""

from __future__ import annotations

import os

from django.core.cache import cache

from backend.apps.core.services import SystemSettings
from backend.apps.core.types import SettingKey

_CACHE_KEY = 'registration_open'


def registration_open() -> bool:
    """Off unless an administrator (or REGISTRATION_OPEN=true at deploy time) enables it."""
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return bool(cached)
    default = os.environ.get('REGISTRATION_OPEN', '').strip().lower() in ('1', 'true', 'yes')
    value = SystemSettings.get_bool(SettingKey.REGISTRATION_OPEN, default)
    cache.set(_CACHE_KEY, value, 30)
    return value


def set_registration_open(value: bool) -> None:
    SystemSettings.set(SettingKey.REGISTRATION_OPEN, value)
    cache.delete(_CACHE_KEY)
