"""The delivery-event scan does its work in bulk, and gets the same answers as line by line.

One scan of a busy Postfix log used to make about 30,000 cache round trips and 40,000 queries (a
queue-id lookup, a message lookup, a policy lookup, an endpoint query and three statements per
endpoint, for every line). These tests pin the bulk shape: a few cache reads and writes, a
constant number of queries whatever the number of events, nothing lost when a read is cut short,
and the same events, counters and suppressions the per-line path produces.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.db import connection
from django.test.utils import CaptureQueriesContext

from backend.apps.core.plugins.services import InstallationService
from backend.apps.mail.models import Suppression, WebhookDelivery
from backend.apps.mail.services import compliance, delivery_events, webhooks
from backend.apps.mail.tests import test_delivery_events as delivery_tests

STOP = SoftTimeLimitExceeded
PREFIX = 'abc123'
SENDER = 'ana@example.com'


def cleanup(qid: str, mid: str) -> str:
    return f'Oct 15 09:00:00 mail postfix/cleanup[11]: {qid}: message-id=<{mid}>'


def status(
    qid: str, to: str, kind: str = 'sent', dsn: str = '2.0.0', detail: str = '250 OK'
) -> str:
    return (
        f'Oct 15 09:00:01 mail postfix/smtp[12]: {qid}: to=<{to}>, '
        f'relay=mx.example.org[198.51.100.1]:25, delay=1, dsn={dsn}, status={kind} ({detail})'
    )


def noise(n: int) -> list[str]:
    return [
        f'Oct 15 09:00:00 mail postfix/smtpd[9]: connect from host{i}.example.net' for i in range(n)
    ]


class CountingCache:
    """Wraps the cache and counts every call by method name (one call is one round trip)."""

    def __init__(self, inner) -> None:  # noqa: ANN001
        self._inner = inner
        self.calls: dict[str, int] = {}

    def __getattr__(self, name: str):  # noqa: ANN204
        target = getattr(self._inner, name)
        if not callable(target):
            return target

        def counted(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            self.calls[name] = self.calls.get(name, 0) + 1
            return target(*args, **kwargs)

        return counted


class EmitManyTests(delivery_tests.EventsBase):
    def setUp(self) -> None:
        super().setUp()
        self.enable()
        self.console, _ = self.endpoint(name='console')
        self.owned, _ = self.endpoint(name='owned', owner_prefix=PREFIX)

    def events(self, n: int, prefix: str = PREFIX) -> list[webhooks.Event]:
        return [
            webhooks.Event(
                'message.delivered', {'n': i}, key_prefix=prefix, event_id=f'evt_{prefix}{i}'
            )
            for i in range(n)
        ]

    def test_every_event_reaches_the_endpoints_that_want_it(self) -> None:
        mixed = self.events(3) + self.events(2, prefix='other9')
        self.assertEqual(webhooks.emit_many(mixed), 3 * 2 + 2 * 1)  # "owned" only hears its own
        self.assertEqual(WebhookDelivery.objects.filter(endpoint=self.console).count(), 5)
        self.assertEqual(WebhookDelivery.objects.filter(endpoint=self.owned).count(), 3)

    def test_events_already_queued_are_skipped_and_a_repeat_within_a_batch_counts_once(
        self,
    ) -> None:
        batch = self.events(4)
        self.assertEqual(webhooks.emit_many(batch + batch[:2]), 4 * 2)
        self.assertEqual(webhooks.emit_many(batch), 0)
        self.assertEqual(WebhookDelivery.objects.count(), 8)

    def test_the_payload_is_the_one_emit_builds(self) -> None:
        webhooks.emit_many([webhooks.Event('message.bounced', {'k': 'v'}, event_id='evt_x1')])
        row = WebhookDelivery.objects.get(endpoint=self.console)
        self.assertEqual(row.payload['id'], 'evt_x1')
        self.assertEqual(row.payload['type'], 'message.bounced')
        self.assertEqual(row.payload['data'], {'k': 'v'})
        self.assertEqual(row.status, WebhookDelivery.PENDING)
        self.assertIsNotNone(row.created_at)  # auto_now_add still applies to a bulk insert

    def test_it_costs_the_same_number_of_queries_for_any_number_of_events(self) -> None:
        with CaptureQueriesContext(connection) as few:
            webhooks.emit_many(self.events(5, prefix='few001'))
        with CaptureQueriesContext(connection) as many:
            webhooks.emit_many(self.events(250, prefix='many01'))
        # About 9 queries per event before: 250 events was ~2,250. The insert is chunked (the
        # database's variable limit decides how finely), so allow a few more statements, not 9 each.
        self.assertLess(len(few), 15)
        self.assertLess(len(many), 25)

    def test_nothing_is_queued_when_the_plugin_is_off(self) -> None:
        InstallationService.uninstall(delivery_tests.PLUGIN, 'a')
        self.assertEqual(webhooks.emit_many(self.events(3)), 0)
        self.assertEqual(webhooks.emit_many([]), 0)
        self.assertFalse(WebhookDelivery.objects.exists())

    def test_all_new_deliveries_are_scheduled_together_once_they_exist(self) -> None:
        with patch.object(webhooks, '_schedule') as schedule:
            made = webhooks.emit_many(self.events(3))
        schedule.assert_called_once()  # one call for the batch, not one per delivery
        scheduled = schedule.call_args.args[0]
        self.assertEqual(len(scheduled), made)
        stored = set(WebhookDelivery.objects.values_list('pk', flat=True))
        self.assertEqual({d.pk for d in scheduled}, stored)

    def test_nothing_is_scheduled_when_nothing_is_new(self) -> None:
        webhooks.emit_many(self.events(2))
        with patch.object(webhooks, '_schedule') as schedule:
            self.assertEqual(webhooks.emit_many(self.events(2)), 0)
        schedule.assert_not_called()


class BatchedScanTests(delivery_tests.EventsBase):
    def setUp(self) -> None:
        super().setUp()
        self.enable()
        self.row, _ = self.endpoint()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'postfix.log'
        self.path.write_text('old line\n')
        patcher = patch.object(delivery_events, 'log_dir', return_value=Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        delivery_events.scan()  # a fresh install starts at the end of the log

    def remember(self, *mids: str, prefix: str = PREFIX, sender: str = SENDER) -> None:
        from django.core.cache import cache

        for mid in mids:
            cache.set(
                delivery_events._message_key(mid), {'key_prefix': prefix, 'sender': sender}, 3600
            )

    def append(self, lines: list[str]) -> None:
        with self.path.open('a') as handle:
            handle.write(''.join(f'{line}\n' for line in lines))

    def delivered_to(self) -> list[str]:
        rows = WebhookDelivery.objects.filter(endpoint=self.row, event_type='message.delivered')
        return sorted(rows.values_list('payload__data__recipient', flat=True))

    def test_a_status_resolves_through_a_cleanup_in_the_same_read(self) -> None:
        self.remember('m1@x', 'm2@x')
        self.append(
            [
                cleanup('Q1', 'm1@x'),
                cleanup('Q2', 'm2@x'),
                status('Q1', 'a@y.org'),
                status('Q2', 'b@y.org'),
            ]
        )
        self.assertEqual(delivery_events.scan(), 2)
        self.assertEqual(self.delivered_to(), ['a@y.org', 'b@y.org'])

    def test_the_link_is_remembered_for_a_later_read(self) -> None:
        self.remember('m1@x')
        self.append([cleanup('Q1', 'm1@x')])
        self.assertEqual(delivery_events.scan(), 0)
        self.append([status('Q1', 'a@y.org')])
        self.assertEqual(delivery_events.scan(), 1)
        self.assertEqual(self.delivered_to(), ['a@y.org'])

    def test_mail_that_was_not_sent_through_the_api_produces_nothing(self) -> None:
        self.append([cleanup('Q9', 'stranger@x'), status('Q9', 'a@y.org'), *noise(5)])
        self.assertEqual(delivery_events.scan(), 0)
        self.assertFalse(WebhookDelivery.objects.filter(event_type='message.delivered').exists())

    def test_a_whole_read_makes_a_handful_of_cache_calls_not_one_per_line(self) -> None:
        mids = [f'm{i}@x' for i in range(120)]
        self.remember(*mids)
        lines = noise(300)
        for i, mid in enumerate(mids):
            lines += [cleanup(f'Q{i}', mid), status(f'Q{i}', f'r{i}@y.org')]
        self.append(lines)
        counting = CountingCache(delivery_events.cache)
        with patch.object(delivery_events, 'cache', counting):
            self.assertEqual(delivery_events.scan(), 120)
        # The only single-key calls are the scan's own log-position bookkeeping, once per read.
        self.assertLessEqual(counting.calls.get('get', 0), 1)
        self.assertLessEqual(counting.calls.get('set', 0), 1)
        self.assertLessEqual(counting.calls.get('get_many', 0), 2)  # queue ids, then messages
        flushes = -(-len(lines) // delivery_events.FLUSH_EVERY)  # one write per FLUSH_EVERY lines
        self.assertLessEqual(counting.calls.get('set_many', 0), flushes)

    def test_the_database_work_does_not_grow_with_the_number_of_events(self) -> None:
        mids = [f'm{i}@x' for i in range(100)]
        self.remember(*mids)
        lines = []
        for i, mid in enumerate(mids):
            lines += [cleanup(f'Q{i}', mid), status(f'Q{i}', f'r{i}@y.org')]
        self.append(lines)
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(delivery_events.scan(), 100)
        self.assertLess(len(queries), 30)  # about 9 queries per event before

    def test_counters_are_added_up_per_sender_and_bounces_share_one_settings_lookup(self) -> None:
        InstallationService.install('sender-compliance', {}, 'a')
        self.remember('m1@x', 'm2@x', 'm3@x', prefix='abc123')
        self.remember('n1@x', prefix='zzz999')
        lines = [cleanup(f'Q{i}', mid) for i, mid in enumerate(['m1@x', 'm2@x', 'm3@x', 'n1@x'])]
        lines += [
            status('Q0', 'a@y.org'),
            status('Q1', 'b@y.org'),
            status('Q2', 'gone@y.org', 'bounced', '5.1.1', '550 5.1.1 User unknown'),
            status('Q3', 'c@y.org'),
        ]
        self.append(lines)
        with (
            patch.object(compliance, 'count', wraps=compliance.count) as count,
            patch.object(compliance, 'note_bounce', wraps=compliance.note_bounce) as bounce,
        ):
            delivery_events.scan()
        totals = {call.args[0]: call.kwargs for call in count.call_args_list}
        self.assertEqual(totals['abc123'], {'delivered': 2, 'bounced': 1})
        self.assertEqual(totals['zzz999'], {'delivered': 1, 'bounced': 0})
        self.assertEqual(count.call_count, 2)  # once per sender, not once per line
        self.assertEqual(bounce.call_count, 1)
        self.assertIsNotNone(bounce.call_args.kwargs['current'])
        self.assertTrue(Suppression.objects.filter(address='gone@y.org').exists())

    def test_a_cache_failure_while_looking_up_loses_nothing(self) -> None:
        self.remember('m1@x')
        self.append([cleanup('Q1', 'm1@x'), status('Q1', 'a@y.org')])
        with (
            patch.object(
                delivery_events.cache, 'get_many', side_effect=ConnectionError('redis down')
            ),
            self.assertRaises(ConnectionError),
        ):
            delivery_events.scan()
        self.assertFalse(WebhookDelivery.objects.filter(event_type='message.delivered').exists())
        self.assertEqual(delivery_events.scan(), 1)  # the same lines are read again
        self.assertEqual(self.delivered_to(), ['a@y.org'])

    def test_what_was_handled_is_written_every_so_many_lines(self) -> None:
        mids = [f'm{i}@x' for i in range(6)]
        self.remember(*mids)
        lines = []
        for i, mid in enumerate(mids):
            lines += [cleanup(f'Q{i}', mid), status(f'Q{i}', f'r{i}@y.org')]
        self.append(lines)
        with (
            patch.object(delivery_events, 'FLUSH_EVERY', 4),
            patch.object(webhooks, 'emit_many', wraps=webhooks.emit_many) as emit_many,
        ):
            self.assertEqual(delivery_events.scan(), 6)
        self.assertGreaterEqual(emit_many.call_count, 3)  # 12 lines, a write every 4
        self.assertEqual(len(self.delivered_to()), 6)

    def test_a_stop_writes_what_was_handled_before_the_position_goes_back(self) -> None:
        self.remember('m1@x', 'm2@x')
        self.append(
            [
                cleanup('Q1', 'm1@x'),
                status('Q1', 'a@y.org'),
                cleanup('Q2', 'm2@x'),
                status('Q2', 'b@y.org'),
            ]
        )
        real = delivery_events.handle_line
        calls: list[int] = []

        def stops_on_the_third(line: str, ctx=None) -> int:  # noqa: ANN001
            calls.append(1)
            if len(calls) == 3:
                raise STOP()
            return real(line, ctx)

        with (
            patch.object(delivery_events, 'handle_line', stops_on_the_third),
            self.assertRaises(STOP),
        ):
            delivery_events.scan()
        self.assertEqual(self.delivered_to(), ['a@y.org'])  # written, not dropped with the batch
        self.assertEqual(delivery_events.scan(), 1)  # the rest is finished by the next read
        self.assertEqual(self.delivered_to(), ['a@y.org', 'b@y.org'])

    def test_a_failed_batch_falls_back_to_one_event_at_a_time(self) -> None:
        self.remember('m1@x', 'm2@x', 'm3@x')
        self.append(
            [cleanup(f'Q{i}', f'm{i}@x') for i in (1, 2, 3)]
            + [status(f'Q{i}', f'r{i}@y.org') for i in (1, 2, 3)]
        )
        real_emit_many = webhooks.emit_many

        def fails_for_a_batch(events):  # noqa: ANN001, ANN202
            if len(events) > 1:
                raise RuntimeError('the bulk insert failed')
            return real_emit_many(events)

        with patch.object(webhooks, 'emit_many', fails_for_a_batch):
            self.assertEqual(delivery_events.scan(), 3)
        self.assertEqual(self.delivered_to(), ['r1@y.org', 'r2@y.org', 'r3@y.org'])

    def test_one_event_that_cannot_be_queued_does_not_cost_the_others(self) -> None:
        self.remember('m1@x', 'm2@x', 'm3@x')
        self.append(
            [cleanup(f'Q{i}', f'm{i}@x') for i in (1, 2, 3)]
            + [status(f'Q{i}', f'r{i}@y.org') for i in (1, 2, 3)]
        )
        real_emit_many = webhooks.emit_many

        def fails_for_one(events):  # noqa: ANN001, ANN202
            if len(events) > 1 or events[0].data['recipient'] == 'r2@y.org':
                raise RuntimeError('this one is bad')
            return real_emit_many(events)

        with patch.object(webhooks, 'emit_many', fails_for_one):
            self.assertEqual(delivery_events.scan(), 2)
        self.assertEqual(self.delivered_to(), ['r1@y.org', 'r3@y.org'])
