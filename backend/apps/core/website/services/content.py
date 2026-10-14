"""The words an administrator wrote for their own pages.

Stored as one setting (``website.content``: ``{page: {title, heading, ...}}``), read through the
cache. Nothing is ever executed or rendered raw: the body goes through ``markup.render``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from django.core.cache import cache
from django.utils.safestring import SafeString

from backend.apps.core.services import SystemSettings
from backend.apps.core.types import SettingKey
from backend.apps.core.website.services import markup
from backend.apps.core.website.types import BY_KEY, LIMITS, ContentError

logger = logging.getLogger('backend')

FIELDS = tuple(LIMITS)
_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_LINE_FIELDS = ('title', 'description', 'heading', 'lede', 'cta_label', 'cta_url')


def _cache_key(page: str) -> str:
    return f'website:content:{page}:v1'


@dataclass(frozen=True)
class PageContent:
    title: str = ''
    description: str = ''
    heading: str = ''
    lede: str = ''
    body: str = ''
    cta_label: str = ''
    cta_url: str = ''

    @property
    def usable(self) -> bool:
        """Enough to show a page: a heading or some body text."""
        return bool(self.heading.strip() or self.body.strip())

    @property
    def body_html(self) -> SafeString:
        return markup.render(self.body)

    def as_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in FIELDS}


def clean(raw: dict[str, Any]) -> PageContent:
    """Validate what the editor posted; raises ``ContentError`` with one message per field."""
    values: dict[str, str] = {}
    errors: dict[str, str] = {}
    for name in FIELDS:
        text = str(raw.get(name) or '').replace('\r\n', '\n').replace('\r', '\n')
        text = text.strip() if name != 'body' else text.strip('\n')
        if name in _LINE_FIELDS and '\n' in text:
            errors[name] = 'Use a single line.'
        elif _CONTROL.search(text):
            errors[name] = 'Remove the control characters.'
        elif len(text) > LIMITS[name]:
            errors[name] = f'At most {LIMITS[name]} characters (this is {len(text)}).'
        values[name] = text
    url = values.get('cta_url', '')
    if url and 'cta_url' not in errors and not markup.safe_link(url):
        errors['cta_url'] = 'Use an https:// address, a mailto: link, or a path such as /docs/.'
    if bool(values.get('cta_label')) != bool(url) and not errors:
        errors['cta_url' if values.get('cta_label') else 'cta_label'] = (
            'A button needs both its text and its address.'
        )
    if errors:
        raise ContentError(errors)
    return PageContent(**values)


def _load_all() -> dict[str, dict[str, str]]:
    stored = SystemSettings.get(SettingKey.WEBSITE_CONTENT, {})
    return stored if isinstance(stored, dict) else {}


def get(page: str) -> PageContent:
    if page not in BY_KEY:
        return PageContent()
    try:
        cached = cache.get(_cache_key(page))
    except Exception:
        cached = None
    if isinstance(cached, dict):
        return PageContent(**{k: str(cached.get(k, '')) for k in FIELDS})
    row = _load_all().get(page) or {}
    content = PageContent(**{k: str(row.get(k, '')) for k in FIELDS if isinstance(row, dict)})
    try:
        cache.set(_cache_key(page), content.as_dict(), 600)
    except Exception:
        pass
    return content


def save(page: str, raw: dict[str, Any], actor: str) -> PageContent:
    if page not in BY_KEY:
        raise ContentError({'page': 'Unknown page.'})
    content = clean(raw)

    def write(current: Any) -> dict[str, Any]:
        everything = dict(current) if isinstance(current, dict) else {}
        everything[page] = content.as_dict()
        return everything

    SystemSettings.mutate(SettingKey.WEBSITE_CONTENT, write, {})
    _forget(page)
    _audit('website_page_saved', actor, f'Saved the text of the {page} page')
    return content


def clear(page: str, actor: str) -> None:
    def drop(current: Any) -> dict[str, Any]:
        everything = dict(current) if isinstance(current, dict) else {}
        everything.pop(page, None)
        return everything

    SystemSettings.mutate(SettingKey.WEBSITE_CONTENT, drop, {})
    _forget(page)
    _audit('website_page_cleared', actor, f'Removed the custom text of the {page} page')


def has_text() -> set[str]:
    """Pages that have custom text saved (for the overview)."""
    return {
        page
        for page, row in _load_all().items()
        if page in BY_KEY and isinstance(row, dict) and (row.get('heading') or row.get('body'))
    }


def _forget(page: str) -> None:
    try:
        cache.delete(_cache_key(page))
    except Exception:
        logger.warning('Could not clear the cached text of %s', page, exc_info=True)


def _audit(action: str, actor: str, detail: str) -> None:
    from backend.apps.core.platform.services.audit import AuditService

    AuditService.record(action=action, user=actor or None, detail=detail)
