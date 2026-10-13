"""The adaptive service: location data, learned places, traffic baselines, campaigns."""

from __future__ import annotations

import io
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse

from backend.apps.accounts.tests import test_assistant_views as base
from backend.apps.core.platform.models import AuditEvent
from backend.apps.core.platform.services.entrypoints import EntryPointService
from backend.apps.core.telemetry.models import KnownPlace, ThreatDigest, ThreatFinding
from backend.apps.core.telemetry.threats import adaptive, digest, geo
from backend.apps.core.telemetry.threats.types import Finding, MailEvent, Severity, WindowSummary

NOW = datetime(2026, 10, 13, 12, 30, tzinfo=UTC)

COUNTRY = (
    '203.0.113.0,203.0.113.255,DE\n'
    '198.51.100.0,198.51.100.255,US\n'
    '192.0.2.0,192.0.2.255,FR\n'
    '45.148.10.0,45.148.10.255,AD\n'
    '45.148.11.0,45.148.11.255,AD\n'
    '45.148.12.0,45.148.12.255,AD\n'
    '2001:db8::,2001:db8:ffff:ffff:ffff:ffff:ffff:ffff,NL\n'
    '240.0.0.0,240.0.0.255,ZZ\n'
)
ASN = (
    '203.0.113.0,203.0.113.255,64500,"Example Hosting, Inc."\n'
    '198.51.100.0,198.51.100.127,64501,Example Carrier\n'
    '198.51.100.128,198.51.100.255,64502,Other Carrier\n'
    '45.148.10.0,45.148.12.255,48090,TECHOFF SRV LIMITED\n'
    '2001:db8::,2001:db8:ffff:ffff:ffff:ffff:ffff:ffff,64503,Example IPv6\n'
)


def filler(n: int = 120) -> str:
    return ''.join(
        f'100.{i // 250}.{i % 250}.0,100.{i // 250}.{i % 250}.255,CH\n' for i in range(n)
    )


def install_geo(case: object) -> Path:
    target = Path(tempfile.mkdtemp(prefix='ifm-geo-')) / 'geo.sqlite'
    patcher = patch.dict(os.environ, {'IFINMAIL_GEO_DB': str(target)})
    patcher.start()
    case.addCleanup(patcher.stop)  # type: ignore[attr-defined]
    geo.build(io.StringIO(COUNTRY + filler()), io.StringIO(ASN), target, '2026-10')
    return target


class GeoTests(SimpleTestCase):
    def setUp(self) -> None:
        self.target = install_geo(self)

    def test_country_operator_and_organisation(self) -> None:
        with geo.reader() as reader:
            assert reader is not None
            place = reader.lookup('203.0.113.9')
            self.assertEqual(
                (place.country, place.asn, place.org), ('DE', 64500, 'Example Hosting, Inc.')
            )
            self.assertEqual(place.key, 'DE/AS64500')
            self.assertEqual(
                reader.lookup('198.51.100.200').asn, 64502
            )  # ranges split inside a /24
            self.assertEqual(reader.lookup('2001:db8:1::5').country, 'NL')
            self.assertEqual(reader.lookup('::ffff:203.0.113.9').country, 'DE')  # v4-mapped

    def test_unknown_reserved_and_garbage_are_unknown_not_errors(self) -> None:
        with geo.reader() as reader:
            assert reader is not None
            self.assertFalse(reader.lookup('8.8.8.8').known)
            self.assertEqual(reader.lookup('240.0.0.5').country, '')  # "ZZ" means no country
            self.assertFalse(reader.lookup('not an address').known)
            self.assertEqual(reader.lookup_net('203.0.113.0/24').country, 'DE')
            self.assertFalse(reader.lookup_net('nonsense').known)

    def test_without_the_file_there_is_no_reader(self) -> None:
        self.target.unlink()
        self.assertIsNone(geo.reader())
        self.assertIsNone(geo.info())

    def test_a_broken_download_keeps_the_old_file(self) -> None:
        before = self.target.read_bytes()
        with self.assertRaises(ValueError):
            geo.build(io.StringIO('1.0.0.0,1.0.0.255,AU\n'), io.StringIO(''), self.target, 'bad')
        self.assertEqual(self.target.read_bytes(), before)

    def test_refresh_downloads_builds_and_falls_back_to_last_month(self) -> None:
        import gzip

        def fake(url: str) -> bytes:
            if '2026-10' in url:
                raise OSError('not published yet')
            text = COUNTRY + filler() if 'country' in url else ASN
            return gzip.compress(text.encode())

        with patch.object(geo, '_download', side_effect=fake):
            result = geo.refresh(NOW)
        self.assertTrue(result['ok'])
        self.assertEqual(result['version'], '2026-09')
        self.assertEqual((geo.info() or {}).get('version'), '2026-09')

    def test_due_when_missing_old_or_failing_recently(self) -> None:
        self.assertFalse(geo.due())  # just built
        later = datetime.now(UTC) + timedelta(days=40)
        self.assertTrue(geo.due(later))
        self.target.unlink()
        self.assertTrue(geo.due())
        geo._note_attempt(datetime.now(UTC), 'offline')  # noqa: SLF001
        self.assertFalse(geo.due())  # tried a moment ago: do not hammer the mirror
        self.assertFalse(geo.refresh_if_due().get('ok') is False)


