"""Opt-in automatic blocking and flood mode: what it does, and the many ways it must not act."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.core import mail
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import APIToken, MailUser
from backend.apps.accounts.tests import test_assistant_views as base
from backend.apps.core.platform.models import AuditEvent
from backend.apps.core.platform.services.entrypoints import (
    FLOOD_MAIL_PER_MINUTE,
    FLOOD_WEB_PER_MINUTE,
    EntryPointService,
)
from backend.apps.core.services import SystemSettings
from backend.apps.core.tasks import reconcile_entrypoints
from backend.apps.core.telemetry.models import ThreatFinding
from backend.apps.core.telemetry.threats import autoblock
from backend.apps.core.telemetry.threats.types import Severity
from backend.apps.core.types import SettingKey

NOW = datetime(2026, 10, 13, 12, 30, tzinfo=UTC)


def finding(
    net: str = '203.0.113.0/24',
    *,
    kind: str = 'probe_sweep',
    severity: Severity = Severity.HIGH,
    minutes: int = 5,
    status: str = ThreatFinding.OPEN,
    key: str = '',
) -> ThreatFinding:
    return ThreatFinding.objects.create(
        key=key or f'{kind}:{net}',
        kind=kind,
        severity=int(severity),
        subject=net,
        title='Scanner probing for files and admin pages',
        summary='x',
        count=50,
        first_seen=NOW - timedelta(minutes=minutes + 5),
        last_seen=NOW - timedelta(minutes=minutes),
        status=status,
    )


class AutoBase(base.AssistantBase):
    def setUp(self) -> None:
        super().setUp()
        self.server_ip = patch(
            'backend.apps.dns.services.server.DNSServerConfig.server_ipv4',
            return_value='192.0.2.10',
        )
        self.server_ip.start()
        self.addCleanup(self.server_ip.stop)

    def turn_on(self, **kw: object) -> None:
        options: dict[str, object] = {'block': True, 'flood': False, 'hours': 24, 'allow_text': ''}
        options.update(kw)
        autoblock.save(**options)  # type: ignore[arg-type]


class AutoBlockTests(AutoBase):
    def test_it_is_on_by_default_and_stays_off_once_turned_off(self) -> None:
        self.assertTrue(autoblock.config().block)  # nothing was ever saved
        self.assertTrue(autoblock.config().flood)
        finding()
        self.assertEqual(autoblock.run(NOW).blocked, ['203.0.113.0/24'])
        EntryPointService.unblock('203.0.113.0/24')
        self.turn_on(block=False)
        self.assertEqual(autoblock.run(NOW).blocked, [])
        self.assertEqual(EntryPointService.blocklist(), [])

    def test_a_serious_finding_blocks_its_network_for_the_chosen_time(self) -> None:
        self.turn_on(hours=6)
        finding()
        result = autoblock.run(NOW)
        self.assertEqual(result.blocked, ['203.0.113.0/24'])
        row = EntryPointService.blocklist()[0]
        self.assertTrue(row['note'].startswith('Auto: '))
        self.assertEqual(datetime.fromisoformat(row['expires']) - NOW, timedelta(hours=6))
        self.assertIn('203.0.113.0/24', EntryPointService.render())
        event = AuditEvent.objects.get(action='network_auto_block')
        self.assertEqual(event.user, 'system')
        self.assertIn('probe_sweep', event.detail)

    def test_the_administrators_are_emailed(self) -> None:
        self.turn_on()
        finding()
        with patch.dict('os.environ', {'ADMIN_EMAIL': 'owner@ifinmail.test', 'THREAT_ALERTS': '1'}):
            autoblock.run(NOW)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('203.0.113.0/24', mail.outbox[0].body)
        self.assertIn('lifts', mail.outbox[0].body)

    def test_a_probe_that_made_the_server_raise_is_blocked_too(self) -> None:
        self.turn_on()
        finding('203.0.113.0/24', kind='probe_triggered_error')
        self.assertEqual(autoblock.run(NOW).blocked, ['203.0.113.0/24'])

    def test_and_a_second_pass_does_not_repeat_itself(self) -> None:
        self.turn_on()
        finding()
        autoblock.run(NOW)
        self.assertEqual(autoblock.run(NOW).blocked, [])
        self.assertEqual(len(EntryPointService.blocklist()), 1)

    def test_what_it_leaves_alone(self) -> None:
        self.turn_on(allow_text='198.51.100.0/24')
        finding('198.51.100.0/24', key='a')  # on the allow-list
        finding('10.0.0.0/24', key='b')  # this server's own side
        finding('192.0.2.0/24', key='c')  # the server's own address is inside it
        finding('203.0.113.0/24', severity=Severity.MEDIUM, key='d')  # not serious enough
        finding('203.0.114.0/24', status=ThreatFinding.ACKNOWLEDGED, key='e')  # someone looked
        finding('203.0.115.0/24', minutes=300, key='f')  # not seen lately
        finding('owner@ifinmail.test', kind='account_attack', key='g')  # not a network
        result = autoblock.run(NOW)
        self.assertEqual(result.blocked, [])
        self.assertEqual(EntryPointService.blocklist(), [])

    def test_a_network_people_signed_in_from_is_never_blocked(self) -> None:
        self.turn_on()
        finding('203.0.113.0/24')
        AuditEvent.objects.create(
            action='login_success',
            user='someone@ifinmail.test',
            detail='IP: 203.0.113.77',
            time=NOW - timedelta(days=2),
        )
        finding('198.51.100.0/24', key='k')
        user = MailUser.objects.create_user('svc@ifinmail.test', base.GOOD)
        APIToken.objects.create(
            user=user,
            name='k',
            prefix='ifm_abc',
            token_hash=hashlib.sha256(b'x').hexdigest(),
            last_used_at=NOW - timedelta(days=3),
            last_used_ip='198.51.100.9',
        )
        result = autoblock.run(NOW)
        self.assertEqual(result.blocked, [])
        self.assertEqual(result.skipped, 2)

    def test_mailbox_users_and_learned_places_are_protected_too(self) -> None:
        from backend.apps.core.telemetry.models import KnownPlace

        finding('203.0.113.0/24', key='a')
        finding('198.51.100.0/24', key='b')
        KnownPlace.objects.create(
            actor='bob@ifinmail.test',
            channel='mail',
            place='DE/AS1',
            country='DE',
            asn=1,
            net='198.51.100.0/24',
            first_seen=NOW - timedelta(days=9),
            last_seen=NOW - timedelta(days=3),
        )
        # a mailbox sign-in in the last hour, from the other network, read from the mail log
        import os
        import tempfile
        from pathlib import Path

        d = Path(tempfile.mkdtemp(prefix='ifm-mail-'))
        stamp = (NOW - timedelta(minutes=5)).strftime('%b %d %H:%M:%S').replace(' 0', '  ', 1)
        (d / 'dovecot.log').write_text(
            f'{stamp} imap-login: Info: Login: user=<amy@ifinmail.test>, method=PLAIN, '
            'rip=203.0.113.20, lip=192.0.2.10, TLS, session=<x>\n'
        )
        with patch.dict(os.environ, {'IFINMAIL_MAIL_LOG_DIR': str(d)}):
            result = autoblock.run(NOW)
        self.assertEqual(result.blocked, [])
        self.assertEqual(result.skipped, 2)

    def test_a_network_that_is_already_blocked_or_inside_a_block_is_skipped(self) -> None:
        self.turn_on()
        EntryPointService.block('203.0.0.0/16', 'manual')
        finding('203.0.113.0/24')
        self.assertEqual(autoblock.run(NOW).blocked, [])
        self.assertEqual(len(EntryPointService.blocklist()), 1)

    def test_at_most_a_few_per_pass_and_a_ceiling_in_force(self) -> None:
        self.turn_on()
        for i in range(autoblock.MAX_PER_PASS + 5):
            finding(f'203.0.{i + 1}.0/24', key=f'k{i}')
        first = autoblock.run(NOW)
        self.assertEqual(len(first.blocked), autoblock.MAX_PER_PASS)
        with patch.object(autoblock, 'MAX_AUTO', autoblock.MAX_PER_PASS + 2):
            second = autoblock.run(NOW)
            self.assertEqual(len(second.blocked), 2)
            self.assertTrue(second.full)
            self.assertTrue(AuditEvent.objects.filter(action='network_auto_block_full').exists())

    def test_the_block_lifts_itself_and_is_audited(self) -> None:
        self.turn_on(hours=1)
        finding()
        autoblock.run(NOW)
        later = NOW + timedelta(hours=1, minutes=1)
        self.assertEqual(EntryPointService.expire(later), ['203.0.113.0/24'])
        self.assertNotIn('203.0.113.0/24', EntryPointService.render())


class FloodModeTests(AutoBase):
    def flood(self) -> None:
        finding(
            'many networks',
            kind='distributed_flood',
            severity=Severity.CRITICAL,
            key='distributed_flood:all',
        )

    def test_the_default_rules_are_unchanged_while_there_is_no_flood(self) -> None:
        text = EntryPointService.render()
        self.assertNotIn('floodweb4', text)
        self.assertIn('limit rate over 120/minute', text)

    def test_on_by_default_and_off_when_turned_off(self) -> None:
        self.flood()
        self.turn_on(block=False, flood=False)
        self.assertFalse(autoblock.run(NOW).flood_started)
        self.assertNotIn('floodweb4', EntryPointService.render())
        self.turn_on(block=False, flood=True)
        self.assertTrue(autoblock.run(NOW).flood_started)

    def test_a_flood_tightens_mail_ports_and_caps_the_web_for_a_while(self) -> None:
        self.turn_on(block=False, flood=True)
        self.flood()
        result = autoblock.run(NOW)
        self.assertTrue(result.flood_started)
        text = EntryPointService.render()
        self.assertIn(f'limit rate over {FLOOD_MAIL_PER_MINUTE}/minute', text)
        self.assertNotIn('limit rate over 120/minute', text)
        self.assertIn(f'limit rate over {FLOOD_WEB_PER_MINUTE}/minute', text)
        self.assertRegex(text, r'th dport \{ 443, 80 \}|th dport \{ 80, 443 \}')
        self.assertTrue(AuditEvent.objects.filter(action='flood_mode_on').exists())
        self.assertEqual(EntryPointService.summary()['flood_mode'], 1)

    def test_it_tightens_only_never_loosens(self) -> None:
        EntryPointService.set_rate_per_minute(25)
        self.turn_on(block=False, flood=True)
        self.flood()
        autoblock.run(NOW)
        self.assertIn('limit rate over 25/minute', EntryPointService.render())

    def test_a_server_with_the_cap_off_still_gets_flood_protection(self) -> None:
        EntryPointService.set_rate_per_minute(0)
        self.assertNotIn('limit rate over', EntryPointService.render())
        self.turn_on(block=False, flood=True)
        self.flood()
        autoblock.run(NOW)
        self.assertIn(f'limit rate over {FLOOD_MAIL_PER_MINUTE}/minute', EntryPointService.render())

    def test_a_second_sighting_extends_without_republishing(self) -> None:
        self.turn_on(block=False, flood=True)
        self.flood()
        self.assertTrue(autoblock.run(NOW).flood_started)
        self.assertFalse(autoblock.run(NOW + timedelta(minutes=10)).flood_started)

    def test_it_ends_on_its_own_and_says_so(self) -> None:
        self.turn_on(block=False, flood=True)
        until = timezone.now() + timedelta(hours=2)
        EntryPointService.start_flood(until, 'test')
        self.assertIn('floodweb4', EntryPointService.render())
        self.assertFalse(EntryPointService.expire_flood())  # still in force
        EntryPointService.start_flood(timezone.now() - timedelta(minutes=1), 'test')
        self.assertNotIn('floodweb4', EntryPointService.render())  # ignored even before the sweep
        result = reconcile_entrypoints()
        self.assertTrue(result['wrote'] or EntryPointService.flood_until() is None)
        self.assertTrue(AuditEvent.objects.filter(action='flood_mode_off').exists())
        self.assertIsNone(EntryPointService.flood_until())

    def test_system_health_reports_flood_mode(self) -> None:
        from backend.apps.accounts.services import system_health

        EntryPointService.start_flood(timezone.now() + timedelta(hours=1), 'test')
        with patch(
            'backend.apps.core.platform.services.entrypoints.EntryPointService.agent_status'
        ) as agent:
            agent.return_value.reporting = True
            agent.return_value.in_sync = True
            check = system_health._firewall()
        self.assertIn('Flood mode is on', check.summary)
        self.assertEqual(check.state, 'warning')


class AutoProtectPageTests(AutoBase):
    def post(self, **extra: str) -> object:
        data = {
            'block': 'on',
            'hours': '24',
            'allow': '203.0.113.0/24\n198.51.100.7',
            'confirm_password': base.GOOD,
        }
        data.update(extra)
        return self.client.post(reverse('accounts:network_auto'), data, follow=True)

    def test_the_panel_is_there_and_on_by_default(self) -> None:
        page = self.client.get(reverse('accounts:network'))
        self.assertContains(page, 'Automatic protection')
        self.assertRegex(page.content.decode(), r'name="block" checked')
        self.assertRegex(page.content.decode(), r'name="flood" checked')
        self.assertTrue(autoblock.config().block)
        self.assertTrue(autoblock.config().flood)

    def test_saving_needs_the_password_and_is_audited(self) -> None:
        self.assertContains(self.post(confirm_password='wrong'), 'not correct')
        self.assertIsNone(SystemSettings.get(SettingKey.NETWORK_AUTOBLOCK, None))  # nothing saved
        self.assertContains(self.post(), 'Automatic protection saved')
        cfg = autoblock.config()
        self.assertTrue(cfg.block)
        self.assertFalse(cfg.flood)
        self.assertEqual(cfg.allow, ('203.0.113.0/24', '198.51.100.7/32'))
        self.assertTrue(AuditEvent.objects.filter(action='network_auto_config').exists())

    def test_a_bad_allow_list_or_duration_is_refused(self) -> None:
        self.assertContains(self.post(allow='not-a-network'), 'is not an IP address')
        self.assertContains(self.post(hours='5'), 'one of the offered durations')
        self.assertIsNone(SystemSettings.get(SettingKey.NETWORK_AUTOBLOCK, None))

    def test_turning_flood_mode_off_ends_one_in_progress(self) -> None:
        EntryPointService.start_flood(timezone.now() + timedelta(hours=1), 'test')
        self.post(block='')  # flood unchecked: not posted
        self.assertIsNone(EntryPointService.flood_until())

    def test_it_takes_the_security_permission(self) -> None:
        self.login('support@ifinmail.test', role='support')
        response = self.client.post(reverse('accounts:network_auto'), {'hours': '24'})
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(SystemSettings.get(SettingKey.NETWORK_AUTOBLOCK, None))
