# ruff: noqa: E501  -- static SVG path data
"""Template tags for the Settings hub navigation."""

from __future__ import annotations

from typing import Any

from django import template
from django.utils.html import format_html
from django.utils.safestring import SafeString, mark_safe

from ..services.settings_catalogue import SettingsCatalogue
from ..types.settings import SettingsIcon

register = template.Library()

# Trusted static SVG shapes (24x24, stroke icons) keyed by SettingsIcon.
_SHAPES: dict[str, str] = {
    SettingsIcon.GENERAL: '<path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.6-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.3 7A2 2 0 1 1 7.1 4.2l.1.1A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1A2 2 0 1 1 19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.1a2 2 0 1 1 0 4H21a1.7 1.7 0 0 0-1.6 1Z"/>',
    SettingsIcon.DOMAINS: '<path d="M4 4h16v6H4zM4 14h16v6H4z"/><path d="M8 7h.01M8 17h.01"/>',
    SettingsIcon.MAIL: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    SettingsIcon.DELIVERABILITY: '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/>',
    SettingsIcon.SPAM: '<path d="M12 3 5 6v5c0 4.5 2.9 8.6 7 10 4.1-1.4 7-5.5 7-10V6z"/><path d="M12 8v5M12 16h.01"/>',
    SettingsIcon.USERS: '<path d="M16 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2"/><circle cx="9.5" cy="7" r="4"/><path d="M20 8v6M23 11h-6"/>',
    SettingsIcon.SECURITY: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    SettingsIcon.LOGS: '<path d="M4 4h8l2 3h6v13H4z"/><path d="M8 12h8M8 16h6"/>',
    SettingsIcon.MONITORING: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    SettingsIcon.STORAGE: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
    SettingsIcon.MAINTENANCE: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.4 2.4-2.6-.6-.6-2.6z"/>',
    SettingsIcon.ABOUT: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    SettingsIcon.APPEARANCE: '<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 0 0 18z" fill="currentColor"/>',
    SettingsIcon.CERTIFICATE: '<path d="M12 3 5 6v5c0 4.5 2.9 8.6 7 10 4.1-1.4 7-5.5 7-10V6z"/><path d="m9 12 2 2 4-4"/>',
    SettingsIcon.NETWORK: '<circle cx="12" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="19" r="2"/><path d="M12 7v5M12 12l-6 5M12 12l6 5"/>',
    SettingsIcon.DEVICE: '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
    SettingsIcon.ACCOUNT: '<circle cx="12" cy="8" r="4"/><path d="M5 21v-1a5 5 0 0 1 5-5h4a5 5 0 0 1 5 5v1"/>',
    'search': '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    SettingsIcon.LANGUAGE: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
}


@register.simple_tag
def settings_icon(name: str, css_class: str = 'ifinmail-icon') -> SafeString:
    shape = _SHAPES.get(str(name), _SHAPES[SettingsIcon.GENERAL])
    return format_html(
        '<svg class="{}" viewBox="0 0 24 24" aria-hidden="true">{}</svg>',
        css_class,
        mark_safe(shape),  # noqa: S308 - static shapes defined above
    )


@register.inclusion_tag('includes/settings_nav.html', takes_context=True)
def settings_nav(context: template.Context) -> dict[str, Any]:
    active = context.get('active_section', '')
    groups = []
    for group in SettingsCatalogue.groups():
        items = [
            {'item': item, 'url': SettingsCatalogue.url_for(item), 'active': item.key == active}
            for item in group.items
        ]
        groups.append({'group': group, 'items': items})
    return {'nav_groups': groups, 'on_hub': active == 'settings'}


@register.simple_tag
def settings_url(item: Any) -> str:
    return SettingsCatalogue.url_for(item)


@register.simple_tag(takes_context=True)
def settings_is_active(context: template.Context) -> bool:
    """True when the current page is the hub or any page listed in the catalogue."""
    active = context.get('active_section', '')
    return active == 'settings' or SettingsCatalogue.get(active) is not None


@register.simple_tag
def health_badge() -> int | None:
    """Issues on the System health page, from its last cached report (never runs the checks)."""
    from ..services.system_health import SystemHealth

    try:
        return SystemHealth.cached_badge()
    except Exception:  # the sidebar must render even if the cache is unavailable
        return None