def mail_ok(net: str, who: str, minutes: int = 1) -> MailEvent:
    return MailEvent(NOW - timedelta(minutes=minutes), net, 'dovecot', 'login_success', who, 1)


class PlaceTests(base.AssistantBase):
    def setUp(self) -> None:
        super().setUp()
        install_geo(self)

    def known(self, who: str, place: str, country: str, asn: int, *, count: int = 10) -> None:
        KnownPlace.objects.create(
            actor=who,
            channel='mail',
            place=place,
            country=country,
            asn=asn,
            first_seen=NOW - timedelta(days=9),
            last_seen=NOW - timedelta(days=1),
            count=count,
            days=5,
        )

    def learn(self, events: list[MailEvent]) -> list[Finding]:
        with geo.reader() as reader:
            assert reader is not None
            return adaptive.learn_places(adaptive.sign_ins([], events), NOW, reader)

    def test_a_new_country_for_an_established_account_is_a_finding_once(self) -> None:
        self.known('bob@ifinmail.test', 'DE/AS64500', 'DE', 64500)
        found = self.learn([mail_ok('198.51.100.0/24', 'bob@ifinmail.test')])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].kind, 'new_place')
        self.assertEqual(found[0].severity, Severity.MEDIUM)
        self.assertIn('US', found[0].summary)
        self.assertIn('DE AS64500', found[0].summary)  # what is usual is named
        self.assertEqual(self.learn([mail_ok('198.51.100.0/24', 'bob@ifinmail.test')]), [])

    def test_a_new_operator_in_a_known_country_is_only_low(self) -> None:
        self.known('bob@ifinmail.test', 'DE/AS64999', 'DE', 64999)
        found = self.learn([mail_ok('203.0.113.0/24', 'bob@ifinmail.test')])
        self.assertEqual(found[0].severity, Severity.LOW)

    def test_an_account_still_being_learned_is_never_flagged(self) -> None:
        self.assertEqual(self.learn([mail_ok('198.51.100.0/24', 'new@ifinmail.test')]), [])
        self.known('young@ifinmail.test', 'DE/AS64500', 'DE', 64500, count=2)
        self.assertEqual(self.learn([mail_ok('198.51.100.0/24', 'young@ifinmail.test')]), [])

    def test_a_place_used_on_another_channel_is_not_new(self) -> None:
        self.known('bob@ifinmail.test', 'DE/AS64500', 'DE', 64500)
        from backend.apps.core.telemetry.threats.types import AuthEvent

        console = AuthEvent(NOW, 'login_success', 'bob@ifinmail.test', '203.0.113.0/24', '')
        with geo.reader() as reader:
            assert reader is not None
            found = adaptive.learn_places(adaptive.sign_ins([console], []), NOW, reader)
        self.assertEqual(found, [])
        self.assertTrue(KnownPlace.objects.filter(channel='console').exists())

    def test_repeats_inside_one_window_count_once(self) -> None:
        self.known('bob@ifinmail.test', 'DE/AS64500', 'DE', 64500)
        events = [mail_ok('203.0.113.0/24', 'bob@ifinmail.test', minutes=m) for m in (5, 4, 3)]
        self.learn(events)
        self.learn(events)  # the next pass sees the same lines again
        row = KnownPlace.objects.get(actor='bob@ifinmail.test', place='DE/AS64500')
        self.assertEqual(row.count, 13)

    def test_no_location_data_means_nothing_is_learned(self) -> None:
        geo.db_path().unlink()
        self.assertIsNone(geo.reader())
        result = adaptive.run(
            [],
            [],
            [mail_ok('198.51.100.0/24', 'bob@ifinmail.test')],
            [],
            WindowSummary(NOW - timedelta(hours=1), NOW),
            NOW,
        )
        self.assertEqual(result, [])
        self.assertFalse(KnownPlace.objects.exists())

    def test_it_can_be_turned_off(self) -> None:
        self.known('bob@ifinmail.test', 'DE/AS64500', 'DE', 64500)
        with patch.dict(os.environ, {'THREAT_ADAPTIVE': '0'}):
            self.assertEqual(
                adaptive.run(
                    [],
                    [],
                    [mail_ok('198.51.100.0/24', 'bob@ifinmail.test')],
                    [],
                    WindowSummary(NOW - timedelta(hours=1), NOW),
                    NOW,
                ),
                [],
            )

    def test_retention_forgets_old_places_and_deleted_accounts(self) -> None:
        self.known('gone@ifinmail.test', 'DE/AS64500', 'DE', 64500)
        old = KnownPlace.objects.create(
            actor=self.admin.email.lower(),
            channel='console',
            place='FR/AS1',
            country='FR',
            asn=1,
            first_seen=NOW - timedelta(days=400),
            last_seen=NOW - timedelta(days=300),
        )
        KnownPlace.objects.create(
            actor=self.admin.email.lower(),
            channel='console',
            place='DE/AS64500',
            country='DE',
            asn=64500,
            first_seen=NOW - timedelta(days=3),
            last_seen=NOW,
        )
        self.assertEqual(adaptive.forget(NOW), 2)
        self.assertFalse(KnownPlace.objects.filter(pk=old.pk).exists())
        self.assertFalse(KnownPlace.objects.filter(actor='gone@ifinmail.test').exists())
        self.assertEqual(KnownPlace.objects.count(), 1)


