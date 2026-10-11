"""Telemetry viewsets — thin wrappers over services (AGENTS.md API flow)."""

from backend.apps.core.telemetry.services.telemetry_service import TelemetryService
from backend.apps.core.telemetry.types import ErrorStatus


class TelemetryViewSet:
    """Non-DRF viewset shim: keeps api.py → viewsets → services → models chain explicit."""

    @staticmethod
    def list_errors(limit: int = 50) -> list[dict]:
        return TelemetryService.get_recent(limit)

    @staticmethod
    def stats() -> dict:
        return TelemetryService.get_stats()

    @staticmethod
    def ack(fingerprint_hash: str, status: ErrorStatus | str) -> bool:
        return TelemetryService.ack_fingerprint(fingerprint_hash, status)
