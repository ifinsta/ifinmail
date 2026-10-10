"""Typed building blocks for the Settings hub."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SettingsGroupKey(StrEnum):
    WORKSPACE = 'workspace'
    ACCESS = 'access'
    PERSONALIZATION = 'personalization'
    SYSTEM = 'system'


class SettingsIcon(StrEnum):
    """Icon names rendered by includes/settings_icon.html."""

    GENERAL = 'general'
    DOMAINS = 'domains'
    MAIL = 'mail'
    DELIVERABILITY = 'deliverability'
    SPAM = 'spam'
    USERS = 'users'
    SECURITY = 'security'
    LOGS = 'logs'
    MONITORING = 'monitoring'
    STORAGE = 'storage'
    MAINTENANCE = 'maintenance'
    ABOUT = 'about'
    APPEARANCE = 'appearance'
    LANGUAGE = 'language'


@dataclass(frozen=True)
class SettingsItem:
    """One entry in the Settings navigation.

    ``key`` equals the ``active_section`` context value of the page that
    renders the item, so the navigation can mark the current page.
    ``url_name`` is a reversible URL name; pages that already existed keep
    their URLs, new pages live under ``accounts:settings_page``.
    """

    key: str
    title: str
    description: str
    icon: SettingsIcon
    url_name: str
    keywords: tuple[str, ...] = ()
    url_kwargs: dict[str, str] = field(default_factory=dict)
    staff_only: bool = True


@dataclass(frozen=True)
class SettingsGroup:
    key: SettingsGroupKey
    title: str
    items: tuple[SettingsItem, ...]


@dataclass(frozen=True)
class ConfigRow:
    """A read-only effective setting. ``secret`` rows never expose their value."""

    label: str
    value: str
    env: str = ''
    hint: str = ''
    mono: bool = False
    tone: str = ''  # '', 'success', 'warning', 'danger'


@dataclass(frozen=True)
class ConfigSection:
    title: str
    rows: tuple[ConfigRow, ...]
    description: str = ''
