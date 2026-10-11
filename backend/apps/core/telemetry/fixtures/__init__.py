"""telemetry — fixtures placeholder (synthetic errors for dev/tests)."""

from __future__ import annotations


def sample_error_payload() -> dict:
    return {
        'exc_type': 'RuntimeError',
        'message': 'RuntimeError: sample telemetry fixture',
        'severity': 'ERROR',
        'source': 'MANUAL',
    }
