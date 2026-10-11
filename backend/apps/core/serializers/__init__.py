"""core — serializers: shaping for the API flow.

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.apps.core.types import SettingKey


@dataclass(frozen=True)
class SettingOut:
    key: str
    value: object


class SettingNotFoundError(LookupError):
    """Raised when a setting key is unknown to the catalogue."""


def validate_setting_key(raw: str) -> SettingKey:
    """Map a request key to a catalogue SettingKey or raise SettingNotFoundError."""
    try:
        return SettingKey(raw)
    except ValueError as exc:
        raise SettingNotFoundError(f'Unknown setting: {raw}') from exc


__all__ = ['SettingNotFoundError', 'SettingOut', 'validate_setting_key']
