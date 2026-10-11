"""Settings viewset — operations over SystemSettings."""

from __future__ import annotations

from typing import Any

from backend.apps.core.serializers import SettingOut, validate_setting_key
from backend.apps.core.services import SystemSettings


def get_setting(raw_key: str) -> SettingOut:
    """Read a catalogued setting (validates the key first)."""
    key = validate_setting_key(raw_key)
    return SettingOut(key=str(key), value=SystemSettings.get(key))


def set_setting(raw_key: str, value: Any) -> SettingOut:
    """Write a catalogued setting (validates the key first)."""
    key = validate_setting_key(raw_key)
    SystemSettings.set(key, value)
    return SettingOut(key=str(key), value=value)


def delete_setting(raw_key: str) -> SettingOut:
    """Delete a catalogued setting (validates the key first)."""
    key = validate_setting_key(raw_key)
    SystemSettings.delete(key)
    return SettingOut(key=str(key), value=None)


__all__ = ['delete_setting', 'get_setting', 'set_setting']
