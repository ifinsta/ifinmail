"""Logging handler — funnels ERROR+ log records into TelemetryService.

Wired via LOGGING in production settings; never raises.
"""

from __future__ import annotations

import logging

from backend.apps.core.telemetry.types import ErrorSource


class TelemetryHandler(logging.Handler):
    """A logging.Handler that records handled errors as telemetry events."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Avoid recursion: telemetry's own loggers never re-enter.
            if record.name == 'backend.telemetry' or record.name.startswith('backend.telemetry.'):
                return
            # Lazy import — avoids AppRegistryNotReady during settings load.
            from backend.apps.core.telemetry.services.telemetry_service import TelemetryService

            message = self.format(record)
            if record.exc_info and record.exc_info[1] is not None:
                TelemetryService.capture(
                    record.exc_info[1],
                    source=ErrorSource.LOGGING,
                    extra={'logger': record.name, 'level': record.levelname},
                )
            elif record.levelno >= logging.ERROR:
                from backend.apps.core.telemetry.types import ErrorSeverity

                level = (
                    ErrorSeverity.CRITICAL
                    if record.levelno >= logging.CRITICAL
                    else ErrorSeverity.ERROR
                )
                TelemetryService.capture(
                    message,
                    severity=level,
                    source=ErrorSource.LOGGING,
                    extra={'logger': record.name, 'level': record.levelname},
                )
        except Exception:
            self.handleError(record)