class SurgeTests(base.AssistantBase):
    def history(self, value: int, days: int = 8, metric: str = 'requests') -> None:
        for d in range(1, days + 1):
            row, _ = ThreatDigest.objects.get_or_create(
                hour=NOW.replace(minute=0, second=0, microsecond=0) - timedelta(days=d)
            )
            row.summary = {**row.summary, metric: value}
            row.save()

    def summary(self, **kw: int) -> WindowSummary:
        s = WindowSummary(NOW - timedelta(hours=1), NOW)
        for k, v in kw.items():
            setattr(s, k, v)
        return s

    def test_far_above_this_hours_normal_is_a_finding(self) -> None:
        self.history(120)
        found = adaptive.surges(self.summary(requests=2500), NOW)
        self.assertEqual([f.kind for f in found], ['traffic_surge'])
        self.assertIn('usually sees about 120', found[0].summary)
        self.assertEqual(found[0].severity, Severity.HIGH)  # >3x the limit

    def test_ordinary_variation_and_small_numbers_are_not(self) -> None:
        self.history(120)
        self.assertEqual(adaptive.surges(self.summary(requests=200), NOW), [])
        self.history(1, metric='mail_failures')
        self.assertEqual(adaptive.surges(self.summary(mail_failures=9), NOW), [])  # under the floor

    def test_too_little_history_means_no_opinion(self) -> None:
        self.history(120, days=3)
        self.assertEqual(adaptive.surges(self.summary(requests=9000), NOW), [])

    def test_other_hours_do_not_count(self) -> None:
        for d in range(1, 9):
            ThreatDigest.objects.create(
                hour=NOW.replace(hour=3, minute=0, second=0, microsecond=0) - timedelta(days=d),
                summary={'requests': 5000},
            )
        self.history(100)
        self.assertEqual(adaptive.surges(self.summary(requests=2000), NOW)[0].count, 2000)


