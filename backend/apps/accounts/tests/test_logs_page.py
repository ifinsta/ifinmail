"""System logs page: filters, pagination, levels, live data, export and permissions."""

from __future__ import annotations

import csv
import io
import json
from datetime import timedelta

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.roles import RoleService
from backend.apps.accounts.services.setup_state import SetupState
from backend.apps.core.platform.models import AuditEvent
from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.tests.mail_base import MailTablesTestCase

BACKEND = 'django.contrib.auth.backends.ModelBackend'


def record(action: str, detail: str = '', *, user: str = 'root@ifinmail.test', severity='info'):
    AuditService.record(action=action, user=user, detail=detail, severity=severity)


class LogsPageTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        SetupState.mark_complete()
        RoleService.ensure_seed()
        self.admin = MailUser.objects.create_user(
            'root@ifinmail.test', 'Correct-Horse-9', is_staff=True, is_superuser=True
        )
        self.client.force_login(self.admin, backend=BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()
        self.url = reverse('accounts:logs')

    def seed(self) -> None:
        record('mailbox_created', 'alex@ifinmail.test')
        record('login_failed', 'bad password for sam@ifinmail.test', severity='warning')
        record('plugin_failed', 'mailbox-care could not be applied', severity='err')
        record('domain_verified', 'ifinmail.test', user='system')

    def test_page_shows_events_levels_and_integrity(self) -> None:
        self.seed()
        page = self.client.get(self.url)
        self.assertContains(page, 'System logs')
        for expected in ('mailbox_created', 'login_failed', 'plugin_failed', 'domain_verified'):
            self.assertContains(page, expected)
        self.assertContains(page, 'ifinmail-badge--danger">Error<')
        self.assertContains(page, 'ifinmail-badge--warning">Warning<')
        self.assertContains(page, 'Intact')
        self.assertContains(page, '4 entries verified')
        self.assertContains(page, 'Showing 1–4 of 4')

    def test_filter_by_level_text_and_period(self) -> None:
        self.seed()
        errors = self.client.get(self.url, {'level': 'error'})
        self.assertContains(errors, 'plugin_failed')
        self.assertNotContains(errors, 'mailbox_created')
        warnings = self.client.get(self.url, {'level': 'warning'})
        self.assertContains(warnings, 'login_failed')
        self.assertNotContains(warnings, 'plugin_failed')
        info = self.client.get(self.url, {'level': 'info'})
        self.assertContains(info, 'mailbox_created')
        self.assertNotContains(info, 'login_failed')
        # Text matches the action, the detail and the person.
        for term, present in (
            ('alex@', 'mailbox_created'),
            ('bad password', 'login_failed'),
            ('system', 'domain_verified'),
            ('PLUGIN_FAILED', 'plugin_failed'),
        ):
            page = self.client.get(self.url, {'q': term})
            self.assertContains(page, present, msg_prefix=term)
        nothing = self.client.get(self.url, {'q': 'no-such-thing'})
        self.assertContains(nothing, 'Nothing matches these filters.')
        # Period: age two events, then ask for the last hour.
        AuditEvent.objects.filter(action__in=['mailbox_created', 'login_failed']).update(
            time=timezone.now() - timedelta(days=3)
        )
        recent = self.client.get(self.url, {'period': 'day'})
        self.assertNotContains(recent, 'mailbox_created')
        self.assertContains(recent, 'plugin_failed')
        self.assertContains(self.client.get(self.url, {'period': 'week'}), 'mailbox_created')

    def test_unknown_filter_values_mean_no_filter(self) -> None:
        self.seed()
        page = self.client.get(
            self.url, {'level': 'nonsense', 'period': 'forever', 'tab': 'x', 'page': 'abc'}
        )
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Showing 1–4 of 4')

    def test_pagination(self) -> None:
        for i in range(60):
            record('bulk_event', f'n={i}')
        first = self.client.get(self.url)
        self.assertContains(first, 'Showing 1–25 of 60')
        self.assertContains(first, 'rel="next"')
        self.assertNotContains(first, 'rel="prev"')
        last = self.client.get(self.url, {'page': 3})
        self.assertContains(last, 'Showing 51–60 of 60')
        self.assertContains(last, 'rel="prev"')
        self.assertNotContains(last, 'rel="next"')
        # Out-of-range pages land on the last page; the filters travel with the links.
        self.assertContains(self.client.get(self.url, {'page': 99}), 'Showing 51–60 of 60')
        filtered = self.client.get(self.url, {'q': 'bulk', 'level': 'info'})
        self.assertContains(filtered, 'page=2&amp;level=info&amp;q=bulk')

    def test_messages_are_escaped(self) -> None:
        record('x', '<script>alert(1)</script> <img src=x onerror=alert(1)>')
        page = self.client.get(self.url).content.decode()
        self.assertNotIn('<script>alert(1)', page)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', page)

    def test_broken_chain_is_reported(self) -> None:
        self.seed()
        AuditEvent.objects.filter(seq=2).update(detail='tampered')
        cache.clear()
        page = self.client.get(self.url)
        self.assertContains(page, 'Broken')
        self.assertContains(page, 'Entry 2 was changed or removed')

    def test_errors_tab(self) -> None:
        from backend.apps.core.telemetry.services.telemetry_service import TelemetryService

        TelemetryService.capture_message('Something broke in the queue worker', severity='ERROR')
        page = self.client.get(self.url, {'tab': 'errors'})
        self.assertContains(page, 'Application errors')
        self.assertContains(page, 'Something broke in the queue worker')
        self.assertContains(
            self.client.get(self.url, {'tab': 'errors', 'q': 'zzz'}), 'Nothing matches'
        )

    def test_live_endpoint_returns_only_newer_events_oldest_first(self) -> None:
        self.seed()
        live = reverse('accounts:logs_live')
        everything = self.client.get(live).json()
        self.assertEqual([r['action'] for r in everything['rows']][-1], 'domain_verified')
        newest = everything['latest']
        self.assertEqual(self.client.get(live, {'after': newest}).json()['rows'], [])
        record('late_event', 'after the page loaded')
        record('later_event', 'and another')
        fresh = self.client.get(live, {'after': newest}).json()
        self.assertEqual([r['action'] for r in fresh['rows']], ['late_event', 'later_event'])
        self.assertEqual(
            set(fresh['rows'][0]),
            {
                'id',
                'time',
                'time_iso',
                'level',
                'level_word',
                'action',
                'user',
                'detail',
            },
        )
        only_errors = self.client.get(live, {'level': 'error'}).json()
        self.assertEqual([r['action'] for r in only_errors['rows']], ['plugin_failed'])

    def test_export_follows_the_filters(self) -> None:
        self.seed()
        response = self.client.get(reverse('accounts:logs_export'), {'level': 'error'})
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual([r[2] for r in rows[1:]], ['plugin_failed'])
        response = self.client.get(
            reverse('accounts:logs_export'), {'q': 'alex', 'format': 'jsonl'}
        )
        lines = [json.loads(x) for x in b''.join(response.streaming_content).splitlines()]
        self.assertEqual([x['action'] for x in lines], ['mailbox_created'])

    def test_the_page_offers_live_view_only_where_it_makes_sense(self) -> None:
        self.seed()
        self.assertContains(self.client.get(self.url), 'id="live-toggle"')
        self.assertNotContains(self.client.get(self.url, {'tab': 'errors'}), 'id="live-toggle"')
        for i in range(30):
            record('bulk', str(i))
        self.assertNotContains(self.client.get(self.url, {'page': 2}), 'id="live-toggle"')

    def test_permissions(self) -> None:
        self.client.logout()
        for name in ('accounts:logs', 'accounts:logs_live', 'accounts:logs_export'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302, name)
