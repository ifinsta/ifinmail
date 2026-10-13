"""Containment of a suspected compromised mailbox: counters, thresholds, pause, notify, resume."""

from __future__ import annotations

import fnmatch
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from django.core import mail
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services import system_health as sh
from backend.apps.accounts.services.roles import RoleService
from backend.apps.accounts.services.setup_state import SetupState
from backend.apps.core.platform.models import AuditEvent
from backend.apps.core.plugins.services import InstallationService
from backend.apps.core.services import SystemSettings
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.core.types import SettingKey
from backend.apps.mail.services import containment
from backend.apps.mail.tasks import check_outbound_containment

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


class FakeRedis:
    """The few Redis commands containment uses, over a dict (strings and sets)."""

    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    def usage(self, login: str, messages: int, recipients: int, domains: int) -> None:
        base = f'ifinmail:out:{login}'
        self.data[f'{base}:m'] = str(messages).encode()
        self.data[f'{base}:r'] = {f'r{i}' for i in range(recipients)}
        self.data[f'{base}:d'] = {f'd{i}' for i in range(domains)}

    def scan_iter(self, match: str = '*', count: int = 10):  # noqa: ARG002
        for key in list(self.data):
            if fnmatch.fnmatch(key, match):
                yield key.encode()

    def get(self, key: str):
        return self.data.get(key)

    def scard(self, key: str) -> int:
        return len(self.data.get(key, ()))

    def delete(self, *keys: str) -> int:
        return sum(1 for k in keys if self.data.pop(k, None) is not None)


