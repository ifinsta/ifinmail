"""MTA-STS policy (RFC 8461), rendered per request instead of from a static file."""

from __future__ import annotations

import os

from backend.apps.core.services import SystemSettings
from backend.apps.core.types import SettingKey

_MODES = ('testing', 'enforce', 'none')


class MtaStsService:
    @staticmethod
    def mode() -> str:
        stored = SystemSettings.get(SettingKey.MTA_STS_MODE)
        value = str(stored or os.environ.get('MTA_STS_MODE', 'testing')).lower()
        return value if value in _MODES else 'testing'

    @staticmethod
    def policy_text(mail_hostname: str, mode: str | None = None) -> str:
        mode = mode or MtaStsService.mode()
        max_age = 86400 if mode == 'testing' else 604800
        return f'version: STSv1\r\nmode: {mode}\r\nmx: {mail_hostname}\r\nmax_age: {max_age}\r\n'
