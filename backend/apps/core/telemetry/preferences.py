"""Telemetry preferences — admin-tunable knobs backed by SystemSetting + env."""

from __future__ import annotations

import os
from typing import Any


class TelemetryPreferences:
    """Single place for retention / sampling / enablement defaults."""

    @staticmethod
    def enabled() -> bool:
        return os.environ.get('TELEMETRY_ENABLED', 'True').lower() == 'true'

    @staticmethod
    def retention_days(default: int = 30) -> int:
        try:
            return int(os.environ.get('TELEMETRY_RETENTION_DAYS', str(default)))
        except ValueError:
            return default

    @staticmethod
    def sample_rate_warning() -> float:
        try:
            return float(os.environ.get('TELEMETRY_SAMPLE_WARNING', '1.0'))
        except ValueError:
            return 1.0

    @staticmethod
    def as_dict() -> dict[str, Any]:
        return {
            'enabled': TelemetryPreferences.enabled(),
            'retention_days': TelemetryPreferences.retention_days(),
            'sample_rate_warning': TelemetryPreferences.sample_rate_warning(),
            'sentry_configured': bool(os.environ.get('SENTRY_DSN', '')),
        }
