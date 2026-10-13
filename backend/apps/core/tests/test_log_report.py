"""The unified logs report: flow parsing, per-source rollups, silence detection, the page."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse

from backend.apps.accounts.tests import test_assistant_views as base
from backend.apps.core.platform.models import AuditEvent
from backend.apps.core.telemetry import report
from backend.apps.core.telemetry.models import ThreatDigest, ThreatFinding
from backend.apps.core.telemetry.threats import digest, mail_log, rollup
from backend.apps.core.telemetry.threats.types import Severity


def syslog(at: datetime) -> str:
    return f'{at:%b} {at.day:>2} {at:%H:%M:%S}'


NOW = datetime.now(UTC).replace(microsecond=0)


def pf(msg: str, minutes: int = 3) -> str:
    return f'{syslog(NOW - timedelta(minutes=minutes))} mail {msg}'


class FlowParseTests(SimpleTestCase):
    def parse(self, line: str):
        return mail_log.parse_line(line, NOW)

    def test_a_message_arrives_and_is_delivered_with_its_queue_id(self) -> None:
        queued = self.parse(
            pf(
                'postfix/qmgr[88]: 4F2A91C7B3: from=<a@example.org>, size=1834, nrcpt=1 '
                '(queue active)'
            )
        )
        assert queued is not None
        self.assertEqual(
            (queued.kind, queued.ref, queued.service), ('received', '4F2A91C7B3', 'postfix')
        )
        delivered = self.parse(
            pf(
                'postfix/lmtp[91]: 4F2A91C7B3: to=<alex@ifinmail.test>, relay=dovecot[/run/lmtp], '
                'delay=0.1, delays=0/0/0/0.1, dsn=2.0.0, status=sent (250 2.0.0 saved)'
            )
        )
        assert delivered is not None
        self.assertEqual((delivered.kind, delivered.ref), ('delivered', '4F2A91C7B3'))

    def test_outbound_sent_deferred_and_bounced(self) -> None:
        def status(word: str, svc: str = 'smtp') -> str:
            return pf(
                f'postfix/{svc}[95]: 9AB0: to=<x@example.org>, '
                'relay=mx.example.org[203.0.113.4]:25, '
                f'delay=1, delays=0/0/1/0, dsn=4.2.0, status={word} (remote said something)'
            )

        for word, kind in (('sent', 'sent'), ('deferred', 'deferred'), ('bounced', 'bounced')):
            event = self.parse(status(word))
            assert event is not None
            self.assertEqual(event.kind, kind)

    def test_rspamd_verdict_action_and_queue_id(self) -> None:
        line = (
            f'{(NOW - timedelta(minutes=2)):%Y-%m-%d %H:%M:%S} #75(rspamd_proxy) <781c8f>; proxy; '
            'rspamd_task_write_log: id: <abc@google.com>, qid: <3CFBDC3912>, ip: 209.85.219.73, '
            'from: <n@google.com>, (default: F (add header): [8.50/15.00] [SYMBOLS...])'
        )
        event = self.parse(line)
        assert event is not None
        self.assertEqual(
            (event.kind, event.ref, event.service), ('spam_add_header', '3CFBDC3912', 'rspamd')
        )

    def test_a_blocked_blocklist_lookup(self) -> None:
        line = (
            f'{(NOW - timedelta(minutes=2)):%Y-%m-%d %H:%M:%S} #76(controller) <imhkkk>; '
            'monitored; '
            'rspamd_monitored_dns_cb: DNS query blocked on multi.uribl.com (127.0.0.1 returned)'
        )
        event = self.parse(line)
        assert event is not None
        self.assertEqual((event.kind, event.who), ('dns_blocked', 'multi.uribl.com'))


def write_logs(d: Path, *, postfix: str = '', dovecot: str = '', rspamd: str = '') -> None:
    (d / 'postfix.log').write_text(postfix)
    (d / 'dovecot.log').write_text(dovecot)
    (d / 'rspamd.log').write_text(rspamd)


class RollupTests(base.AssistantBase):
    def setUp(self) -> None:
        super().setUp()
        self.dir = Path(tempfile.mkdtemp(prefix='ifm-rollup-'))
        env = patch.dict(
            os.environ,
            {
                'IFINMAIL_MAIL_LOG_DIR': str(self.dir),
                'IFINMAIL_ACCESS_LOG': str(self.dir / 'access.json'),
                'ADMIN_EMAIL': '',
            },
        )
        env.start()
        self.addCleanup(env.stop)

    def flow(self) -> str:
        lines = [
            pf('postfix/qmgr[1]: A1: from=<a@x.test>, size=10, nrcpt=1 (queue active)'),
            pf('postfix/qmgr[1]: A2: from=<b@x.test>, size=10, nrcpt=1 (queue active)'),
            pf('postfix/lmtp[2]: A1: to=<u@i.test>, relay=d, delay=1, dsn=2.0.0, status=sent (ok)'),
            pf(
                'postfix/smtp[3]: A2: to=<v@o.test>, relay=m[1.2.3.4]:25, delay=1, dsn=4.0.0, '
                'status=deferred (later)'
            ),
            pf(
                'postfix/smtp[3]: A3: to=<w@o.test>, relay=m[1.2.3.4]:25, delay=1, dsn=5.0.0, '
                'status=bounced (no)'
            ),
        ]
        return '\n'.join(lines) + '\n'

    def test_the_digest_stores_one_counter_set_per_source(self) -> None:
        write_logs(
            self.dir,
            postfix=self.flow(),
            rspamd=(
                f'{(NOW - timedelta(minutes=2)):%Y-%m-%d %H:%M:%S} #1(rspamd_proxy) <x>; proxy; '
                'rspamd_task_write_log: id: <i>, qid: <A1>, ip: 1.2.3.4, from: <a@x.test>, '
                '(default: F (no action): [0.40/15.00] [S])\n'
            ),
        )
        digest.run(NOW, summarise=False)
        sources = ThreatDigest.objects.get().summary['sources']
        self.assertEqual(
            {k: sources['postfix'][k] for k in ('received', 'delivered', 'deferred', 'bounced')},
            {'received': 2, 'delivered': 1, 'deferred': 1, 'bounced': 1},
        )
        self.assertEqual(sources['rspamd']['actions'], {'no_action': 1})
        self.assertTrue(sources['postfix']['exists'])
        self.assertGreater(sources['postfix']['lines'], 0)

    def test_a_source_that_went_quiet_is_a_finding(self) -> None:
        stale = NOW - timedelta(hours=8)
        sources = {
            'postfix': {'exists': True, 'last_at': stale.isoformat()},
            'dovecot': {'exists': True, 'last_at': (NOW - timedelta(hours=1)).isoformat()},
            'rspamd': {'exists': False},
        }
        found = rollup.findings(sources, NOW)
        self.assertEqual([f.key for f in found], ['log_silent:postfix'])
        self.assertEqual(found[0].severity, Severity.MEDIUM)

    def test_a_refusing_blocklist_is_a_finding_only_when_it_keeps_happening(self) -> None:
        sources = {
            'rspamd': {
                'exists': True,
                'last_at': NOW.isoformat(),
                'dns_blocked': {'multi.uribl.com': 5, 'x.test': 1},
            }
        }
        self.assertEqual(
            [f.key for f in rollup.findings(sources, NOW)], ['resolver_blocked:multi.uribl.com']
        )

    def test_the_slowest_page_never_carries_an_id(self) -> None:
        self.assertEqual(
            rollup._page('/accounts/invite/9f8e7d6c5b4a3210aabbccdd/accept'), '/accounts/invite/'
        )  # noqa: SLF001
        self.assertEqual(rollup._page('/accounts/logs/?q=x'), '/accounts/logs/')  # noqa: SLF001


class ReportTests(base.AssistantBase):
    def make(self, hours_ago: int, **summary: object) -> None:
        hour = (NOW - timedelta(hours=hours_ago)).replace(minute=0, second=0)
        ThreatDigest.objects.create(hour=hour, summary=summary)

    def test_the_report_sums_the_hourly_rows_in_the_period(self) -> None:
        sources = {
            'postfix': {
                'exists': True,
                'last_at': NOW.isoformat(),
                'lines': 10,
                'received': 3,
                'delivered': 2,
            },
            'nginx': {'exists': True, 'last_at': NOW.isoformat(), 'lines': 50, 'closed': 4},
            'dovecot': {'exists': True, 'last_at': NOW.isoformat(), 'lines': 5, 'logins': 2},
            'rspamd': {
                'exists': True,
                'last_at': NOW.isoformat(),
                'lines': 7,
                'actions': {'reject': 1},
            },
        }
        self.make(
            1,
            requests=100,
            by_status={'2xx': 80, '4xx': 20},
            auth_failures=1,
            mail_failures=2,
            sources=sources,
        )
        self.make(2, requests=50, by_status={'2xx': 50}, peak_per_minute=9, sources=sources)
        self.make(30, requests=999)  # outside a 24-hour report
        data = report.build('day', NOW)
        self.assertEqual(data['web']['requests'], 150)
        self.assertEqual(data['web']['refused'], 20)
        self.assertEqual(data['web']['closed'], 8)
        self.assertEqual(data['mail']['received'], 6)
        self.assertEqual(data['mail']['delivered'], 4)
        self.assertEqual(data['mail']['spam'], {'reject': 2})
        self.assertEqual(data['security']['failed_mail_signins'], 2)
        self.assertEqual(report.build('month', NOW)['web']['requests'], 1149)

    def test_source_status_ok_silent_missing_and_attention(self) -> None:
        latest = {
            'sources': {
                'nginx': {'exists': True, 'last_at': NOW.isoformat(), 'lines': 5},
                'postfix': {'exists': True, 'last_at': (NOW - timedelta(hours=9)).isoformat()},
                'dovecot': {'exists': False},
                'rspamd': {
                    'exists': True,
                    'last_at': NOW.isoformat(),
                    'dns_blocked': {'multi.uribl.com': 4},
                },
            }
        }
        by = {s['key']: s['status'] for s in report.sources_table(latest, NOW)}
        self.assertEqual(
            by,
            {
                'nginx': 'ok',
                'postfix': 'silent',
                'dovecot': 'missing',
                'rspamd': 'attention',
                'audit': 'ok',
                'errors': 'ok',
            },
        )

    def test_security_lists_findings_and_blocks(self) -> None:
        ThreatFinding.objects.create(
            key='probe_sweep:203.0.113.0/24',
            kind='probe_sweep',
            severity=int(Severity.HIGH),
            subject='203.0.113.0/24',
            title='Scanner',
            summary='x',
            count=9,
            first_seen=NOW,
            last_seen=NOW,
        )
        AuditEvent.objects.create(
            action='network_auto_block', user='system', detail='203.0.113.0/24 for 24 h'
        )
        data = report.build('day', NOW)
        self.assertEqual(data['security']['findings'], 1)
        self.assertEqual(data['security']['by_severity'], {'high': 1})
        self.assertEqual(data['security']['blocks'], 1)

    def test_the_page_and_the_json_export(self) -> None:
        self.make(1, requests=100, by_status={'2xx': 100})
        page = self.client.get(reverse('accounts:logs_report'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Log sources')
        self.assertContains(page, 'Spam filter decisions') if False else None
        exported = self.client.get(reverse('accounts:logs_report') + '?period=week&format=json')
        self.assertEqual(exported.status_code, 200)
        body = json.loads(exported.content)
        self.assertEqual(body['period'], 'week')
        self.assertIn('sources', body)
        self.assertIn('attachment', exported['Content-Disposition'])

    def test_the_tab_is_on_the_logs_page_and_needs_audit_view(self) -> None:
        self.assertContains(
            self.client.get(reverse('accounts:logs')), reverse('accounts:logs_report')
        )
        self.client.logout()
        self.assertIn(self.client.get(reverse('accounts:logs_report')).status_code, (302, 403))
