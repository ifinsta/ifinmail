"""System health page: one list of what is wrong, pending or recommended."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import UTC, datetime
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services import system_health as sh
from backend.apps.core.tests.mail_base import MailTablesTestCase

GOOD = 'Correct-Horse-9'
LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


def _report() -> sh.HealthReport:
    return sh.HealthReport(
        checked_at=datetime.now(UTC),
        checks=[
            sh.HealthCheck('ptr', sh.GROUP_IDENTITY, 'Reverse DNS (PTR)', sh.ERROR,
                           '192.0.2.10 points back to nothing.', 'Set it at your VPS provider.',
                           [('Reverse DNS name', 'mail.ifinmail.test')]),
            sh.HealthCheck('backups', sh.GROUP_SERVER, 'Backups', sh.WAITING, 'First backup tonight.'),
            sh.HealthCheck('disk', sh.GROUP_SERVER, 'Disk space', sh.OK, '17 GB free.'),
        ],
    )


@override_settings(CACHES=LOCMEM)
class SystemHealthPageTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        from backend.apps.accounts.services.setup_state import SetupState

        SetupState.mark_complete()
        admin = MailUser.objects.create_superuser('admin@ifinmail.test', GOOD)
        self.client.force_login(admin)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def test_page_lists_todo_in_progress_and_passing_checks(self) -> None:
        with patch.object(sh, '_collect', return_value=_report()):
            response = self.client.get(reverse('accounts:system_health'))
        self.assertContains(response, 'Reverse DNS (PTR)')
        self.assertContains(response, 'Set it at your VPS provider.')
        self.assertContains(response, 'mail.ifinmail.test')
        self.assertContains(response, 'First backup tonight.')
        self.assertContains(response, '1 check passes')

    def test_sidebar_shows_the_cached_issue_count_without_running_checks(self) -> None:
        with patch.object(sh, '_collect', side_effect=AssertionError('must not run')):
            page = self.client.get(reverse('accounts:dashboard'))
        self.assertNotContains(page, 'ifinmail-nav-count')
        self.assertContains(page, reverse('accounts:system_health'))
        cache.set(sh.CACHE_KEY, _report(), 60)
        with patch.object(sh, '_collect', side_effect=AssertionError('must not run')):
            page = self.client.get(reverse('accounts:dashboard'))
        self.assertContains(page, '<b class="ifinmail-nav-count"')

    def test_recheck_bypasses_the_cache(self) -> None:
        cache.set(sh.CACHE_KEY, _report(), 60)
        fresh = sh.HealthReport(checked_at=datetime.now(UTC), checks=[])
        with patch.object(sh, '_collect', return_value=fresh) as collect:
            response = self.client.post(reverse('accounts:system_health_recheck'))
        self.assertRedirects(response, reverse('accounts:system_health'), fetch_redirect_response=False)
        collect.assert_called_once()
        self.assertEqual(cache.get(sh.CACHE_KEY).checks, [])

    def test_a_crashing_check_becomes_could_not_check(self) -> None:
        def boom() -> None:
            raise RuntimeError('lookup exploded')

        rows = sh._check(boom)
        self.assertEqual(rows[0].state, sh.UNKNOWN)


class QueueCheckTests(SimpleTestCase):
    def _queue(self, **data: int) -> sh.HealthCheck:
        handle, path = tempfile.mkstemp()
        with os.fdopen(handle, 'w') as f:
            json.dump({'updated': int(time.time()), **data}, f)
        self.addCleanup(os.remove, path)
        with patch.object(sh, '_QUEUE_FILE', path):
            return sh._mail_queue()

    def test_empty_queue_is_ok(self) -> None:
        self.assertEqual(self._queue(active=0, deferred=0, hold=0).state, sh.OK)

    def test_deferred_mail_is_a_warning_and_a_day_old_backlog_an_error(self) -> None:
        self.assertEqual(self._queue(deferred=3, oldest_deferred_seconds=600).state, sh.WARNING)
        self.assertEqual(self._queue(deferred=3, oldest_deferred_seconds=90000).state, sh.ERROR)

    def test_missing_report_is_unknown(self) -> None:
        with patch.object(sh, '_QUEUE_FILE', '/nonexistent/mailq.json'):
            self.assertEqual(sh._mail_queue().state, sh.UNKNOWN)


class BlocklistTests(SimpleTestCase):
    def test_a_refused_spamhaus_query_is_not_reported_as_clean(self) -> None:
        from backend.apps.core.platform.services import deliverability

        with patch.object(deliverability, '_resolve', return_value=['127.255.255.254']):
            result = deliverability.DeliverabilityService._check_blacklists('192.0.2.10')
        self.assertEqual(result['status'], 'warn')
        self.assertIsNone(next(iter(result['listings'].values()))['listed'])

    def test_a_listing_is_an_error_row(self) -> None:
        from backend.apps.core.platform.services import deliverability

        with patch.object(deliverability, '_resolve', return_value=['127.0.0.2']):
            row = sh._blocklists('192.0.2.10')
        self.assertEqual(row.state, sh.ERROR)


class RoleAddressTests(MailTablesTestCase):
    def test_postmaster_forwarding_to_a_login_without_mailbox_is_flagged(self) -> None:
        from backend.apps.mail.models import Alias
        from backend.apps.mail.services import MailboxService

        domain = self.make_domain('ifinmail.test')
        MailboxService.create('ifinmail.test', 'douglas', GOOD)
        for role in ('postmaster', 'abuse'):
            Alias.objects.create(domain=domain, source=f'{role}@ifinmail.test', destination='admin@ifinmail.test')
        row = sh._role_addresses('ifinmail.test', 'ifinmail.test')
        self.assertEqual(row.state, sh.WARNING)
        self.assertIn('no mailbox', row.summary)
        Alias.objects.filter(source='postmaster@ifinmail.test').update(destination='douglas@ifinmail.test')
        Alias.objects.filter(source='abuse@ifinmail.test').update(destination='douglas@ifinmail.test')
        self.assertEqual(sh._role_addresses('ifinmail.test', 'ifinmail.test').state, sh.OK)


@override_settings(CACHES=LOCMEM)
class HealthPageTests(MailTablesTestCase):
    """The page's own behaviour: verdict, groups, check cards."""

    def setUp(self) -> None:
        super().setUp()
        from backend.apps.accounts.services.setup_state import SetupState

        SetupState.mark_complete()

        self.admin = MailUser.objects.create_superuser('admin@ifinmail.test', GOOD)
        self.client.force_login(self.admin)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()
        self.url = reverse('accounts:system_health')

    def report(self, *checks) -> sh.HealthReport:
        return sh.HealthReport(checked_at=datetime.now(UTC), checks=list(checks))

    def check(self, key, group, title, state, summary='x', **extra) -> sh.HealthCheck:
        return sh.HealthCheck(key, group, title, state, summary, **extra)

    def get(self, report: sh.HealthReport, **params):
        with patch(
            'backend.apps.accounts.views.system_health.SystemHealth.report', return_value=report
        ):
            return self.client.get(self.url, params)

    def test_verdict_names_the_first_thing_to_fix(self) -> None:
        page = self.get(
            self.report(
                self.check('ptr', 'Server identity', 'Reverse DNS (PTR)', 'error', fix='Ask VPS'),
                self.check('bk', 'Server', 'Backup key', 'warning'),
                self.check('ok', 'Server', 'Disk space', 'ok'),
            )
        )
        self.assertContains(page, '1 thing needs fixing before mail is reliable.')
        self.assertContains(page, 'Start with: <strong>Reverse DNS (PTR)</strong>')
        self.assertContains(page, 'ifinmail-hbanner--danger')
        self.assertContains(page, '#check-server-identity-ptr')
        self.assertContains(page, 'How to fix')
        self.assertContains(page, 'Ask VPS')

    def test_each_verdict_tone(self) -> None:
        cases = (
            (('warning',), 'Mail should work. 1 improvement is recommended.', 'warning'),
            (('waiting',), 'Nothing is wrong. The server is still finishing 1 item.', 'info'),
            (('ok',), 'Everything checks out.', 'ok'),
        )
        for states, words, tone in cases:
            with self.subTest(tone=tone):
                page = self.get(self.report(*[self.check('k', 'Server', 'T', s) for s in states]))
                self.assertContains(page, words)
                self.assertContains(page, f'ifinmail-hbanner--{tone}')

    def test_groups_filter_the_checks_and_count_what_needs_attention(self) -> None:
        report = self.report(
            self.check('a', 'Mail delivery', 'Inbound SMTP', 'error'),
            self.check('b', 'Mail delivery', 'Queue', 'warning'),
            self.check('c', 'example.test', 'SPF', 'ok'),
        )
        page = self.get(report)
        self.assertContains(page, '?group=mail-delivery')
        self.assertContains(page, '2 need attention')
        self.assertContains(page, 'Inbound SMTP')
        self.assertContains(page, 'SPF')
        only = self.get(report, group='exampletest')
        self.assertContains(only, 'id="check-exampletest-c"')
        self.assertNotContains(only, 'id="check-mail-delivery-a"')
        # The verdict and counts always describe the whole server.
        self.assertContains(only, '1 thing needs fixing')
        # Unknown groups show everything.
        self.assertContains(self.get(report, group='nope'), 'Inbound SMTP')

    def test_values_can_be_copied_and_links_and_assistant_are_offered(self) -> None:
        report = self.report(
            self.check(
                'ptr', 'Server identity', 'PTR', 'error',
                values=[('IP address', '203.0.113.5')],
                link='/accounts/settings/',
                link_label='Network',
            )
        )
        page = self.get(report)
        self.assertContains(page, 'data-copy="203.0.113.5"')
        self.assertContains(page, 'href="/accounts/settings/"')
        self.assertNotContains(page, 'Ask the assistant')  # no model connected
        from backend.apps.core.assistant.services import config as assistant_config

        connected = assistant_config.ModelSettings(base_url='http://x/v1', model='m')
        with patch.object(assistant_config, 'current', return_value=connected):
            page = self.get(report)
        self.assertContains(page, 'Ask the assistant')
        self.assertContains(page, 'accounts/assistant/?q=')

    def test_passing_checks_are_compact_and_collapsed(self) -> None:
        page = self.get(self.report(self.check('d', 'Server', 'Disk space', 'ok', '62% free')))
        self.assertContains(page, '1 check passes')
        self.assertContains(page, 'ifinmail-hc--compact')
        self.assertContains(page, '62% free')
        self.assertContains(page, 'Nothing to do here.')
