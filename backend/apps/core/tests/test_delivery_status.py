"""Delivery status for the owner: parse, classify, count, report, alert, API, dashboard."""

# ruff: noqa: E501  (receiver texts and tables are easier to read unwrapped)

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse

from backend.apps.accounts.tests import test_assistant_views as base
from backend.apps.core.platform.models import AuditEvent  # noqa: F401  (import keeps models loaded)
from backend.apps.core.telemetry import report
from backend.apps.core.telemetry.models import ThreatDigest, ThreatFinding
from backend.apps.core.telemetry.threats import delivery, digest, mail_log
from backend.apps.core.telemetry.threats.types import MailEvent, Severity

NOW = datetime.now(UTC).replace(microsecond=0)


def syslog(at: datetime) -> str:
    return f'{at:%b} {at.day:>2} {at:%H:%M:%S}'


def pf(msg: str, minutes: int = 3) -> str:
    return f'{syslog(NOW - timedelta(minutes=minutes))} mail {msg}'


def status_line(qid: str, to: str, status: str, detail: str, dsn: str = '') -> str:
    dsn_part = f'dsn={dsn}, ' if dsn else ''
    return pf(
        f'postfix/smtp[201]: {qid}: to=<{to}>, relay=mx.example.net[198.51.100.7]:25, delay=1.2, '
        f'delays=0.1/0/0.4/0.7, {dsn_part}status={status} ({detail})'
    )


class ParseTests(SimpleTestCase):
    def parse(self, line: str):
        return mail_log.parse_line(line, NOW)

    def test_an_accepted_message_keeps_its_destination_domain(self) -> None:
        event = self.parse(status_line('AAA111', 'Bob@Gmail.com', 'sent', '250 2.0.0 OK', '2.0.0'))
        assert event is not None
        self.assertEqual((event.kind, event.domain, event.dsn), ('sent', 'gmail.com', '2.0.0'))

    def test_a_bounce_keeps_the_dsn_and_a_scrubbed_reason(self) -> None:
        event = self.parse(
            status_line(
                'BBB222',
                'x@example.com',
                'bounced',
                'host mx.example.com[203.0.113.9] said: 550 5.1.1 <x@example.com>: Recipient '
                'address rejected: User unknown (in reply to RCPT TO command)',
                '5.1.1',
            )
        )
        assert event is not None
        self.assertEqual((event.kind, event.dsn), ('bounced', '5.1.1'))
        self.assertNotIn('x@example.com', event.reason)
        self.assertNotIn('203.0.113.9', event.reason)
        self.assertIn('User unknown', event.reason)

    def test_a_local_delivery_failure_has_no_destination(self) -> None:
        event = self.parse(
            pf(
                'postfix/lmtp[91]: CCC333: to=<alex@ifinmail.test>, relay=dovecot[/run/lmtp], '
                'delay=0.1, dsn=4.2.0, status=deferred (451 4.2.0 mailbox busy)'
            )
        )
        assert event is not None
        self.assertEqual((event.kind, event.domain), ('deferred', ''))

    def test_the_sending_mailbox_is_read_from_the_queue_line(self) -> None:
        event = self.parse(
            pf(
                'postfix/qmgr[88]: DDD444: from=<Alex@IfinMail.test>, size=2048, nrcpt=1 '
                '(queue active)'
            )
        )
        assert event is not None
        self.assertEqual((event.kind, event.sender), ('received', 'alex@ifinmail.test'))

    def test_a_status_line_without_a_dsn_still_parses(self) -> None:
        event = self.parse(
            status_line(
                'EEE555', 'a@b.org', 'deferred', 'connect to mx[1.2.3.4]:25: Connection timed out'
            )
        )
        assert event is not None
        self.assertEqual((event.kind, event.dsn, event.domain), ('deferred', '', 'b.org'))


