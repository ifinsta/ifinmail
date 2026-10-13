"""Failed mail sign-ins, relay probing and address guessing, from the Postfix and Dovecot logs
into the threat digest, the Threats page and (opt-in) the automatic block."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse

from backend.apps.accounts.tests import test_assistant_views as base
from backend.apps.core.platform.services.entrypoints import EntryPointService
from backend.apps.core.telemetry.models import ThreatFinding
from backend.apps.core.telemetry.threats import autoblock, digest, mail_log, mail_rules
from backend.apps.core.telemetry.threats.types import MailEvent, Severity


def _syslog(at: datetime) -> str:
    """A syslog-style stamp as Postfix and Dovecot write it (day padded with a space)."""
    return f'{at:%b} {at.day:>2} {at:%H:%M:%S}'


NOW = datetime.now(UTC).replace(microsecond=0)  # blocks are judged by the real clock


def stamp(minutes_ago: int = 3) -> str:
    return _syslog(NOW - timedelta(minutes=minutes_ago))


def sasl(ip: str, minutes: int = 3) -> str:
    return (
        f'{stamp(minutes)} mail postfix/submission/smtpd[41]: warning: unknown[{ip}]: '
        'SASL LOGIN authentication failed: (reason unavailable)'
    )


def dovecot_fail(ip: str, who: str, attempts: int = 3, minutes: int = 3) -> str:
    return (
        f'{stamp(minutes)} imap-login: Info: Disconnected: Connection closed: read failed '
        f'(auth failed, {attempts} attempts in 6 secs): user=<{who}>, method=PLAIN, rip={ip}, '
        'lip=192.0.2.10, TLS, session=<abc>'
    )


def dovecot_ok(ip: str, who: str, minutes: int = 1) -> str:
    return (
        f'{stamp(minutes)} imap-login: Info: Login: user=<{who}>, method=PLAIN, rip={ip}, '
        'lip=192.0.2.10, mpid=9, TLS, session=<def>'
    )


def relay(ip: str, minutes: int = 3) -> str:
    return (
        f'{stamp(minutes)} mail postfix/smtpd[40]: NOQUEUE: reject: RCPT from unknown[{ip}]: '
        '554 5.7.1 <victim@example.net>: Relay access denied; from=<a@b.test> '
        'to=<victim@example.net> proto=ESMTP helo=<x>'
    )


def unknown(ip: str, n: int, minutes: int = 3) -> str:
    return (
        f'{stamp(minutes)} mail postfix/smtpd[40]: NOQUEUE: reject: RCPT from unknown[{ip}]: '
        f'550 5.1.1 <user{n}@ifinmail.test>: Recipient address rejected: User unknown in '
        'virtual mailbox table; from=<a@b.test> to=<user@ifinmail.test> proto=ESMTP helo=<x>'
    )


class ParseTests(SimpleTestCase):
    def parse(self, line: str) -> MailEvent | None:
        return mail_log.parse_line(line, NOW)

    def test_a_failed_postfix_sasl_login(self) -> None:
        event = self.parse(sasl('203.0.113.9'))
        assert event is not None
        self.assertEqual(
            (event.kind, event.net, event.service), ('auth_failed', '203.0.113.0/24', 'postfix')
        )

    def test_a_failed_dovecot_login_counts_its_attempts_and_names_the_account(self) -> None:
        event = self.parse(dovecot_fail('203.0.113.9', 'bob@ifinmail.test', attempts=4))
        assert event is not None
        self.assertEqual(
            (event.kind, event.weight, event.who), ('auth_failed', 4, 'bob@ifinmail.test')
        )

    def test_a_line_exactly_as_real_dovecot_wrote_it(self) -> None:
        line = (
            'Oct 13 12:27:19 imap-login: Info: Disconnected: Connection closed: Connection reset '
            'by peer (auth failed, 1 attempts in 2 secs): user=<bob@example.test>, method=PLAIN, '
            'rip=203.0.113.9, lip=127.0.0.1, secured, session=<pNcfVLZdYId/AAAB>'
        )
        event = self.parse(line)
        assert event is not None
        self.assertEqual(
            (event.kind, event.who, event.weight), ('auth_failed', 'bob@example.test', 1)
        )

    def test_a_successful_login(self) -> None:
        event = self.parse(dovecot_ok('203.0.113.9', 'bob@ifinmail.test'))
        assert event is not None
        self.assertEqual((event.kind, event.who), ('login_success', 'bob@ifinmail.test'))

    def test_relay_attempts_and_unknown_recipients(self) -> None:
        event = self.parse(relay('198.51.100.4'))
        assert event is not None
        self.assertEqual(event.kind, 'relay_denied')
        event = self.parse(unknown('198.51.100.4', 1))
        assert event is not None
        self.assertEqual(event.kind, 'unknown_recipient')

    def test_ipv6_clients_are_a_slash_48(self) -> None:
        event = self.parse(sasl('2001:db8:1:2::9'))
        assert event is not None
        self.assertEqual(event.net, '2001:db8:1::/48')

    def test_everything_else_is_dropped(self) -> None:
        for line in (
            f'{stamp()} mail postfix/smtpd[40]: connect from unknown[203.0.113.9]',
            f'{stamp()} imap-login: Info: Disconnected: (no auth attempts in 0 secs): '
            'user=<>, rip=203.0.113.9, lip=192.0.2.10',
            'garbage',
            '',
            'x' * 5000,
        ):
            self.assertIsNone(self.parse(line), line[:40])

    def test_a_timestamp_with_a_year_and_zone_is_read_as_given(self) -> None:
        line = '2026-10-13T12:27:00+00:00 imap-login: Info: Login: user=<a@b.test>, rip=203.0.113.9'
        event = self.parse(line)
        assert event is not None
        self.assertEqual(event.at, datetime(2026, 10, 13, 12, 27, tzinfo=UTC))

    def test_a_december_line_read_in_january_is_last_year(self) -> None:
        jan = datetime(2027, 1, 1, 0, 5, tzinfo=UTC)
        event = mail_log.parse_line(
            'Dec 31 23:58:00 imap-login: Info: Login: user=<a@b.test>, rip=203.0.113.9', jan
        )
        assert event is not None
        self.assertEqual(event.at.year, 2026)


class ReaderTests(SimpleTestCase):
    def test_both_logs_and_the_rotated_copy_are_read_and_old_lines_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / 'postfix.log').write_text(
                sasl('203.0.113.9', 5) + '\n' + relay('198.51.100.4') + '\n'
            )
            (d / 'postfix.log.1').write_text(sasl('203.0.113.9', 90) + '\n')
            (d / 'dovecot.log').write_text(dovecot_fail('203.0.113.9', 'a@b.test') + '\n')
            events = mail_log.read_window(NOW - timedelta(hours=1), NOW, directory=d)
        self.assertEqual(
            sorted(e.kind for e in events), ['auth_failed', 'auth_failed', 'relay_denied']
        )

    def test_missing_logs_are_empty_not_an_error(self) -> None:
        self.assertEqual(mail_log.read_window(NOW, NOW, directory=Path('/nonexistent')), [])
        self.assertFalse(mail_log.available(Path('/nonexistent')))


def ev(
    kind: str, net: str = '203.0.113.0/24', who: str = '', weight: int = 1, minutes: int = 10
) -> MailEvent:
    return MailEvent(NOW - timedelta(minutes=minutes), net, 'dovecot', kind, who, weight)


class RuleTests(SimpleTestCase):
    def kinds(self, events: list[MailEvent]) -> dict[str, Severity]:
        return {f.kind: f.severity for f in mail_rules.analyze(events)}

    def test_a_few_failures_are_not_a_finding(self) -> None:
        self.assertEqual(self.kinds([ev('auth_failed', who='a@b.test', weight=3)]), {})

    def test_one_account_failing_repeatedly_is_a_client_not_an_attack(self) -> None:
        found = mail_rules.analyze([ev('auth_failed', who='a@b.test', weight=12)])
        self.assertEqual(found[0].severity, Severity.MEDIUM)
        self.assertIn('client', found[0].summary)

    def test_many_accounts_from_one_network_is_password_spraying(self) -> None:
        events = [ev('auth_failed', who=f'u{i}@b.test', weight=3) for i in range(5)]
        found = mail_rules.analyze(events)
        self.assertEqual(found[0].severity, Severity.HIGH)
        self.assertIn('spraying', found[0].summary)
        self.assertEqual(found[0].subject, '203.0.113.0/24')

    def test_sheer_volume_is_high_even_without_account_names(self) -> None:
        events = [ev('auth_failed', weight=1) for _ in range(60)]
        self.assertEqual(self.kinds(events), {'mail_login_guessing': Severity.HIGH})

    def test_relay_probing_and_address_guessing(self) -> None:
        events = [ev('relay_denied') for _ in range(4)] + [
            ev('unknown_recipient') for _ in range(25)
        ]
        self.assertEqual(
            self.kinds(events),
            {'mail_relay_probe': Severity.MEDIUM, 'mail_recipient_guessing': Severity.MEDIUM},
        )

    def test_the_servers_own_side_is_ignored(self) -> None:
        events = [ev('auth_failed', net='172.18.0.0/24', weight=80)]
        self.assertEqual(mail_rules.analyze(events), [])

    def test_a_distributed_attack_is_one_finding(self) -> None:
        events = [
            ev('auth_failed', net=f'198.51.{i}.0/24', who='a@b.test', weight=4) for i in range(16)
        ]
        found = {f.kind for f in mail_rules.analyze(events)}
        self.assertIn('mail_distributed_guessing', found)

    def test_a_sign_in_right_after_a_spray_is_critical(self) -> None:
        events = [ev('auth_failed', who=f'u{i}@b.test', weight=2, minutes=20 - i) for i in range(4)]
        events.append(ev('login_success', who='u2@b.test', minutes=5))
        by_kind = {f.kind: f for f in mail_rules.analyze(events)}
        self.assertEqual(by_kind['mail_success_after_failures'].severity, Severity.CRITICAL)
        self.assertEqual(by_kind['mail_success_after_failures'].subject, 'u2@b.test')

    def test_finally_typing_the_right_password_is_not_a_breach(self) -> None:
        events = [ev('auth_failed', who='a@b.test', weight=3, minutes=20)]
        events.append(ev('login_success', who='a@b.test', minutes=5))
        self.assertEqual(self.kinds(events), {})


class EndToEndTests(base.AssistantBase):
    def setUp(self) -> None:
        super().setUp()
        self.dir = Path(tempfile.mkdtemp(prefix='ifm-mail-'))
        env = patch.dict(
            os.environ,
            {
                'IFINMAIL_MAIL_LOG_DIR': str(self.dir),
                'IFINMAIL_ACCESS_LOG': str(self.dir / 'none.json'),
                'ADMIN_EMAIL': '',
            },
        )
        env.start()
        self.addCleanup(env.stop)
        server = patch(
            'backend.apps.dns.services.server.DNSServerConfig.server_ipv4',
            return_value='192.0.2.10',
        )
        server.start()
        self.addCleanup(server.stop)

    def spray(self, ip: str = '203.0.113.9') -> None:
        lines = [dovecot_fail(ip, f'user{i}@ifinmail.test', attempts=3) for i in range(6)]
        lines += [sasl(ip) for _ in range(5)]
        (self.dir / 'dovecot.log').write_text('\n'.join(lines) + '\n')

    def test_the_digest_finds_it_and_the_page_shows_it(self) -> None:
        self.spray()
        result = digest.run(NOW, summarise=False)
        self.assertEqual(result.summary.mail_failures, 23)
        finding = ThreatFinding.objects.get(kind='mail_login_guessing')
        self.assertEqual(finding.subject, '203.0.113.0/24')
        self.assertEqual(finding.severity, int(Severity.HIGH))
        page = self.client.get(reverse('accounts:threats'))
        self.assertContains(page, 'Password guessing against the mail ports')
        self.assertContains(page, 'Failed mail sign-ins')
        self.assertContains(page, 'Block this network')  # the one-click block covers it
        self.assertNotContains(page, '203.0.113.9')

    def test_the_assistant_gets_masked_account_names_only(self) -> None:
        from backend.apps.core.telemetry.threats import summarize

        self.spray()
        result = digest.run(NOW, summarise=False)
        facts = str(summarize.facts(result.summary, result.findings))
        self.assertNotIn('user0@ifinmail.test', facts)
        self.assertIn('u***@ifinmail.test', facts)
        self.assertIn("'mail_failures': 23", facts)

    def test_with_automatic_blocking_on_the_network_is_blocked_then_released(self) -> None:
        autoblock.save(block=True, flood=False, hours=1, allow_text='')
        self.spray()
        digest.run(NOW, summarise=False)
        self.assertEqual(autoblock.run(NOW).blocked, ['203.0.113.0/24'])
        self.assertIn('203.0.113.0/24', EntryPointService.render())
        EntryPointService.expire(NOW + timedelta(hours=2))
        self.assertEqual(EntryPointService.blocklist(), [])
