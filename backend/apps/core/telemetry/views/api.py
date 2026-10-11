"""Telemetry API views — backwards-compat shim (API flow lives in viewsets/).

New code imports from ``backend.apps.core.telemetry.api``
(urls.py → api.py → viewsets/).
"""

from backend.apps.core.telemetry.viewsets import (
    telemetry_ack,
    telemetry_errors,
    telemetry_fingerprints,
    telemetry_stats,
)

__all__ = ['telemetry_ack', 'telemetry_errors', 'telemetry_fingerprints', 'telemetry_stats']