def net_finding(net: str, kind: str = 'probe_sweep', severity: Severity = Severity.HIGH) -> Finding:
    return Finding(
        key=f'{kind}:{net}',
        kind=kind,
        severity=severity,
        subject=net,
        title='Scanner',
        summary='x',
        count=10,
        first_seen=NOW - timedelta(minutes=9),
        last_seen=NOW,
    )


class CampaignTests(base.AssistantBase):
    def setUp(self) -> None:
        super().setUp()
        install_geo(self)

    def test_networks_of_one_operator_become_one_finding(self) -> None:
        findings = [net_finding(f'45.148.{i}.0/24') for i in (10, 11, 12)]
        findings.append(net_finding('203.0.113.0/24'))
        with geo.reader() as reader:
            assert reader is not None
            found = adaptive.campaigns(findings, reader)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].key, 'campaign:AS48090')
        self.assertEqual(found[0].samples, ['45.148.10.0/24', '45.148.11.0/24', '45.148.12.0/24'])
        self.assertEqual(found[0].severity, Severity.HIGH)

    def test_two_networks_are_not_a_campaign_and_internal_ones_never_count(self) -> None:
        with geo.reader() as reader:
            assert reader is not None
            self.assertEqual(
                adaptive.campaigns(
                    [net_finding('45.148.10.0/24'), net_finding('45.148.11.0/24')], reader
                ),
                [],
            )

    def test_where_from_counts_events_by_country_and_operator(self) -> None:
        from backend.apps.core.telemetry.threats.types import Access

        def req(net_ip: str) -> Access:
            net = net_ip.rsplit('.', 1)[0] + '.0/24'
            return Access(NOW, net_ip, net, 'GET', '/', '', 200, 'h', 'ua', '', 0.0)

        requests = [req('203.0.113.5')] * 3 + [req('45.148.10.9')] * 5 + [req('45.148.11.9')]
        with geo.reader() as reader:
            assert reader is not None
            countries, operators = adaptive.where_from(requests, [], reader)
        self.assertEqual(countries, {'AD': 6, 'DE': 3})
        self.assertEqual(operators[0]['asn'], 48090)
        self.assertEqual((operators[0]['events'], operators[0]['networks']), (6, 2))


