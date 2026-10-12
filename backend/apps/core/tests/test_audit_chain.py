"""Audit trail: time-based retention, hash chain, export, and the purge button."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.setup_state import SetupState
from backend.apps.core.platform.models import AuditEvent
from backend.apps.core.platform.services.audit import (
    DEFAULT_RETENTION_DAYS,
    MIN_RETENTION_DAYS,
    AuditService,
)
from backend.apps.core.tasks import audit_maintenance
from backend.apps.core.tests.mail_base import MailTablesTestCase

MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'


def _record(count: int, action: str = 'test_event') -> None:
    for i in range(count):
        AuditService.record(action=action, user='admin@ifinmail.test', detail=f'n={i}')


class ChainTests(TestCase):
    def test_every_event_links_to_the_one_before_it(self) -> None:
        _record(3)
        rows = list(AuditEvent.objects.order_by('seq'))
        self.assertEqual([r.seq for r in rows], [1, 2, 3])
        self.assertEqual(rows[0].prev_hash, '')
        self.assertEqual(rows[1].prev_hash, rows[0].entry_hash)
        self.assertEqual(rows[2].prev_hash, rows[1].entry_hash)
        result = AuditService.verify_chain()
        self.assertTrue(result['ok'])
        self.assertEqual((result['checked'], result['head_seq']), (3, 3))
        self.assertEqual(result['head_hash'], rows[2].entry_hash)

    def test_changing_a_stored_event_is_detected(self) -> None:
        _record(3)
        AuditEvent.objects.filter(seq=2).update(detail='nothing to see here')
        result = AuditService.verify_chain()
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], {'seq': 2, 'reason': 'hash'})

    def test_removing_an_event_between_two_others_is_detected(self) -> None:
        _record(4)
        AuditEvent.objects.filter(seq=2).delete()
        result = AuditService.verify_chain()
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], {'seq': 3, 'reason': 'link'})

    def test_a_failed_race_for_a_sequence_number_retries_instead_of_forking(self) -> None:
        _record(1)
        real_create = AuditEvent.objects.create
        calls = {'n': 0}

        def create_once_clashing(**kwargs: object) -> AuditEvent:
            calls['n'] += 1
            if calls['n'] == 1:
                from django.db import IntegrityError

                raise IntegrityError('seq taken')
            return real_create(**kwargs)

        with patch.object(AuditEvent.objects, 'create', side_effect=create_once_clashing):
            _record(1, action='second')
        self.assertEqual(AuditEvent.objects.count(), 2)
        self.assertTrue(AuditService.verify_chain()['ok'])

    def test_the_command_exits_non_zero_when_the_chain_is_broken(self) -> None:
        _record(2)
        call_command('verify_audit_chain', stdout=_Sink())
        AuditEvent.objects.filter(seq=1).update(user='someone-else')
        with self.assertRaises(CommandError):
            call_command('verify_audit_chain', stdout=_Sink())

    def test_the_daily_job_raises_an_alarm_for_a_broken_chain(self) -> None:
        _record(2)
        AuditEvent.objects.filter(seq=1).update(action='forged')
        result = audit_maintenance()
        self.assertFalse(result['ok'])
        self.assertTrue(AuditService.has('audit_chain_broken', severity='err'))


class RetentionTests(TestCase):
    def test_default_and_floor(self) -> None:
        with patch.dict('os.environ', {}, clear=False):
            self.assertEqual(AuditService.retention_days(), DEFAULT_RETENTION_DAYS)
        with patch.dict('os.environ', {'AUDIT_RETENTION_DAYS': '7'}):
            self.assertEqual(AuditService.retention_days(), MIN_RETENTION_DAYS)
        with patch.dict('os.environ', {'AUDIT_RETENTION_DAYS': '90'}):
            self.assertEqual(AuditService.retention_days(), 90)
        with patch.dict('os.environ', {'AUDIT_RETENTION_DAYS': 'forever'}):
            self.assertEqual(AuditService.retention_days(), DEFAULT_RETENTION_DAYS)

    def test_only_events_past_the_window_are_removed_and_the_chain_stays_valid(self) -> None:
        _record(6)
        old = timezone.now() - timedelta(days=DEFAULT_RETENTION_DAYS + 5)
        AuditEvent.objects.filter(seq__lte=3).update(time=old)
        deleted, before = AuditService.purge_expired()
        self.assertEqual((deleted, before), (3, 6))
        self.assertEqual(sorted(AuditEvent.objects.values_list('seq', flat=True)), [4, 5, 6])
        result = AuditService.verify_chain()
        self.assertTrue(result['ok'])
        self.assertEqual(result['checked'], 3)

    def test_the_newest_event_survives_even_when_everything_is_old(self) -> None:
        _record(3)
        old = timezone.now() - timedelta(days=DEFAULT_RETENTION_DAYS + 5)
        AuditEvent.objects.update(time=old)
        AuditService.purge_expired()
        self.assertEqual(list(AuditEvent.objects.values_list('seq', flat=True)), [3])
        _record(1)
        self.assertEqual(AuditEvent.objects.order_by('-seq').first().seq, 4)


class ConsoleTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        SetupState.mark_complete()
        self.admin = MailUser.objects.create_user(
            'root@ifinmail.test', 'Correct-Horse-9', is_staff=True, is_superuser=True
        )
        self.client.force_login(self.admin, backend=MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def test_the_purge_button_cannot_delete_recent_evidence(self) -> None:
        _record(600)
        before = AuditEvent.objects.count()
        response = self.client.post(reverse('accounts:log_purge'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['deleted'], 0)
        self.assertEqual(AuditEvent.objects.count(), before)
        self.assertTrue(AuditService.verify_chain()['ok'])

    def test_jsonl_export_is_complete_and_carries_the_chain(self) -> None:
        _record(250)  # more than the 200-event memory buffer
        response = self.client.get(reverse('accounts:logs_export'), {'format': 'jsonl'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/x-ndjson')
        rows = [json.loads(line) for line in b''.join(response.streaming_content).splitlines()]
        self.assertGreaterEqual(len(rows), 250)
        self.assertEqual(
            set(rows[0]),
            {'seq', 'time', 'user', 'action', 'detail', 'severity', 'prev_hash', 'entry_hash'},
        )
        head = AuditService.verify_chain()
        self.assertEqual(response['X-Audit-Head'], f'{head["head_seq"]}:{head["head_hash"]}')
        self.assertEqual(response['X-Audit-Chain'], 'ok')

    def test_csv_export_reads_the_database_not_the_memory_buffer(self) -> None:
        _record(250)
        AuditService._events = []  # a different worker process has an empty buffer
        response = self.client.get(reverse('accounts:logs_export'))
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.content.decode().strip().splitlines()), 251)

    def test_export_requires_the_audit_permission(self) -> None:
        self.client.logout()
        self.assertEqual(self.client.get(reverse('accounts:logs_export')).status_code, 302)


class _Sink:
    def write(self, *_: object) -> None:
        return None

    def flush(self) -> None:
        return None
