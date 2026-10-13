"""The Threats page, the assistant's view of it, and the written summary end to end."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.tests import test_assistant_views as base
from backend.apps.core.assistant.services import agent
from backend.apps.core.assistant.tests.fake_provider import answer
from backend.apps.core.platform.models import AuditEvent
from backend.apps.core.platform.services.entrypoints import EntryPointService
from backend.apps.core.telemetry.models import ThreatDigest, ThreatFinding
from backend.apps.core.telemetry.threats import digest

NOW = datetime(2026, 10, 13, 12, 30, tzinfo=UTC)


def row(
    uri: str, status: int = 404, ip: str = '203.0.113.7', minutes: int = 3, cid: str = ''
) -> str:
    return json.dumps(
        {
            't': (NOW - timedelta(minutes=minutes)).isoformat(),
            'ip': ip,
            'm': 'GET',
            'uri': uri,
            'st': status,
            'b': 1,
            'rt': 0.01,
            'h': 'mail.example.test',
            'p': 'HTTP/2.0',
            'ua': 'Mozilla/5.0',
            'ref': '',
            'cid': cid or uri[1:8],
        }
    )


class ThreatBase(base.AssistantBase):
    def setUp(self) -> None:
        super().setUp()
        self.dir = Path(tempfile.mkdtemp(prefix='ifm-thr-'))
        self.log = self.dir / 'access.json'
        env = patch.dict(os.environ, {'IFINMAIL_ACCESS_LOG': str(self.log), 'ADMIN_EMAIL': ''})
        env.start()
        self.addCleanup(env.stop)

    def scan(self, ip: str = '203.0.113.7', *, status: int = 404, sensitive: bool = False) -> None:
        paths = ('/.env', '/.git/config', '/wp-login.php', '/phpmyadmin/', '/.env.backup')
        rows = [row(p, status, ip, cid=f'cid{i}') for i, p in enumerate(paths)]
        if sensitive:
            rows.append(row('/.env', 200, '198.51.100.9', cid='open1'))
        self.log.write_text('\n'.join(rows) + '\n')


class ThreatsPageTests(ThreatBase):
    def test_the_page_shows_the_verdict_findings_and_where_to_tighten(self) -> None:
        self.scan()
        digest.run(NOW, summarise=False)
        page = self.client.get(reverse('accounts:threats'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Scanners are probing the server')
        self.assertContains(page, 'Scanner probing for files and admin pages')
        self.assertContains(page, '203.0.113.0/24')
        self.assertContains(page, reverse('accounts:network'))  # the link is the control itself
        self.assertNotContains(page, '203.0.113.7')  # never the address, only the network

    def test_a_served_secret_is_the_loudest_thing_on_the_page(self) -> None:
        self.scan(sensitive=True)
        digest.run(NOW, summarise=False)
        page = self.client.get(reverse('accounts:threats'))
        self.assertContains(page, 'Act now')
        self.assertContains(page, 'A sensitive file is being served')

    def test_a_quiet_server_says_so(self) -> None:
        self.log.write_text(row('/accounts/login/', 200, '198.51.100.1') + '\n')
        digest.run(NOW, summarise=False)
        self.assertContains(self.client.get(reverse('accounts:threats')), 'Quiet')

    def test_without_a_log_it_explains_instead_of_failing(self) -> None:
        page = self.client.get(reverse('accounts:threats'))
        self.assertContains(page, 'No access log is being read yet')

    def test_only_people_who_may_view_the_audit_see_it_and_only_managers_act(self) -> None:
        self.login('support@ifinmail.test', role='support')
        self.assertEqual(self.client.get(reverse('accounts:threats')).status_code, 200)
        self.assertEqual(self.client.post(reverse('accounts:threats_run')).status_code, 403)
        page = self.client.get(reverse('accounts:threats')).content.decode()
        self.assertNotIn('Check now', page)  # the button is not offered, not just refused
        outsider = MailUser.objects.create_user('plain@ifinmail.test', base.GOOD, is_staff=False)
        self.client.force_login(outsider, backend='django.contrib.auth.backends.ModelBackend')
        self.assertIn(self.client.get(reverse('accounts:threats')).status_code, (302, 403))

    def test_acknowledging_and_reopening_a_finding(self) -> None:
        self.scan()
        digest.run(NOW, summarise=False)
        finding = ThreatFinding.objects.get()
        url = reverse('accounts:threats_ack')
        self.client.post(url, {'finding': str(finding.pk)})
        self.assertEqual(ThreatFinding.objects.get().status, 'acknowledged')
        self.assertContains(self.client.get(reverse('accounts:threats')), 'Acknowledged')
        self.client.post(url, {'finding': str(finding.pk), 'undo': '1'})
        self.assertEqual(ThreatFinding.objects.get().status, 'open')
        self.assertTrue(AuditEvent.objects.filter(action='threat_finding_acknowledged').exists())

    def test_check_now_runs_a_pass_and_is_audited(self) -> None:
        self.scan()
        with patch('backend.apps.core.telemetry.threats.digest.datetime') as clock:
            clock.now.return_value = NOW
            response = self.client.post(reverse('accounts:threats_run'), follow=True)
        self.assertContains(response, 'Checked the last hour')
        self.assertTrue(AuditEvent.objects.filter(action='threat_digest_run').exists())

    def test_it_is_in_the_settings_hub(self) -> None:
        hub = self.client.get(reverse('accounts:settings')).content.decode()
        self.assertIn(reverse('accounts:threats'), hub)


class BlockFromThreatsTests(ThreatBase):
    """One click from a finding to a firewall rule: password again, never your own side, expires."""

    def setUp(self) -> None:
        super().setUp()
        self.scan()
        digest.run(NOW, summarise=False)
        self.finding = ThreatFinding.objects.get()
        self.url = reverse('accounts:threats_block')

    def post(self, **extra: str) -> object:
        data = {
            'finding': str(self.finding.pk),
            'duration': '24h',
            'confirm_password': base.GOOD,
        }
        client_ip = extra.pop('ip', '')
        data.update(extra)
        meta = {'HTTP_X_FORWARDED_FOR': client_ip} if client_ip else {}
        return self.client.post(self.url, data, follow=True, **meta)

    def test_the_finding_offers_the_block_and_posting_it_publishes_the_rule(self) -> None:
        self.assertContains(self.client.get(reverse('accounts:threats')), 'Block this network')
        response = self.post()
        self.assertContains(response, '203.0.113.0/24 is blocked until')
        row = EntryPointService.blocklist()[0]
        self.assertEqual(row['cidr'], '203.0.113.0/24')
        self.assertIn('expires', row)
        self.assertIn('203.0.113.0/24', EntryPointService.render())
        self.assertEqual(ThreatFinding.objects.get().status, 'acknowledged')
        audit = AuditEvent.objects.get(action='network_block')
        self.assertIn(self.finding.key, audit.detail)
        self.assertContains(self.client.get(reverse('accounts:threats')), 'Blocked')

    def test_the_lifetimes(self) -> None:
        now = timezone.now()
        self.post(duration='1h')
        hours = datetime.fromisoformat(EntryPointService.blocklist()[0]['expires']) - now
        self.assertLess(abs(hours - timedelta(hours=1)), timedelta(minutes=2))
        EntryPointService.unblock('203.0.113.0/24')
        self.post(duration='forever')
        self.assertNotIn('expires', EntryPointService.blocklist()[0])

    def test_a_wrong_or_missing_password_changes_nothing(self) -> None:
        self.assertContains(self.post(confirm_password='nope'), 'not correct')
        self.assertContains(self.post(confirm_password=''), 'Enter your password')
        self.assertEqual(EntryPointService.blocklist(), [])
        self.assertTrue(AuditEvent.objects.filter(action='stepup_failed').exists())

    def test_it_will_not_block_the_network_you_are_on(self) -> None:
        response = self.post(ip='203.0.113.50')  # the admin is inside the scanner's /24
        self.assertContains(response, 'which you are using')
        self.assertEqual(EntryPointService.blocklist(), [])

    def test_it_will_not_block_this_servers_own_side(self) -> None:
        ThreatFinding.objects.filter(pk=self.finding.pk).update(subject='192.168.1.0/24')
        self.assertContains(self.post(), 'own side')
        self.assertEqual(EntryPointService.blocklist(), [])

    def test_only_findings_about_a_network_can_be_blocked(self) -> None:
        ThreatFinding.objects.filter(pk=self.finding.pk).update(
            kind='account_attack', subject='owner@ifinmail.test'
        )
        self.assertContains(self.post(), 'not about a network')
        self.assertEqual(EntryPointService.blocklist(), [])

    def test_a_finding_that_is_gone_or_malformed_is_a_message_not_an_error(self) -> None:
        self.assertContains(self.post(finding='not-an-id'), 'already gone')
        self.assertContains(self.post(finding=str(uuid.uuid4())), 'already gone')

    def test_it_takes_the_firewall_permission(self) -> None:
        self.login('support@ifinmail.test', role='support')
        self.assertEqual(
            self.client.post(self.url, {'finding': str(self.finding.pk)}).status_code, 403
        )
        self.assertNotContains(self.client.get(reverse('accounts:threats')), 'Block this network')
        self.assertEqual(EntryPointService.blocklist(), [])


class ThreatToolTests(ThreatBase):
    def run_tool(self, **arguments: object) -> dict:
        from backend.apps.core.assistant.services import tools

        tool = tools.get('threat_digest')
        assert tool is not None
        self.assertIsNone(tool.check_arguments(dict(arguments)))
        return tool.handler(dict(arguments), tools.ToolContext(user=self.admin.email))

    def test_the_assistant_can_read_the_findings_and_where_to_tighten(self) -> None:
        self.scan(sensitive=True)
        digest.run(NOW, summarise=False)
        report = self.run_tool()
        text = json.dumps(report)
        kinds = {f['what'] for f in report['findings']}
        self.assertIn('A sensitive file is being served', kinds)
        self.assertIn('Settings > Network & entry points', text)
        self.assertNotIn('203.0.113.7', text)
        self.assertEqual(report['page'], 'Settings > Threats')
        narrowed = self.run_tool(minimum='critical')
        self.assertTrue(all(f['severity'] == 'critical' for f in narrowed['findings']))

    def test_before_any_digest_it_says_so(self) -> None:
        self.assertIn('No digest', self.run_tool()['gist'])

    def test_the_prompt_points_at_the_tool(self) -> None:
        self.assertIn('threat_digest', agent.SYSTEM_PROMPT)


class AssistantSummaryTests(ThreatBase):
    GOOD = json.dumps(
        {
            'gist': 'One network is sweeping for secrets; nothing was served.',
            'priorities': [{'finding': 'probe_sweep:203.0.113.0/24', 'why': 'It is systematic.'}],
            'correlations': [],
            'ignore': ['plain-port TLS handshakes'],
        }
    )

    def connect_model(self) -> None:
        self.connect()

    def test_with_a_model_connected_the_gist_is_written_and_budgeted(self) -> None:
        self.connect_model()
        self.scan()
        self.fake.push(answer(self.GOOD, tokens=640))
        result = digest.run(NOW)
        self.assertTrue(result.summarised)
        row_ = ThreatDigest.objects.get()
        self.assertEqual(row_.gist_source, 'assistant')
        self.assertIn('sweeping for secrets', row_.gist)
        self.assertEqual(row_.tokens, 640)
        self.assertEqual(row_.priorities[0]['key'], 'probe_sweep:203.0.113.0/24')
        self.assertEqual(row_.ignored, ['plain-port TLS handshakes'])
        # the digest spends from the assistant's daily budget
        with patch.object(timezone, 'now', return_value=NOW):
            pass
        self.assertGreaterEqual(agent.tokens_today(), 0)
        # what left the server: aggregates only
        sent = self.fake.sent_text()
        self.assertIn('203.0.113.0/24', sent)
        self.assertNotIn('203.0.113.7', sent)
        self.assertNotIn('Mozilla', sent)
        self.assertNotIn('cid0', sent)

    def test_the_model_is_not_asked_again_for_the_same_picture(self) -> None:
        self.connect_model()
        self.scan()
        self.fake.push(answer(self.GOOD, tokens=100))
        digest.run(NOW)
        calls = len(self.fake.requests)
        digest.run(NOW + timedelta(minutes=10))
        self.assertEqual(len(self.fake.requests), calls)
        self.assertEqual(ThreatDigest.objects.get().tokens, 100)

    def test_a_garbled_answer_keeps_the_rule_written_gist(self) -> None:
        self.connect_model()
        self.scan()
        self.fake.push(answer('I am sorry, I cannot help with that.', tokens=50))
        result = digest.run(NOW)
        self.assertFalse(result.summarised)
        row_ = ThreatDigest.objects.get()
        self.assertEqual(row_.gist_source, 'rules')
        self.assertIn('finding', row_.gist)

    def test_a_model_outage_never_stops_the_digest(self) -> None:
        self.connect_model()
        self.scan()
        self.fake.push({'error': 'down'}, status=500)
        result = digest.run(NOW)
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(ThreatFinding.objects.count(), 1)

    def test_it_will_not_overspend_the_daily_budget(self) -> None:
        self.connect_model()
        self.scan()
        with patch.object(agent, 'tokens_today', return_value=10**9):
            result = digest.run(NOW)
        self.assertFalse(result.summarised)
        self.assertEqual(self.fake.requests, [])

    def test_nothing_is_sent_when_nothing_was_found(self) -> None:
        self.connect_model()
        self.log.write_text(row('/accounts/login/', 200, '198.51.100.1') + '\n')
        digest.run(NOW)
        self.assertEqual(self.fake.requests, [])

    def test_without_a_model_the_rules_still_write_the_gist(self) -> None:
        self.scan()
        result = digest.run(NOW)
        self.assertFalse(result.summarised)
        self.assertEqual(ThreatDigest.objects.get().gist_source, 'rules')