class AdaptivePageTests(base.AssistantBase):
    def setUp(self) -> None:
        super().setUp()
        install_geo(self)
        server = patch(
            'backend.apps.dns.services.server.DNSServerConfig.server_ipv4',
            return_value='192.0.2.10',
        )
        server.start()
        self.addCleanup(server.stop)
        for i in (10, 11, 12):
            ThreatFinding.objects.create(
                key=f'probe_sweep:45.148.{i}.0/24',
                kind='probe_sweep',
                severity=int(Severity.HIGH),
                subject=f'45.148.{i}.0/24',
                title='Scanner probing',
                summary='x',
                count=9,
                first_seen=NOW,
                last_seen=NOW,
            )
        ThreatFinding.objects.create(
            key='campaign:AS48090',
            kind='campaign',
            severity=int(Severity.HIGH),
            subject='AS48090 TECHOFF SRV LIMITED',
            title='Several networks of one operator',
            summary='three networks',
            count=27,
            first_seen=NOW,
            last_seen=NOW,
            samples=['45.148.10.0/24', '45.148.11.0/24', '45.148.12.0/24'],
        )
        ThreatDigest.objects.create(
            hour=timezone_now_hour(),
            summary={
                'requests': 40,
                'countries': {'AD': 30, 'DE': 10},
                'providers': [
                    {
                        'asn': 48090,
                        'org': 'TECHOFF SRV LIMITED',
                        'country': 'AD',
                        'events': 30,
                        'networks': 3,
                    }
                ],
            },
        )

    def test_the_page_names_where_traffic_comes_from(self) -> None:
        page = self.client.get(reverse('accounts:threats'))
        self.assertContains(page, 'Where it comes from')
        self.assertContains(page, 'TECHOFF SRV LIMITED')
        self.assertContains(page, 'AD · AS48090')  # beside each network finding
        self.assertContains(page, 'Block these 3 networks')
        self.assertContains(page, 'IP location data by DB-IP.com')

    def test_one_click_blocks_every_network_of_a_campaign(self) -> None:
        campaign = ThreatFinding.objects.get(kind='campaign')
        response = self.client.post(
            reverse('accounts:threats_block'),
            {'finding': str(campaign.pk), 'duration': '24h', 'confirm_password': base.GOOD},
            follow=True,
        )
        self.assertContains(response, 'blocked until')
        self.assertEqual(
            sorted(r['cidr'] for r in EntryPointService.blocklist()),
            ['45.148.10.0/24', '45.148.11.0/24', '45.148.12.0/24'],
        )
        self.assertEqual(AuditEvent.objects.filter(action='network_block').count(), 3)

    def test_a_campaign_never_blocks_the_network_you_are_on(self) -> None:
        campaign = ThreatFinding.objects.get(kind='campaign')
        self.client.post(
            reverse('accounts:threats_block'),
            {'finding': str(campaign.pk), 'duration': '1h', 'confirm_password': base.GOOD},
            HTTP_X_FORWARDED_FOR='45.148.11.77',
        )
        self.assertEqual(
            sorted(r['cidr'] for r in EntryPointService.blocklist()),
            ['45.148.10.0/24', '45.148.12.0/24'],
        )

    def test_the_digest_run_fills_places_and_findings_end_to_end(self) -> None:
        # a mailbox with history signs in from a new country in the mail log
        KnownPlace.objects.create(
            actor='bob@ifinmail.test',
            channel='mail',
            place='DE/AS64500',
            country='DE',
            asn=64500,
            first_seen=NOW - timedelta(days=9),
            last_seen=NOW - timedelta(days=1),
            count=12,
            days=6,
        )
        d = Path(tempfile.mkdtemp(prefix='ifm-mail-'))
        stamp = (NOW - timedelta(minutes=2)).strftime('%b %d %H:%M:%S').replace(' 0', '  ', 1)
        (d / 'dovecot.log').write_text(
            f'{stamp} imap-login: Info: Login: user=<bob@ifinmail.test>, method=PLAIN, '
            'rip=198.51.100.9, lip=192.0.2.10, TLS, session=<x>\n'
            f'{stamp} mail postfix/smtpd[9]: NOQUEUE: reject: RCPT from unknown[198.51.100.9]: '
            '554 5.7.1 <v@example.net>: Relay access denied; from=<a@b.test>\n'
        )
        with patch.dict(os.environ, {'IFINMAIL_MAIL_LOG_DIR': str(d), 'ADMIN_EMAIL': ''}):
            result = digest.run(NOW, summarise=False)
        self.assertTrue(any(f.kind == 'new_place' for f in result.findings))
        self.assertIn('US', result.summary.countries)
        page = self.client.get(reverse('accounts:threats'))
        self.assertContains(page, 'Sign-in from a country this account has not used before')


def timezone_now_hour() -> datetime:
    return datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
