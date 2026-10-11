"""telemetry — web.py: server-rendered helpers (web flow: web → views → services)."""

from django.http import HttpRequest

from backend.apps.core.telemetry.services.telemetry_service import TelemetryService


def telemetry_context(request: HttpRequest, limit: int = 50) -> dict:
    """Context fragment merged into the admin logs page."""
    events = TelemetryService.get_recent(limit)
    stats = TelemetryService.get_stats()
    return {'telemetry_events': events, 'telemetry_stats': stats}
