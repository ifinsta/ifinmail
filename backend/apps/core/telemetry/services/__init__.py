"""Telemetry services — re-export layer (AGENTS.md: services/ is the interface).

Installing `logging_handler.TelemetryHandler` runs at ``django.setup()`` time
(before the app registry is ready), so package-level imports must stay lazy:
importing ``.telemetry_service`` here would pull in models too early.
"""

from __future__ import annotations

from typing import Any

_LAZY = {
    'TelemetryService',
    'build_fingerprint',
    'cull_traceback',
    'get_correlation_id',
    'scrub_dict',
    'set_correlation_id',
}

__all__ = sorted(_LAZY)


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        from . import telemetry_service as _service

        return getattr(_service, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