class ClassifyTests(SimpleTestCase):
    CASES = (
        ('4.7.28', 'host gmail-smtp-in.l.google.com said: 421-4.7.28 Gmail has detected an unusual rate of unsolicited mail', 'rate_limited'),
        ('5.1.1', '550 5.1.1 Recipient address rejected: User unknown in virtual mailbox table', 'unknown_recipient'),
        ('5.7.1', '550 5.7.1 Service unavailable; Client host blocked using Spamhaus', 'blocked'),
        ('5.7.25', '550 5.7.25 The ip address sending this message does not have a PTR record', 'reverse_dns'),
        ('4.4.1', 'connect to mx.example.com: Connection timed out', 'connection'),
        ('5.4.5', '550-5.4.5 Daily user sending quota exceeded', 'rate_limited'),
        ('4.2.2', '452 4.2.2 Mailbox full', 'mailbox_full'),
        ('5.7.26', '550-5.7.26 This message does not pass authentication checks (SPF and DKIM)', 'authentication'),
        ('4.7.0', '450 4.7.0 Greylisted, please try again in 300 seconds', 'greylisted'),
        ('4.4.2', 'Host or domain name not found. Name service error for name=x.invalid', 'connection'),
        ('5.3.4', '552 5.3.4 Message size exceeds fixed limit', 'too_large'),
        ('5.7.0', '554 5.7.0 Message rejected as spam by content filter', 'spam_content'),
        ('', 'something nobody has seen before', 'other'),
    )  # fmt: skip

    def test_the_receivers_words_become_a_category(self) -> None:
        for dsn, text, expected in self.CASES:
            with self.subTest(text=text[:50]):
                self.assertEqual(delivery.classify(dsn, delivery.scrub(text)), expected)

    def test_addresses_and_ips_never_survive_scrubbing(self) -> None:
        text = delivery.scrub(
            'said: 550 <secret@corp.example> from [203.0.113.9]:25 and 2001:db8::1'
        )
        for leaked in ('secret@corp.example', '203.0.113.9', '2001:db8::1'):
            self.assertNotIn(leaked, text)

    def test_ordinary_words_are_not_mistaken_for_ip_addresses(self) -> None:
        self.assertIn('exceeded', delivery.scrub('quota exceeded'))

    def test_a_reason_is_bounded_and_printable(self) -> None:
        text = delivery.scrub('x' * 1000 + '\x00\x1b')
        self.assertLessEqual(len(text), 220)
        self.assertTrue(text.isprintable())

    def test_every_category_explains_itself(self) -> None:
        for category in delivery.BY_KEY.values():
            self.assertTrue(category.label)
            self.assertTrue(category.hint)


def ev(
    kind: str,
    domain: str = 'gmail.com',
    ref: str = 'Q1',
    dsn: str = '',
    reason: str = '',
    sender: str = '',
) -> MailEvent:
    return MailEvent(
        NOW, '', 'postfix', kind, '', 1, ref, domain=domain, dsn=dsn, reason=reason, sender=sender
    )  # noqa: E501


class AggregateTests(SimpleTestCase):
    def test_counts_reasons_destinations_and_senders(self) -> None:
        events = [
            ev('received', domain='', ref='Q1', sender='alex@ifinmail.test'),
            ev('received', domain='', ref='Q2', sender='sam@ifinmail.test'),
            ev('sent', 'gmail.com', 'Q1'),
            ev('bounced', 'example.com', 'Q2', '5.1.1', 'User unknown'),
            ev('deferred', 'outlook.com', 'Q3', '4.7.0', 'rate limited, try again later'),
        ]
        data = delivery.aggregate(events)
        self.assertEqual((data['sent'], data['deferred'], data['bounced']), (1, 1, 1))
        self.assertEqual(data['reasons']['bounced'], {'unknown_recipient': 1})
        self.assertEqual(data['reasons']['deferred'], {'rate_limited': 1})
        self.assertEqual(data['domains']['gmail.com'], [1, 0, 0])
        self.assertEqual(data['senders']['alex@ifinmail.test'], [1, 0, 0])
        self.assertEqual(data['senders']['sam@ifinmail.test'], [0, 0, 1])
        self.assertIn('unknown_recipient', data['examples'])

    def test_local_delivery_failures_are_counted_apart(self) -> None:
        data = delivery.aggregate([ev('deferred', domain='', ref='L1'), ev('sent', 'a.org')])
        self.assertEqual((data['local_failed'], data['sent'], data['deferred']), (1, 1, 0))

    def test_the_destination_table_is_bounded(self) -> None:
        events = [ev('sent', f'host{i}.example') for i in range(40)]
        self.assertLessEqual(len(delivery.aggregate(events)['domains']), delivery.KEEP_DOMAINS)

    def test_providers_group_their_domains(self) -> None:
        for domain, provider in (
            ('gmail.com', 'Google'), ('googlemail.com', 'Google'), ('hotmail.com', 'Microsoft'),
            ('mail.yahoo.com', 'Yahoo'), ('corp.example', 'corp.example'),
        ):  # fmt: skip
            self.assertEqual(delivery.provider_of(domain), provider)


