"""Telemetry signal handlers — request exceptions + Celery task failures."""

from __future__ import annotations

import logging
from typing import Any

from django.core.signals import got_request_exception
from django.dispatch import receiver

logger = logging.getLogger('backend.telemetry')


@receiver(got_request_exception)
def _capture_request_exception(sender: Any, request: Any, **kwargs: Any) -> None:
    """Persist every unhandled Django exception (best-effort, never raises)."""
    try:
        exc = kwargs.get('exception')
        from backend.apps.core.telemetry.services.telemetry_service import TelemetryService
        from backend.apps.core.telemetry.types import ErrorSource

        if isinstance(exc, BaseException):
            TelemetryService.capture(exc, source=ErrorSource.DJANGO, request=request)
    except Exception as exc:
        logger.warning('Telemetry signal handler failed: %s', exc)


def _capture_task_failure(
    sender: Any, task_id: str, exception: BaseException, args: Any, kwargs: Any, **extra: Any
) -> None:
    try:
        from backend.apps.core.telemetry.services.telemetry_service import TelemetryService
        from backend.apps.core.telemetry.types import ErrorSource

        TelemetryService.capture(
            exception,
            source=ErrorSource.CELERY,
            extra={'task': getattr(sender, 'name', str(sender)), 'task_id': task_id},
        )
    except Exception as exc:
        logger.warning('Telemetry celery hook failed: %s', exc)


try:  # Celery is optional in some test contexts.
    from celery.signals import task_failure

    task_failure.connect(_capture_task_failure, dispatch_uid='ifinmail-telemetry-task-failure')
except Exception:  # pragma: no cover — celery import guard
    pass