class _Base(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.redis = FakeRedis()
        self.admin = MailUser.objects.create_superuser('root@ifinmail.test', 'Correct-Horse-9')
        patcher = patch.object(containment, 'redis_client', return_value=self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)

    def install(self, **settings: object) -> None:
        InstallationService.install('outbound-policy', settings, 'a')

    def policy_file(self) -> dict[str, str]:
        path = Path(self.runtime_dir) / 'postfix-sender-policy.conf'
        out = {}
        for line in path.read_text().splitlines():
            if line and not line.startswith('#'):
                key, _, value = line.partition('=')
                out[key.strip()] = value.strip()
        return out


class EvaluationTests(_Base):
    def test_nothing_happens_without_the_plugin(self) -> None:
        self.redis.usage('alex@ifinmail.test', 5000, 5000, 500)
        self.assertIsNone(containment.thresholds())
        self.assertEqual(containment.evaluate(self.redis, NOW), {'paused': [], 'alerted': []})

    def test_a_mailbox_over_a_limit_is_paused_published_and_reported_once(self) -> None:
        self.install()
        self.redis.usage('alex@ifinmail.test', 40, 800, 30)  # recipients over 500
        self.redis.usage('quiet@ifinmail.test', 20, 30, 5)
        result = containment.evaluate(self.redis, NOW)
        self.assertEqual(result, {'paused': ['alex@ifinmail.test'], 'alerted': []})
        state = containment.paused()['alex@ifinmail.test']
        self.assertIn('800 different recipients (limit 500)', state['reason'])
        self.assertEqual(state['usage'], {'messages': 40, 'recipients': 800, 'domains': 30})
        # Published to Postfix through the dynamic source, for that mailbox only.
        self.assertEqual(self.policy_file()['paused_logins'], 'alex@ifinmail.test')
        # Audited, and the administrators were emailed.
        event = AuditEvent.objects.get(action='sending_paused')
        self.assertEqual((event.severity, event.user), ('warning', 'system'))
        self.assertEqual(len(mail.outbox), 1)
        # The install's ADMIN_EMAIL and every active superuser.
        self.assertEqual(mail.outbox[0].to, ['admin@ifinmail.test', 'root@ifinmail.test'])
        self.assertIn('Sending paused for alex@ifinmail.test', mail.outbox[0].subject)
        # The next run does nothing more for a mailbox that is already paused.
        again = containment.evaluate(self.redis, NOW + timedelta(minutes=1))
        self.assertEqual(again, {'paused': [], 'alerted': []})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(AuditEvent.objects.filter(action='sending_paused').count(), 1)

    def test_each_threshold_counts_and_the_limit_itself_is_allowed(self) -> None:
        self.install(max_messages_hour=100, max_recipients_hour=200, max_domains_hour=50)
        self.redis.usage('a@ifinmail.test', 100, 200, 50)  # exactly at every limit
        self.redis.usage('b@ifinmail.test', 101, 1, 1)
        self.redis.usage('c@ifinmail.test', 1, 1, 51)
        paused = containment.evaluate(self.redis, NOW)['paused']
        self.assertEqual(sorted(paused), ['b@ifinmail.test', 'c@ifinmail.test'])

    def test_notify_only_alerts_without_pausing_and_not_more_than_hourly(self) -> None:
        self.install(containment='notify')
        self.redis.usage('alex@ifinmail.test', 900, 10, 2)
        self.assertEqual(
            containment.evaluate(self.redis, NOW), {'paused': [], 'alerted': ['alex@ifinmail.test']}
        )
        self.assertEqual(containment.paused(), {})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Sending was not paused', mail.outbox[0].body)
        soon = containment.evaluate(self.redis, NOW + timedelta(minutes=30))
        self.assertEqual(soon['alerted'], [])
        later = containment.evaluate(self.redis, NOW + timedelta(minutes=61))
        self.assertEqual(later['alerted'], ['alex@ifinmail.test'])
        self.assertEqual(len(mail.outbox), 2)
        self.assertNotIn('paused_logins', {k: v for k, v in self.policy_file().items() if v})

    def test_action_off_does_nothing(self) -> None:
        self.install(containment='off')
        self.redis.usage('alex@ifinmail.test', 9000, 9000, 900)
        self.assertEqual(containment.evaluate(self.redis, NOW), {'paused': [], 'alerted': []})

    def test_extra_addresses_are_told_too(self) -> None:
        self.install(notify_addresses='Security@ifinmail.test')
        self.redis.usage('alex@ifinmail.test', 900, 10, 2)
        containment.evaluate(self.redis, NOW)
        self.assertEqual(
            sorted(mail.outbox[0].to),
            ['admin@ifinmail.test', 'root@ifinmail.test', 'security@ifinmail.test'],
        )

    def test_a_pause_outlives_uninstalling_the_plugin(self) -> None:
        self.install()
        self.redis.usage('alex@ifinmail.test', 900, 10, 2)
        containment.evaluate(self.redis, NOW)
        InstallationService.uninstall('outbound-policy', 'a')
        self.assertEqual(self.policy_file()['paused_logins'], 'alex@ifinmail.test')

    def test_unrelated_and_malformed_keys_are_ignored(self) -> None:
        self.install()
        self.redis.data['rspamd:other:m'] = b'999999'
        self.redis.data['ifinmail:out:broken'] = b'1'
        self.redis.data['ifinmail:out:x@ifinmail.test:m'] = b'not-a-number-but-bytes'
        with self.assertRaises(ValueError):  # a corrupt counter surfaces; the task catches it
            containment.read_usage(self.redis)
        self.redis.data['ifinmail:out:x@ifinmail.test:m'] = b'3'
        self.assertEqual([u.login for u in containment.read_usage(self.redis)], ['x@ifinmail.test'])

    def test_the_task_survives_a_failing_run(self) -> None:
        with patch.object(containment, 'evaluate', side_effect=RuntimeError('redis down')):
            self.assertEqual(check_outbound_containment(), {'paused': [], 'alerted': []})


class ResumeTests(_Base):
    def test_resume_clears_the_pause_the_counters_and_publishes(self) -> None:
        self.install()
        self.redis.usage('alex@ifinmail.test', 900, 10, 2)
        containment.evaluate(self.redis, NOW)
        self.assertEqual(self.policy_file()['paused_logins'], 'alex@ifinmail.test')
        self.assertTrue(containment.resume('Alex@ifinmail.test', 'root@ifinmail.test'))
        self.assertEqual(containment.paused(), {})
        self.assertEqual(self.policy_file()['paused_logins'], '')
        self.assertEqual(self.redis.data, {})  # counted afresh, or it would trip again at once
        self.assertTrue(AuditEvent.objects.filter(action='sending_resumed').exists())
        self.assertFalse(containment.resume('alex@ifinmail.test', 'root@ifinmail.test'))
        # Without fresh evidence nothing pauses it again.
        self.assertEqual(containment.evaluate(self.redis, NOW)['paused'], [])

    def test_a_mass_compromise_does_not_overflow_the_published_list(self) -> None:
        self.install()
        for i in range(450):  # past the 200 that ordinary address lists allow
            containment.pause(f'user{i}@ifinmail.test', 'burst', None)
        published = self.policy_file()['paused_logins'].split(',')
        self.assertEqual(len(published), 450)

    def test_an_administrator_can_pause_by_hand(self) -> None:
        self.install()
        self.assertTrue(
            containment.pause('intern@ifinmail.test', 'left the company', None, actor='root')
        )
        self.assertFalse(containment.pause('intern@ifinmail.test', 'again', None, actor='root'))
        self.assertEqual(self.policy_file()['paused_logins'], 'intern@ifinmail.test')


class ConsoleTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        SetupState.mark_complete()
        RoleService.ensure_seed()
        self.client.force_login(self.admin, backend='django.contrib.auth.backends.ModelBackend')
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def pause_one(self) -> None:
        self.install()
        self.redis.usage('alex@ifinmail.test', 900, 10, 2)
        containment.evaluate(self.redis, NOW)

    def test_the_page_lists_paused_mailboxes_and_resumes_them(self) -> None:
        self.pause_one()
        page = self.client.get(reverse('accounts:sending'))
        self.assertContains(page, 'alex@ifinmail.test')
        self.assertContains(page, '900 messages (limit 300)')
        self.assertContains(page, 'Resume sending')
        done = self.client.post(
            reverse('accounts:sending_resume'), {'login': 'alex@ifinmail.test'}, follow=True
        )
        self.assertContains(done, 'Sending is resumed for alex@ifinmail.test')
        self.assertContains(done, 'No mailbox is paused.')
        self.assertContains(done, 'Containment is watching every mailbox')
        again = self.client.post(
            reverse('accounts:sending_resume'), {'login': 'alex@ifinmail.test'}, follow=True
        )
        self.assertContains(again, 'is not paused')

    def test_the_page_says_containment_is_off_without_the_plugin(self) -> None:
        page = self.client.get(reverse('accounts:sending'))
        self.assertContains(page, 'Containment is off.')
        self.assertContains(
            page, reverse('accounts:marketplace_plugin', kwargs={'plugin_id': 'outbound-policy'})
        )

    def test_system_health_reports_a_pause_as_an_error(self) -> None:
        self.assertEqual(sh._sending(), [])
        self.install()
        [watching] = sh._sending()
        self.assertEqual((watching.state, watching.title), ('ok', 'Outbound containment'))
        containment.pause('alex@ifinmail.test', 'sent 900 messages', None)
        [check] = sh._sending()
        self.assertEqual(check.state, 'error')
        self.assertIn('alex@ifinmail.test (sent 900 messages)', check.summary)
        self.assertEqual(check.link, reverse('accounts:sending'))

    def test_only_managers_may_resume(self) -> None:
        self.pause_one()
        support = MailUser.objects.create_user(
            'support@ifinmail.test', 'Correct-Horse-9', is_staff=True
        )
        RoleService.assign(support, 'support')
        self.client.force_login(support, backend='django.contrib.auth.backends.ModelBackend')
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()
        self.assertEqual(self.client.get(reverse('accounts:sending')).status_code, 403)
        response = self.client.post(
            reverse('accounts:sending_resume'), {'login': 'alex@ifinmail.test'}
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn('alex@ifinmail.test', containment.paused())
        self.assertIsNotNone(SystemSettings.get(SettingKey.SENDING_PAUSED))