def hourly(sent=0, deferred=0, bounced=0, reasons=None, domains=None, examples=None) -> dict:
    return {
        'sources': {
            'postfix': {
                'delivery': {
                    'sent': sent, 'deferred': deferred, 'bounced': bounced, 'local_failed': 0,
                    'reasons': reasons or {'deferred': {}, 'bounced': {}},
                    'examples': examples or {},
                    'domains': domains or {},
                    'senders': {},
                }
            }
        }
    }  # fmt: skip


class ReportTests(SimpleTestCase):
    def test_no_mail_says_so(self) -> None:
        data = delivery.build([hourly()])
        self.assertEqual(data['verdict']['tone'], 'none')
        self.assertIsNone(data['bounce_rate'])

    def test_a_healthy_sender(self) -> None:
        data = delivery.build([hourly(sent=200, bounced=1)])
        self.assertEqual(data['verdict']['tone'], 'ok')
        self.assertEqual(data['bounce_rate'], 0.5)

    def test_a_rate_over_two_percent_is_a_watch_and_over_five_is_bad(self) -> None:
        self.assertEqual(delivery.build([hourly(sent=96, bounced=4)])['verdict']['tone'], 'watch')
        self.assertEqual(delivery.build([hourly(sent=90, bounced=10)])['verdict']['tone'], 'bad')

    def test_too_few_messages_never_make_a_rate_alarming(self) -> None:
        data = delivery.build([hourly(sent=1, bounced=1)])
        self.assertEqual(data['bounce_rate'], 50.0)
        self.assertEqual(data['verdict']['tone'], 'ok')

    def test_retries_are_not_failures(self) -> None:
        data = delivery.build([hourly(sent=100, deferred=40)])
        self.assertEqual((data['bounce_rate'], data['verdict']['tone']), (0.0, 'ok'))

    def test_the_period_before_gives_a_change(self) -> None:
        data = delivery.build([hourly(sent=90, bounced=10)], [hourly(sent=99, bounced=1)])
        self.assertEqual(data['change']['bounce_rate_points'], 9.0)

    def test_reasons_carry_words_hints_and_the_receivers_example(self) -> None:
        data = delivery.build(
            [
                hourly(
                    sent=10, bounced=6,
                    reasons={'deferred': {}, 'bounced': {'reverse_dns': 6}},
                    examples={'reverse_dns': 'said: 550 5.7.25 no PTR'},
                )
            ]
        )  # fmt: skip
        reason = data['reasons'][0]
        self.assertEqual(
            (reason['category'], reason['kind'], reason['count']), ('reverse_dns', 'bounced', 6)
        )
        self.assertIn('PTR', reason['hint'])
        self.assertIn('no PTR', reason['example'])

    def test_rows_from_before_this_feature_are_ignored_safely(self) -> None:
        data = delivery.build([{'sources': {'postfix': {'sent': 5}}}, hourly(sent=3)])
        self.assertEqual(data['sent'], 3)
        self.assertTrue(data['detail'])

    def test_the_weekly_text_has_a_delivery_section(self) -> None:
        text = '\n'.join(delivery.as_text(delivery.build([hourly(sent=90, bounced=10)])))
        self.assertIn('DELIVERY', text)
        self.assertIn('bounce rate 10.0%', text)


class FindingTests(SimpleTestCase):
    def test_a_healthy_day_raises_nothing(self) -> None:
        self.assertEqual(delivery.findings([hourly(sent=300, bounced=2)], NOW), [])

    def test_a_high_bounce_rate_is_a_high_finding_with_the_top_reason(self) -> None:
        rows = [hourly(sent=80, bounced=20, reasons={'deferred': {}, 'bounced': {'blocked': 20}})]
        found = delivery.findings(rows, NOW)
        top = next(f for f in found if f.kind == 'delivery_bounce_rate')
        self.assertEqual(top.severity, Severity.HIGH)
        self.assertIn('blocked', top.summary.lower())

    def test_two_to_five_percent_is_only_medium(self) -> None:
        found = delivery.findings([hourly(sent=96, bounced=4)], NOW)
        self.assertEqual(found[0].severity, Severity.MEDIUM)

    def test_few_messages_are_never_an_alert(self) -> None:
        self.assertEqual(delivery.findings([hourly(sent=5, bounced=5)], NOW), [])

    def test_a_provider_that_mostly_refuses_is_named(self) -> None:
        rows = [
            hourly(
                sent=2, deferred=8,
                reasons={'deferred': {'rate_limited': 8}, 'bounced': {}},
                domains={'gmail.com': [2, 8, 0]},
            )
        ]  # fmt: skip
        found = [f for f in delivery.findings(rows, NOW) if f.kind == 'delivery_provider']
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].subject, found[0].severity), ('Google', Severity.HIGH))

    def test_a_provider_that_mostly_accepts_is_not(self) -> None:
        rows = [hourly(sent=50, deferred=6, domains={'gmail.com': [50, 6, 0]})]
        self.assertEqual(
            [f for f in delivery.findings(rows, NOW) if f.kind == 'delivery_provider'], []
        )


