"""Telemetry verifications — self-test proving errors get recorded."""

from __future__ import annotations

from typing import Any


def run_telemetry_selfcheck() -> dict[str, Any]:
    """Raise a synthetic error through the full pipeline and assert storage.

    Used by /health/full and the ``check_telemetry`` management command.
    Never raises — returns ``{'ok': bool, ...}``.
    """
    from backend.apps.core.telemetry.services.telemetry_service import TelemetryService
    from backend.apps.core.telemetry.types import ErrorSource

    marker = 'telemetry-selfcheck'
    try:
        try:
            raise RuntimeError(f'{marker}: synthetic verification error')
        except RuntimeError as exc:
            result = TelemetryService.capture(
                exc, source=ErrorSource.HEALTH, extra={'selfcheck': True}
            )
        fingerprint = result.get('fingerprint', '')
        # Synchronous path persists immediately in tests; in prod on_commit
        # may defer — fall back to the memory buffer as proof of capture.
        recent = TelemetryService.get_recent(50)
        found = any(marker in (e.get('detail', '') or '') for e in recent)
        ok = bool(fingerprint) and found
        return {
            'ok': ok,
            'fingerprint': fingerprint,
            'correlation_id': result.get('correlation_id', ''),
            'matched_in_recent': found,
        }
    except Exception as exc:  # pragma: no cover — defensive
        return {'ok': False, 'error': str(exc)}
