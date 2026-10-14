"""The look the console and the public site start with, until a person chooses their own.

A person's choice is kept in their browser (``ifinmail-theme-init.js``). This is only the default
for browsers that have not chosen: one setting, read through the cache because every page asks.
"""

from __future__ import annotations

import logging

from django.core.cache import cache

from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.services import SystemSettings
from backend.apps.core.types import SettingKey

logger = logging.getLogger('backend')

DEFAULT = 'smooth'
THEMES = ('smooth', 'light', 'dark', 'auto', 'contrast')
_CACHE_KEY = 'appearance:default-theme:v1'


def default_theme() -> str:
    try:
        cached = cache.get(_CACHE_KEY)
    except Exception:
        cached = None
    if cached in THEMES:
        return cached
    value = SystemSettings.get(SettingKey.DEFAULT_THEME, DEFAULT)
    value = value if value in THEMES else DEFAULT
    try:
        cache.set(_CACHE_KEY, value, 3600)
    except Exception:
        pass
    return value


def set_default_theme(value: str, actor: str) -> str:
    if value not in THEMES:
        raise ValueError('Choose one of the listed themes.')
    SystemSettings.set(SettingKey.DEFAULT_THEME, value)
    try:
        cache.delete(_CACHE_KEY)
    except Exception:
        logger.warning('Could not clear the cached default theme', exc_info=True)
    AuditService.record(
        action='default_theme_set', user=actor or None, detail=f'Default theme set to {value}'
    )
    return value
