"""Spam Filtering: the page, its forms, the values that reach Rspamd and the figures it shows."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.core.services import SystemSettings
from backend.apps.core.telemetry import report
from backend.apps.core.telemetry.models import ThreatDigest
from backend.apps.core.telemetry.threats import spam as spam_stats
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.mail.services import spam_policy
from backend.apps.mail.services.spam_policy import SpamSettingError
from backend.apps.core.types import SettingKey

MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'


class ThresholdTests(SimpleTestCase):
    def test_the_standard_level_is_the_shipped_configuration(self) -> None:
        self.assertEqual(
            spam_policy.thresholds(5),
            {'greylist': 4.0, 'junk': 6.0, 'rewrite': 8.0, 'reject': 15.0},
        )

    def test_every_level_keeps_the_actions_in_order_and_stricter_is_lower(self) -> None:
        previous = None
        for level in range(spam_policy.MIN_LEVEL, spam_policy.MAX_LEVEL + 1):
            t = spam_policy.thresholds(level)
            self.assertLessEqual(t['greylist'], t['junk'], level)
            self.assertLessEqual(t['junk'], t['rewrite'], level)
            self.assertLessEqual(t['rewrite'], t['reject'], level)
            if previous:
                self.assertTrue(all(t[k] <= previous[k] for k in t), level)
            previous = t

    def test_every_level_is_a_value_the_engine_accepts(self) -> None:
        from backend.apps.core.plugins.services import registry

        target = registry.get_target('rspamd.policy')
        for level in range(spam_policy.MIN_LEVEL, spam_policy.MAX_LEVEL + 1):
            for name, score in spam_policy.thresholds(level).items():
                key = {
                    'greylist': 'spam_greylist_score',
                    'junk': 'spam_junk_score',
                    'rewrite': 'spam_rewrite_score',
                    'reject': 'spam_reject_score',
                }[name]
                self.assertIsNone(target.validate(key, f'{score:.1f}'), (level, name, score))

    def test_levels_outside_one_to_ten_are_refused(self) -> None:
        for bad in ('0', '11', 'x', '', None):
            with self.subTest(bad=bad), self.assertRaises(SpamSettingError):
                spam_policy.clamp_level(bad)
        self.assertEqual(spam_policy.clamp_level('4.0'), 4)  # an older page sent 4.0


class HostTests(SimpleTestCase):
    def test_good_names(self) -> None:
        self.assertEqual(spam_policy.normalize_host(' DNSBL.Example.org. '), 'dnsbl.example.org')

    def test_bad_names_say_what_is_wrong(self) -> None:
        for bad in (
            'localhost',
            'http://dnsbl.example.org',
            'dnsbl.example.org/x',
            'a b.example.org',
            '1.2.3.4',
            'bad_name.example.org',
            '-x.example.org',
            'x@example.org',
            'a' * 64 + '.example.org',
            '',
        ):
            with self.subTest(bad=bad), self.assertRaises(SpamSettingError):
                spam_policy.normalize_host(bad)


class ProbeTests(SimpleTestCase):
    class Answer(list):
        pass

    def resolver(self, behaviour):
        outer = self

        class R:
            def resolve(self, name, rtype):
                return behaviour(name, rtype, outer)

        return R()

    def test_a_list_that_answers_its_test_entry_works(self) -> None:
        import dns.rdtypes.IN.A  # noqa: F401

        class Rdata:
            def to_text(self) -> str:
                return '127.0.0.2'

        seen = []

        def behaviour(name, rtype, outer):
            seen.append(name)
            return [Rdata()]

        result = spam_policy.probe('bl.example.org', 'dnsbl', self.resolver(behaviour))
        self.assertEqual(result['state'], 'works')
        self.assertEqual(seen, ['2.0.0.127.bl.example.org'])

    def test_a_link_list_is_asked_about_its_test_name(self) -> None:
        import dns.resolver

        seen = []

        def behaviour(name, rtype, outer):
            seen.append((name, rtype))
            if rtype == 'SOA':
                raise dns.resolver.NoAnswer()
            raise dns.resolver.NXDOMAIN()

        result = spam_policy.probe('uri.example.org', 'uribl', self.resolver(behaviour))
        self.assertEqual(seen[0], ('test.uri.example.org', 'A'))
        self.assertEqual(result['state'], 'quiet')

    def test_refused_missing_and_down_are_told_apart(self) -> None:
        import dns.exception
        import dns.resolver

        class Rdata:
            def to_text(self) -> str:
                return '127.255.255.254'

        refused = spam_policy.probe(
            'bl.example.org', 'dnsbl', self.resolver(lambda n, t, o: [Rdata()])
        )
        self.assertEqual(refused['state'], 'refused')

        def nowhere(name, rtype, outer):
            raise dns.resolver.NXDOMAIN()

        self.assertEqual(
            spam_policy.probe('nope.example.org', 'dnsbl', self.resolver(nowhere))['state'],
            'missing',
        )

        def slow(name, rtype, outer):
            raise dns.exception.Timeout()

        self.assertEqual(
            spam_policy.probe('slow.example.org', 'dnsbl', self.resolver(slow))['state'], 'down'
        )


class FigureTests(SimpleTestCase):
    def row(self, **actions: int) -> dict:
        return {'sources': {'rspamd': {'actions': actions}}}

    def test_totals_group_the_actions_by_what_happened_to_the_message(self) -> None:
        t = spam_stats.totals(
            [
                self.row(no_action=90, add_header=4, rewrite_subject=1, greylist=3, reject=2),
                self.row(no_action=10, soft_reject=1, something_new=2),
            ]
        )
        self.assertEqual(
            t,
            {
                'scanned': 113,
                'delivered': 100,
                'junked': 5,
                'delayed': 4,
                'refused': 2,
                'other': 2,
            },
        )

    def test_no_data_is_zeros_not_an_error(self) -> None:
        self.assertEqual(spam_stats.totals([{}, {'sources': {}}])['scanned'], 0)

    def test_the_chart_always_has_one_bar_per_hour(self) -> None:
        now = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)
        buckets = spam_stats.hourly(
            [(datetime(2026, 10, 14, 11, 0, tzinfo=UTC), self.row(no_action=8, reject=2))], now
        )
        self.assertEqual(len(buckets), 24)
        self.assertEqual(buckets[-1]['hour'].hour, 12)
        self.assertEqual(buckets[-2]['scanned'], 10)
        bars = spam_stats.bars(buckets)
        self.assertEqual(bars[-2]['height'], 100)
        self.assertEqual(bars[0]['height'], 0)
        self.assertEqual((bars[-2]['caught'], bars[-2]['share']), (2, 20))


class _PageCase(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        admin = MailUser.objects.create_user('root@ifinmail.test', 'Correct-Horse-9', is_staff=True)
        self.client.force_login(admin, backend=MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()
        patcher = patch('backend.apps.mail.services.spam_policy._publish')
        self.publish = patcher.start()
        self.addCleanup(patcher.stop)

    def page(self, **params: str):
        return self.client.get(reverse('accounts:spam_filtering'), params)


class PageTests(_PageCase):
    def test_the_page_renders_with_nothing_configured_and_nothing_scanned(self) -> None:
        response = self.page()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Nothing has been scanned')
        self.assertContains(response, 'No lists added')
        self.assertNotContains(response, 'False Positives')

    def test_the_forms_post_the_field_names_the_views_read(self) -> None:
        """The failure this page once had: the script posted ``level`` and the view read
        ``value``, so the slider never saved. Each form's fields are posted back as rendered."""
        html = self.page().content.decode()
        forms = re.findall(r'<form[^>]*action="([^"]+)"[^>]*>(.*?)</form>', html, flags=re.S)
        fields = {
            action: set(re.findall(r'name="([a-z_]+)"', body))
            for action, body in forms
            if 'spam-filtering' in action
        }
        self.assertEqual(
            fields[reverse('accounts:spam_sensitivity')], {'csrfmiddlewaretoken', 'level'}
        )
        self.assertEqual(
            fields[reverse('accounts:spam_add_provider')], {'csrfmiddlewaretoken', 'host', 'kind'}
        )

    def test_saving_a_level_stores_it_and_publishes_to_the_engine(self) -> None:
        response = self.client.post(reverse('accounts:spam_sensitivity'), {'level': '8'})
        self.assertRedirects(response, reverse('accounts:spam_filtering'))
        self.assertEqual(SystemSettings.get(SettingKey.SPAM_SENSITIVITY), 8)
        self.publish.assert_called()
        self.assertContains(self.page(), 'value="8"')

    def test_a_bad_level_is_a_message_not_an_error(self) -> None:
        response = self.client.post(
            reverse('accounts:spam_sensitivity'), {'level': '42'}, follow=True
        )
        self.assertContains(response, 'from 1 to 10')
        self.assertIsNone(SystemSettings.get(SettingKey.SPAM_SENSITIVITY))

    def test_a_list_can_be_added_tested_turned_off_and_removed(self) -> None:
        add = reverse('accounts:spam_add_provider')
        self.client.post(add, {'host': 'BL.Example.org', 'kind': 'dnsbl'})
        self.assertContains(self.page(), 'bl.example.org')
        self.assertEqual(
            spam_policy.rspamd_values()['rspamd.policy']['dnsbl_providers'],
            'bl.example.org/dnsbl',
        )

        verdict = {'state': 'works', 'ms': 42, 'detail': 'It answered for its test entry.', 'at': ''}
        with patch.object(spam_policy, 'probe', return_value=verdict):
            response = self.client.post(
                reverse('accounts:spam_test_provider'), {'host': 'bl.example.org'}, follow=True
            )
        self.assertContains(response, '42')
        self.assertContains(response, 'Answers')

        self.client.post(reverse('accounts:spam_toggle_provider'), {'host': 'bl.example.org'})
        self.assertEqual(spam_policy.rspamd_values()['rspamd.policy']['dnsbl_providers'], '')
        self.assertContains(self.page(), 'Turn on')

        self.client.post(reverse('accounts:spam_remove_provider'), {'host': 'bl.example.org'})
        self.assertContains(self.page(), 'No lists added')

    def test_duplicates_bad_names_and_the_cap_are_refused_with_a_reason(self) -> None:
        add = reverse('accounts:spam_add_provider')
        self.client.post(add, {'host': 'bl.example.org', 'kind': 'dnsbl'})
        again = self.client.post(add, {'host': 'BL.example.org', 'kind': 'uribl'}, follow=True)
        self.assertContains(again, 'already in the list')
        bad = self.client.post(add, {'host': 'http://x.example.org', 'kind': 'dnsbl'}, follow=True)
        self.assertContains(bad, 'only the DNS name')
        kind = self.client.post(add, {'host': 'ok.example.org', 'kind': 'nonsense'}, follow=True)
        self.assertContains(kind, 'what kind of list')
        for n in range(spam_policy.MAX_PROVIDERS):
            self.client.post(add, {'host': f'l{n}.example.org', 'kind': 'dnsbl'})
        full = self.client.post(add, {'host': 'one-more.example.org', 'kind': 'dnsbl'}, follow=True)
        self.assertContains(full, 'At most')
        self.assertEqual(len(spam_policy.providers()), spam_policy.MAX_PROVIDERS)

    def test_the_old_overrides_file_is_read_until_something_is_saved(self) -> None:
        legacy = {
            'sensitivity': '7.0',
            'providers': [
                {'host': 'rbl.example.net', 'type': 'CUSTOM'},
                {'host': 'not a host', 'type': 'CUSTOM'},
            ],
        }
        with patch.object(spam_policy, '_legacy', return_value=legacy):
            self.assertEqual(spam_policy.level(), 7)
            self.assertEqual([p.host for p in spam_policy.providers()], ['rbl.example.net'])
            self.assertEqual(spam_policy.providers()[0].kind, 'dnsbl')

    def test_only_those_who_manage_security_can_change_it(self) -> None:
        plain = MailUser.objects.create_user('plain@ifinmail.test', 'Correct-Horse-9')
        self.client.logout()
        self.client.force_login(plain, backend=MODEL_BACKEND)
        for name in ('spam_sensitivity', 'spam_add_provider'):
            response = self.client.post(reverse(f'accounts:{name}'), {'level': '9', 'host': 'x.example.org'})
            self.assertIn(response.status_code, (302, 403), name)
        self.assertIsNone(SystemSettings.get(SettingKey.SPAM_SENSITIVITY))
        self.assertEqual(spam_policy.providers(), [])

    def test_the_figures_come_from_the_digest(self) -> None:
        now = timezone.now().replace(minute=5, second=0, microsecond=0)
        ThreatDigest.objects.create(
            hour=now.replace(minute=0),
            summary={
                'sources': {
                    'rspamd': {'actions': {'no_action': 40, 'add_header': 6, 'reject': 3}}
                }
            },
        )
        ThreatDigest.objects.create(
            hour=now.replace(minute=0) - timedelta(days=3),
            summary={'sources': {'rspamd': {'actions': {'no_action': 100}}}},
        )
        day = report.spam_section('day', now)
        self.assertEqual((day['scanned'], day['junked'], day['refused']), (49, 6, 3))
        week = report.spam_section('week', now)
        self.assertEqual(week['scanned'], 149)
        html = self.page().content.decode()
        self.assertIn('ifinmail-chart-bars', html)
        self.assertIn('>49<', html)


class EngineValuesTests(_PageCase):
    def test_the_values_reach_the_runtime_file_the_filter_reads(self) -> None:
        from backend.apps.core.plugins.services import InstallationService

        SystemSettings.set(SettingKey.SPAM_SENSITIVITY, 8)
        SystemSettings.set(
            SettingKey.SPAM_PROVIDERS,
            [
                {'host': 'bl.example.org', 'type': 'dnsbl', 'enabled': True},
                {'host': 'off.example.org', 'type': 'dnsbl', 'enabled': False},
                {'host': 'wl.example.org', 'type': 'dnswl', 'enabled': True},
            ],
        )
        InstallationService.publish_all()
        text = (Path(self.runtime_dir) / 'rspamd-plugins.conf').read_text()
        values = dict(
            line.split(' = ', 1) for line in text.splitlines() if ' = ' in line
        )
        t = spam_policy.thresholds(8)
        self.assertEqual(values['spam_reject_score'], f'{t["reject"]:.1f}')
        self.assertEqual(values['spam_greylist_score'], f'{t["greylist"]:.1f}')
        self.assertEqual(values['dnsbl_providers'], 'bl.example.org/dnsbl,wl.example.org/dnswl')
