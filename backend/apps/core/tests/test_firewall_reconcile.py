"""The entry-point rules are published without anyone touching a setting, and System health says
whether they are in force."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from django.conf import settings

from backend.apps.accounts.services.system_health import _firewall
from backend.apps.core.platform.models import AuditEvent
from backend.apps.core.platform.services.entrypoints import (
    CATALOGUE,
    RULES_FILE,
    STATUS_FILE,
    EntryPointService,
)
from backend.apps.core.platform.services.runtime import read_runtime_file, write_runtime_file
from backend.apps.core.services import SystemSettings
from backend.apps.core.tasks import reconcile_entrypoints
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.core.types import SettingKey


def report(*, ok: bool, sha: str = '', message: str = 'Rules applied.', age: int = 5) -> None:
    when = (datetime.now(UTC) - timedelta(seconds=age)).strftime('%Y-%m-%dT%H:%M:%SZ')
    write_runtime_file(
        STATUS_FILE,
        json.dumps({'updated': when, 'ok': ok, 'sha256': sha, 'message': message}) + '\n',
    )


class ReconcileTests(MailTablesTestCase):
    def test_a_server_nobody_touched_gets_its_rules_published(self) -> None:
        self.assertIsNone(read_runtime_file(RULES_FILE))
        self.assertTrue(EntryPointService.reconcile())
        text = read_runtime_file(RULES_FILE)
        assert text is not None
        self.assertIn('table inet ifinmail', text)
        self.assertIn('limit rate over 120/minute', text)  # the default cap is in the rules
        self.assertEqual(text, EntryPointService.render())

    def test_it_writes_only_when_something_differs(self) -> None:
        EntryPointService.reconcile()
        before = read_runtime_file(RULES_FILE)
        self.assertFalse(EntryPointService.reconcile())
        self.assertEqual(read_runtime_file(RULES_FILE), before)
        write_runtime_file(RULES_FILE, '# someone edited this by hand\n')
        self.assertTrue(EntryPointService.reconcile())  # drift is corrected
        self.assertEqual(read_runtime_file(RULES_FILE), EntryPointService.render())

    def test_a_changed_setting_changes_the_next_reconcile(self) -> None:
        EntryPointService.reconcile()
        EntryPointService.set_enabled('pop3', False)
        EntryPointService.block('198.51.100.0/24', 'test')
        text = read_runtime_file(RULES_FILE) or ''
        self.assertIn('110', text)
        self.assertIn('198.51.100.0/24', text)
        self.assertFalse(EntryPointService.reconcile())  # apply() already published it

    def test_locked_ports_are_never_closed_by_the_defaults(self) -> None:
        text = EntryPointService.render()
        for entry in CATALOGUE:
            if entry.locked:
                for proto, port in entry.ports:
                    self.assertNotRegex(
                        text,
                        rf'meta l4proto {proto.value} th dport \{{[^}}]*\b{port}\b[^}}]*\}} drop',
                    )

    def test_only_mail_ports_are_capped_and_the_web_is_not(self) -> None:
        capped = {e.key for e in CATALOGUE if e.rate_limited}
        self.assertEqual(capped, {'smtp', 'submission', 'smtps', 'imaps', 'pop3s', 'pop3', 'imap'})
        self.assertFalse({'http', 'https', 'dns'} & capped)

    def test_the_task_reports_and_audits_a_publication_once(self) -> None:
        first = reconcile_entrypoints()
        self.assertTrue(first['wrote'])
        self.assertEqual(first['rate_per_minute'], 120)
        second = reconcile_entrypoints()
        self.assertFalse(second['wrote'])
        self.assertEqual(AuditEvent.objects.filter(action='firewall_published').count(), 1)

    def test_it_is_scheduled(self) -> None:
        entry = settings.CELERY_BEAT_SCHEDULE['reconcile-entrypoints']
        self.assertEqual(entry['task'], 'core.reconcile_entrypoints')


class FirewallHealthTests(MailTablesTestCase):
    def sha(self) -> str:
        return hashlib.sha256((read_runtime_file(RULES_FILE) or '').encode()).hexdigest()

    def test_an_agent_that_is_not_reporting_is_a_warning(self) -> None:
        check = _firewall()
        self.assertEqual(check.state, 'warning')
        self.assertIn('not reporting', check.summary)
        report(ok=True, sha='x', age=600)  # a heartbeat from ten minutes ago
        self.assertEqual(_firewall().state, 'warning')

    def test_rules_not_yet_published_are_waiting_not_an_error(self) -> None:
        report(ok=False, message='Waiting for rules from the console.')
        check = _firewall()
        self.assertEqual(check.state, 'waiting')
        self.assertIn('within five minutes', check.summary)

    def test_published_but_not_yet_applied_is_waiting(self) -> None:
        EntryPointService.reconcile()
        report(ok=False, message='Waiting for rules from the console.')
        self.assertEqual(_firewall().state, 'waiting')

    def test_rules_in_force_say_what_they_do(self) -> None:
        EntryPointService.reconcile()
        report(ok=True, sha=self.sha())
        check = _firewall()
        self.assertEqual(check.state, 'ok')
        self.assertIn('120 new connections a minute', check.summary)
        self.assertIn('7 mail ports', check.summary)

    def test_a_rejected_rule_set_is_an_error(self) -> None:
        EntryPointService.reconcile()
        report(ok=False, sha=self.sha(), message='Rules rejected, previous rules kept: syntax')
        check = _firewall()
        self.assertEqual(check.state, 'error')
        self.assertIn('previous one is still in force', check.summary)

    def test_a_turned_off_cap_is_stated_not_hidden(self) -> None:
        EntryPointService.set_rate_per_minute(0)
        report(ok=True, sha=self.sha())
        check = _firewall()
        self.assertEqual(check.state, 'ok')
        self.assertIn('connection cap is off', check.summary)


class ExpiringBlockTests(MailTablesTestCase):
    def test_a_block_with_a_time_limit_lifts_itself_and_says_so(self) -> None:
        later = datetime.now(UTC) + timedelta(hours=1)
        EntryPointService.block('198.51.100.0/24', 'scanner', expires_at=later)
        EntryPointService.block('192.0.2.0/24', 'kept')
        self.assertIn('198.51.100.0/24', EntryPointService.render())
        self.assertEqual(EntryPointService.expire(), [])  # not yet

        gone = EntryPointService.expire(later + timedelta(seconds=1))
        self.assertEqual(gone, ['198.51.100.0/24'])
        self.assertEqual([r['cidr'] for r in EntryPointService.blocklist()], ['192.0.2.0/24'])
        text = read_runtime_file(RULES_FILE) or ''
        self.assertNotIn('198.51.100.0/24', text)
        self.assertIn('192.0.2.0/24', text)  # a block without a time stays

    def test_an_entry_past_its_time_is_not_in_the_rules_even_before_the_sweep(self) -> None:
        EntryPointService.block(
            '198.51.100.0/24', '', expires_at=datetime.now(UTC) + timedelta(hours=1)
        )
        moment = datetime.now(UTC) + timedelta(hours=2)
        self.assertEqual(EntryPointService.active_blocklist(moment), [])
        self.assertEqual(len(EntryPointService.blocklist()), 1)

    def test_the_task_audits_each_lifted_block(self) -> None:
        EntryPointService.block(
            '198.51.100.0/24', '', expires_at=datetime.now(UTC) - timedelta(minutes=1)
        )
        result = reconcile_entrypoints()
        self.assertEqual(result['lapsed'], ['198.51.100.0/24'])
        self.assertEqual(EntryPointService.blocklist(), [])
        self.assertTrue(AuditEvent.objects.filter(action='network_unblock', user='system').exists())
        self.assertEqual(reconcile_entrypoints()['lapsed'], [])

    def test_a_row_with_a_bad_time_is_kept_rather_than_lost(self) -> None:
        EntryPointService.block('198.51.100.0/24', '')
        SystemSettings.mutate(
            SettingKey.NETWORK_BLOCKLIST,
            lambda rows: [{**r, 'expires': 'garbage'} for r in rows],
            [],
        )
        self.assertEqual(EntryPointService.expire(), [])
        self.assertEqual(len(EntryPointService.blocklist()), 1)
