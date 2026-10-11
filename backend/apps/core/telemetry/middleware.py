"""Telemetry middleware — correlation ids + guaranteed error capture."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from backend.apps.core.telemetry.services.telemetry_service import (
    get_correlation_id,
    set_correlation_id,
)


class CorrelationIdMiddleware:
    """Assign/propagate X-Correlation-ID on every request (outermost)."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = (
            request.headers.get('X-Correlation-ID', '')
            if hasattr(request, 'headers')
            else request.META.get('HTTP_X_CORRELATION_ID', '')
        )
        correlation_id = (incoming or '').strip() or uuid.uuid4().hex[:16]
        set_correlation_id(correlation_id)
        request.correlation_id = correlation_id  # type: ignore[attr-defined]
        response = self.get_response(request)
        response['X-Correlation-ID'] = correlation_id
        return response


class ErrorCaptureMiddleware:
    """Last-chance capture for unhandled exceptions (inner, near the view)."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        try:
            return self.get_response(request)
        except Exception as exc:
            try:
                # Lazy import — safe during app loading.
                from backend.apps.core.telemetry.services.telemetry_service import (
                    TelemetryService,
                )
                from backend.apps.core.telemetry.types import ErrorSource

                result = TelemetryService.capture(exc, source=ErrorSource.DJANGO, request=request)
                request.telemetry_correlation_id = result.get(  # type: ignore[attr-defined]
                    'correlation_id', get_correlation_id()
                )
            except Exception:
                pass
            raise