class IntegrationTests(base.AssistantBase):
    def digest_row(self, hours_ago: int, **figures: int) -> None:
        hour = (NOW - timedelta(hours=hours_ago)).replace(minute=0, second=0)
        ThreatDigest.objects.update_or_create(hour=hour, defaults={'summary': hourly(**figures)})

    def test_the_section_sums_the_periods_digests(self) -> None:
        self.digest_row(2, sent=40, bounced=1)
        self.digest_row(5, sent=60, bounced=3, deferred=7)
        section = report.delivery_section('day', NOW)
        self.assertEqual((section['sent'], section['bounced'], section['deferred']), (100, 4, 7))
        self.assertEqual(section['bounce_rate'], 3.8)

    def test_the_full_report_carries_the_same_section(self) -> None:
        self.digest_row(2, sent=40, bounced=1)
        self.assertEqual(report.build('day')['delivery']['sent'], 40)

    def test_the_digest_raises_a_delivery_finding_and_emails_the_owner(self) -> None:
        for h in (2, 3, 4):
            self.digest_row(
                h, sent=20, bounced=10,
                reasons={'deferred': {}, 'bounced': {'reverse_dns': 10}},
            )  # fmt: skip
        with (
            patch('backend.apps.core.telemetry.threats.digest.access_log.read_window') as win,
            patch('backend.apps.core.telemetry.threats.digest.mail_log.read_window_with_stats', return_value=([], {})),
            patch('backend.apps.core.telemetry.threats.digest.send_mail') as mail,
            patch('backend.apps.mail.services.containment._recipients_of_alerts', return_value=['owner@ifinmail.test']),
        ):  # fmt: skip
            win.return_value = type(
                'R', (), {'requests': [], 'skipped_bytes': 0, 'available': True}
            )()
            result = digest.run(NOW, summarise=False)
        kinds = {f.kind for f in result.findings}
        self.assertIn('delivery_bounce_rate', kinds)
        self.assertTrue(ThreatFinding.objects.filter(kind='delivery_bounce_rate').exists())
        self.assertTrue(mail.called)
        self.assertIn('bouncing', mail.call_args.args[0] + mail.call_args.args[1].lower())

    def test_the_api_returns_the_typed_contract(self) -> None:
        import base64

        from backend.apps.accounts.services.tokens import TokenService, key_id

        self.digest_row(
            1, sent=100, bounced=1,
            reasons={'deferred': {}, 'bounced': {'unknown_recipient': 1}},
            domains={'gmail.com': [100, 0, 1]},
        )  # fmt: skip
        row, token = TokenService.create(self.admin, 'monitor', ['audit.view'], expires_in_days=30)
        auth = base64.b64encode(f'{key_id(row.prefix)}:{token.split(".", 2)[2]}'.encode()).decode()
        response = self.client.get(
            '/api/v1/telemetry/delivery?period=day', HTTP_AUTHORIZATION=f'Basic {auth}'
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual((body['sent'], body['bounced']), (100, 1))
        self.assertEqual(body['verdict']['tone'], 'ok')
        self.assertEqual(body['destinations'][0]['provider'], 'Google')
        denied = self.client.get('/api/v1/telemetry/delivery')
        self.assertEqual(denied.status_code, 401)

    def test_the_dashboard_and_the_report_show_the_panel(self) -> None:
        self.digest_row(
            1, sent=80, bounced=20, reasons={'deferred': {}, 'bounced': {'blocked': 20}}
        )
        dash = self.client.get(reverse('accounts:dashboard'))
        self.assertContains(dash, 'Outgoing mail delivery')
        self.assertContains(dash, 'ifinmail-delivery--bad')
        page = self.client.get(reverse('accounts:logs_report'), {'period': 'day'})
        self.assertContains(page, 'Why they failed')
        self.assertContains(page, 'Blocked for reputation')

    def test_the_dashboard_still_opens_if_the_figures_fail(self) -> None:
        with patch('backend.apps.core.telemetry.report.delivery_section', side_effect=RuntimeError):
            self.assertEqual(self.client.get(reverse('accounts:dashboard')).status_code, 200)
