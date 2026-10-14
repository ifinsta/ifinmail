"""What the "Website pages" plugin decided: which pages are on, and what the footer says.

Resolved once, when the plugin's settings are published, and kept in the cache: a public page
reads one small entry. Without the plugin (or when it is off) every page is standard, which is
exactly what the site did before the plugin existed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field

from django.core.cache import cache

from backend.apps.core.website.types import BY_KEY, CAPABILITY, KEYS, TAGLINE_MAX, Mode

logger = logging.getLogger('backend')

CACHE_KEY = 'website:policy:v1'
FALLBACK_TTL = 300  # only used when nothing has been published yet (or the cache was flushed)


@dataclass(frozen=True)
class Policy:
    modes: Mapping[str, str] = field(default_factory=dict)
    powered_by: bool = True
    project_links: bool = True
    tagline: str = ''
    footer_note: str = ''
    installed: bool = False  # the plugin is enabled

    def mode(self, key: str) -> str:
        return self.modes.get(key, Mode.STANDARD)

    def as_dict(self) -> dict[str, object]:
        return {
            'modes': dict(self.modes),
            'powered_by': self.powered_by,
            'project_links': self.project_links,
            'tagline': self.tagline,
            'footer_note': self.footer_note,
            'installed': self.installed,
        }


STANDARD = Policy()


def from_values(values: Mapping[str, str]) -> Policy:
    """A policy from capability values; anything unusable falls back to standard."""
    modes: dict[str, str] = {}
    for item in (values.get('modes') or '').split(','):
        page, _, mode = item.partition('=')
        if page in BY_KEY and mode in (Mode.STANDARD, Mode.CUSTOM, Mode.OFF):
            modes[page] = mode
    return Policy(
        modes=modes,
        powered_by=values.get('powered_by', 'yes') != 'no',
        project_links=values.get('project_links', 'yes') != 'no',
        tagline=(values.get('tagline') or '').strip()[:TAGLINE_MAX],
        footer_note=(values.get('footer_note') or '').strip()[:TAGLINE_MAX],
        installed=bool(values),
    )


def _from_json(raw: object) -> Policy | None:
    try:
        data = json.loads(raw) if isinstance(raw, (str, bytes)) else None
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    modes = {
        k: v
        for k, v in (data.get('modes') or {}).items()
        if k in KEYS and v in (Mode.STANDARD, Mode.CUSTOM, Mode.OFF)
    }
    return Policy(
        modes=modes,
        powered_by=data.get('powered_by') is not False,
        project_links=data.get('project_links') is not False,
        tagline=str(data.get('tagline') or '')[:TAGLINE_MAX],
        footer_note=str(data.get('footer_note') or '')[:TAGLINE_MAX],
        installed=bool(data.get('installed')),
    )


def store(serialized: str) -> None:
    """Called when the plugin's settings are published."""
    try:
        cache.set(CACHE_KEY, serialized, None)
    except Exception:  # a cache outage must not fail a settings change; reads fall back
        logger.warning('Could not cache the website policy', exc_info=True)


def current() -> Policy:
    try:
        cached = cache.get(CACHE_KEY)
    except Exception:
        cached = None
    if cached is not None:
        parsed = _from_json(cached)
        if parsed is not None:
            return parsed
    policy = _compute()
    try:
        cache.set(CACHE_KEY, json.dumps(policy.as_dict()), FALLBACK_TTL)
    except Exception:
        pass
    return policy


def _compute() -> Policy:
    from backend.apps.core.plugins.services import InstallationService

    try:
        values = InstallationService.capability_values(CAPABILITY)
    except Exception:  # public pages must render even if the database hiccups
        logger.warning('Could not read the website plugin settings', exc_info=True)
        return STANDARD
    return from_values(values)
