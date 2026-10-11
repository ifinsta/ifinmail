"""Telemetry tests — prove errors are recorded when they occur."""

from __future__ import annotations

import pytest
from django.test import TestCase

from backend.apps.core.telemetry.services.telemetry_service import (
    TelemetryService,
    build_fingerprint,
    scrub_dict,
)
from backend.apps.core.telemetry.types import ErrorSeverity, ErrorSource, ErrorStatus
from backend.apps.core.telemetry.verifications import run_telemetry_selfcheck


class FingerprintTests(TestCase):
    def test_stable_hash(self) -> None:
        h1 = build_fingerprint('ValueError', 'myview', 'a|b')
        h2 = build_fingerprint('ValueError', 'myview', 'a|b')
        h3 = build_fingerprint('TypeError', 'myview', 'a|b')
        assert h1 == h2
        assert h1 != h3
        assert len(h1) == 64


class ScrubTests(TestCase):
    def test_passwords_redacted(self) -> None:
        cleaned = scrub_dict(
            {'password': 'hunter2', 'username': 'alice', 'nested': {'token': 'abc'}}
        )
        assert cleaned['password'] == '[REDACTED]'
        assert cleaned['username'] == 'alice'
        assert cleaned['nested']['token'] == '[REDACTED]'


class CaptureTests(TestCase):
    def test_capture_exception_persists(self) -> None:
        from backend.apps.core.telemetry.services.models import ErrorEvent

        try:
            raise ValueError('telemetry-test-boom')
        except ValueError as exc:
            result = TelemetryService.capture(exc, source=ErrorSource.MANUAL)
        assert result['fingerprint']
        assert result['correlation_id']
        assert ErrorEvent.objects.filter(message__contains='telemetry-test-boom').exists()

    def test_capture_message_and_dedup(self) -> None:
        from backend.apps.core.telemetry.services.models import ErrorFingerprint

        TelemetryService.capture_message('dup-message-xyz', severity=ErrorSeverity.WARNING)
        TelemetryService.capture_message('dup-message-xyz', severity=ErrorSeverity.WARNING)
        fps = ErrorFingerprint.objects.filter(exc_type='Message')
        assert fps.exists()
        assert fps.first().count >= 2  # storms bump count, not rows-spam

    def test_throttle_never_raises(self) -> None:
        for _ in range(30):
            TelemetryService.capture_message('throttle-probe', severity=ErrorSeverity.ERROR)
        assert True

    def test_ack_lifecycle(self) -> None:
        TelemetryService.capture_message('ack-me-pls', severity=ErrorSeverity.ERROR)
        recent = TelemetryService.get_recent(5)
        assert recent
        from backend.apps.core.telemetry.services.models import ErrorEvent

        event = ErrorEvent.objects.order_by('-created_at').first()
        assert event is not None
        ok = TelemetryService.ack_fingerprint(event.fingerprint.hash, ErrorStatus.RESOLVED)
        assert ok

    def test_selfcheck_passes(self) -> None:
        result = run_telemetry_selfcheck()
        assert result['ok'] is True

    def test_get_stats_shape(self) -> None:
        stats = TelemetryService.get_stats()
        assert 'open_critical_24h' in stats
        assert 'total_24h' in stats


@pytest.mark.django_db
@pytest.mark.django_db
def test_logging_handler_records_errors(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from backend.apps.core.telemetry.services.logging_handler import TelemetryHandler

    handler = TelemetryHandler()
    test_logger = logging.getLogger('backend.telemetry-probe')
    test_logger.addHandler(handler)
    test_logger.setLevel(logging.ERROR)
    try:
        test_logger.error('probe-error-12345')
    finally:
        test_logger.removeHandler(handler)
    recent = TelemetryService.get_recent(10)
    assert any('probe-error-12345' in (e.get('detail', '') or '') for e in recent)
