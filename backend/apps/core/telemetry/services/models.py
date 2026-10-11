"""services/models.py — re-export proxy for INTRA-APP use only.

Cross-app imports of ``services.models`` are FORBIDDEN (AGENTS.md).
Other apps must use ``TelemetryService`` or import from ``models/``.
"""

from backend.apps.core.telemetry.models import ErrorEvent, ErrorFingerprint

__all__ = ['ErrorEvent', 'ErrorFingerprint']
