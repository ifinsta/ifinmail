"""Telemetry models — persistent error events grouped by fingerprint.

Follows AGENTS.md governance: inherit CoreModel, all access via services/.
"""

from __future__ import annotations

from django.db import models

from backend.apps.core.base.models.base import CoreModel
from backend.apps.core.telemetry.types import ErrorSeverity, ErrorSource, ErrorStatus


class ErrorFingerprint(CoreModel):
    """Dedup key — one row per distinct error signature.

    Storms of identical errors bump ``count`` instead of spamming the UI.
    """

    hash = models.CharField(max_length=64, unique=True)
    exc_type = models.CharField(max_length=255, default='', blank=True)
    view_name = models.CharField(max_length=255, default='', blank=True)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    count = models.BigIntegerField(default=0)
    status = models.CharField(
        max_length=16,
        choices=[(s.value, s.name) for s in ErrorStatus],
        default=ErrorStatus.OPEN.value,
    )
    severity_max = models.CharField(
        max_length=16,
        choices=[(s.value, s.name) for s in ErrorSeverity],
        default=ErrorSeverity.ERROR.value,
    )

    class Meta:
        db_table = 'ifinmail_error_fingerprint'
        ordering = ['-last_seen']
        indexes = [
            models.Index(fields=['status', '-last_seen']),
        ]

    def __str__(self) -> str:
        return f'{self.exc_type or "error"} x{self.count} [{self.status}]'


class ErrorEvent(CoreModel):
    """One recorded error occurrence (sampled — see TelemetryService)."""

    fingerprint = models.ForeignKey(
        ErrorFingerprint,
        on_delete=models.PROTECT,
        related_name='events',
    )
    severity = models.CharField(
        max_length=16,
        choices=[(s.value, s.name) for s in ErrorSeverity],
        default=ErrorSeverity.ERROR.value,
    )
    source = models.CharField(
        max_length=16,
        choices=[(s.value, s.name) for s in ErrorSource],
        default=ErrorSource.DJANGO.value,
    )
    exc_type = models.CharField(max_length=255, default='', blank=True)
    message = models.CharField(max_length=2000, default='', blank=True)
    traceback = models.TextField(default='', blank=True)
    request_path = models.CharField(max_length=1024, default='', blank=True)
    method = models.CharField(max_length=16, default='', blank=True)
    view_name = models.CharField(max_length=255, default='', blank=True)
    user_repr = models.CharField(max_length=255, default='', blank=True)
    correlation_id = models.CharField(max_length=64, default='', blank=True, db_index=True)
    release = models.CharField(max_length=64, default='', blank=True)
    environment = models.CharField(max_length=64, default='', blank=True)
    context = models.JSONField(default=dict, blank=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        db_table = 'ifinmail_error_event'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['fingerprint', '-created_at']),
            models.Index(fields=['severity', '-created_at']),
            models.Index(fields=['source', '-created_at']),
            models.Index(fields=['resolved', '-created_at']),
        ]

    def __str__(self) -> str:
        return f'{self.exc_type or self.source}: {self.message[:80]}'
