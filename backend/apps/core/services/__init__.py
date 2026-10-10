"""Core service layer — foundational services shared across all apps."""

from __future__ import annotations

import logging
from typing import Any

from django.db.utils import DatabaseError

from ..models import SystemSetting
from ..types import SettingKey

logger = logging.getLogger('backend')

_MISSING = object()


class SystemSettings:
    """Single interface for reading and writing persisted system settings."""

    @staticmethod
    def get(key: SettingKey | str, default: Any = None) -> Any:
        try:
            row = SystemSetting.objects.filter(key=str(key)).first()
        except DatabaseError:
            logger.warning('System settings unavailable while reading %s', key)
            return default
        if row is None:
            return default
        return row.value.get('v', default) if isinstance(row.value, dict) else default

    @staticmethod
    def set(key: SettingKey | str, value: Any) -> None:
        SystemSetting.objects.update_or_create(key=str(key), defaults={'value': {'v': value}})

    @staticmethod
    def get_bool(key: SettingKey | str, default: bool = False) -> bool:
        value = SystemSettings.get(key, _MISSING)
        if value is _MISSING:
            return default
        return bool(value)

    @staticmethod
    def get_int(key: SettingKey | str, default: int = 0) -> int:
        value = SystemSettings.get(key, _MISSING)
        if value is _MISSING:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def delete(key: SettingKey | str) -> None:
        SystemSetting.objects.filter(key=str(key)).delete()
