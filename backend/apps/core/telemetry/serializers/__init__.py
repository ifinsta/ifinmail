"""Telemetry serializers — typed dict shaping for API responses."""

from __future__ import annotations

from typing import Any


def serialize_event(event: Any) -> dict[str, Any]:
    created = getattr(event, 'created_at', None)
    return {
        'id': str(getattr(event, 'id', '')),
        'fingerprint': getattr(getattr(event, 'fingerprint', None), 'hash', ''),
        'severity': getattr(event, 'severity', ''),
        'source': getattr(event, 'source', ''),
        'exc_type': getattr(event, 'exc_type', ''),
        'message': getattr(event, 'message', ''),
        'request_path': getattr(event, 'request_path', ''),
        'method': getattr(event, 'method', ''),
        'view_name': getattr(event, 'view_name', ''),
        'correlation_id': getattr(event, 'correlation_id', ''),
        'created_at': created.isoformat() if hasattr(created, 'isoformat') else '',
        'resolved': bool(getattr(event, 'resolved', False)),
    }


def serialize_fingerprint(fp: Any) -> dict[str, Any]:
    return {
        'hash': getattr(fp, 'hash', ''),
        'exc_type': getattr(fp, 'exc_type', ''),
        'view_name': getattr(fp, 'view_name', ''),
        'count': int(getattr(fp, 'count', 0) or 0),
        'status': getattr(fp, 'status', ''),
        'severity_max': getattr(fp, 'severity_max', ''),
    }
