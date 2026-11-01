"""Webhook deliveries are published to the workers in chunks, one endpoint per chunk.

A busy minute queued one broker message per delivery (about 0.4 ms each, over 3 seconds for 8,000
deliveries). Now deliveries to one endpoint travel together, 25 to a task. Because a chunk is
worked through one delivery after another, it is per endpoint (so a slow or dead endpoint only
slows its own deliveries) and it stops after a time budget, handing the rest back to the queue.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.db import transaction
from django.test import SimpleTestCase

from backend.apps.mail import tasks
from backend.apps.mail.models import WebhookDelivery
from backend.apps.mail.services import webhooks
from backend.apps.mail.tests import test_delivery_events as delivery_tests
from backend.config.celery import app

# The shared test base replaces _schedule with a mock; these tests want the real one.
REAL_SCHEDULE = webhooks._schedule


def fake(endpoint: str, n: int) -> list[SimpleNamespace]:
    return [SimpleNamespace(endpoint_id=endpoint, pk=f'{endpoint}{i}') for i in range(n)]


class ChunkTests(SimpleTestCase):
    def test_grouped_by_endpoint_capped_in_size_and_every_id_exactly_once(self) -> None:
        # Interleaved on purpose: the endpoints arrive mixed, as events are processed in order.
        mixed = [d for pair in zip(fake('A', 60), fake('B', 60), strict=True) for d in pair]
        mixed += fake('C', 3)
        chunks = webhooks._chunks(mixed)
        self.assertEqual(sorted(len(c) for c in chunks), [3, 10, 10, 25, 25, 25, 25])
        for chunk in chunks:
            self.assertEqual(len({i[0] for i in chunk}), 1, 'a chunk mixes endpoints')
            self.assertLessEqual(len(chunk), webhooks.DELIVERY_CHUNK)
        flat = [i for c in chunks for i in c]
        self.assertEqual(sorted(flat), sorted(str(d.pk) for d in mixed))
        a_ids = [i for c in chunks for i in c if i.startswith('A')]
        self.assertEqual(a_ids, [f'A{i}' for i in range(60)])  # order within an endpoint is kept

    def test_nothing_gives_no_chunks(self) -> None:
        self.assertEqual(webhooks._chunks([]), [])


class PublishingBase(delivery_tests.EventsBase):
    def setUp(self) -> None:
        super().setUp()
        self.enable()
        patcher = patch.object(webhooks, '_schedule', REAL_SCHEDULE)
        patcher.start()
        self.addCleanup(patcher.stop)
        # The test settings run Celery eagerly, so a real publish would deliver on the spot.
        publisher = patch.object(tasks.deliver_webhooks, 'delay')
        self.delay = publisher.start()
        self.addCleanup(publisher.stop)
        self.fast, _ = self.endpoint(name='fast', url='https://fast.example.com/in')
        self.slow, _ = self.endpoint(name='slow', url='https://slow.example.com/in')

    def events(self, n: int, prefix: str = 'p') -> list[webhooks.Event]:
        return [
            webhooks.Event('message.delivered', {'i': i}, event_id=f'evt_{prefix}{i}')
            for i in range(n)
        ]

    def ids_for(self, endpoint) -> list[str]:  # noqa: ANN001
        rows = WebhookDelivery.objects.filter(endpoint=endpoint).order_by('event_id')
        return [str(pk) for pk in rows.values_list('pk', flat=True)]


class PublishingTests(PublishingBase):
    def test_a_busy_batch_is_a_few_broker_messages_not_one_per_delivery(self) -> None:
        made = webhooks.emit_many(self.events(60))
        self.assertEqual(made, 120)  # 60 events to each of two endpoints
        self.assertEqual(self.delay.call_count, 2 * 3)  # per endpoint: 25 + 25 + 10
        endpoint_of = dict(WebhookDelivery.objects.values_list('pk', 'endpoint_id'))
        sent: list[str] = []
        for call in self.delay.call_args_list:
            ids = call.args[0]
            self.assertEqual(len({endpoint_of[uuid.UUID(i)] for i in ids}), 1)
            sent += ids
        self.assertEqual(sorted(sent), sorted(str(pk) for pk in endpoint_of))

    def test_nothing_is_published_until_the_transaction_commits(self) -> None:
        with transaction.atomic():
            webhooks.emit_many(self.events(3))
            self.delay.assert_not_called()  # the rows are not visible to a worker yet
        self.assertEqual(self.delay.call_count, 2)  # then one chunk per endpoint

    def test_a_rolled_back_batch_publishes_nothing(self) -> None:
        with self.assertRaises(RuntimeError), transaction.atomic():
            webhooks.emit_many(self.events(3))
            raise RuntimeError('the surrounding work failed')
        self.delay.assert_not_called()
        self.assertFalse(WebhookDelivery.objects.exists())

    def test_a_broker_failure_loses_nothing_the_sweep_will_find_it(self) -> None:
        self.delay.side_effect = [RuntimeError('broker down'), None]
        webhooks.emit_many(self.events(3))
        self.assertEqual(self.delay.call_count, 2)  # the second chunk was still tried
        due = WebhookDelivery.objects.filter(status=WebhookDelivery.PENDING)
        self.assertEqual(due.count(), 6)  # every row is pending and due, for the sweep

    def test_the_sweep_still_delivers_what_was_never_published(self) -> None:
        webhooks.emit_many(self.events(3))
        self.assertEqual(webhooks.sweep(), 6)
        delivered = WebhookDelivery.objects.filter(status=WebhookDelivery.DELIVERED)
        self.assertEqual(delivered.count(), 6)


class DeliverBatchTests(PublishingBase):
    def setUp(self) -> None:
        super().setUp()
        webhooks.emit_many(self.events(5))
        self.delay.reset_mock()
        self.ids = self.ids_for(self.fast)

    def status_of(self, ids: list[str]) -> list[str]:
        return [WebhookDelivery.objects.get(pk=i).status for i in ids]

    def test_each_delivery_in_the_chunk_is_made_in_turn(self) -> None:
        self.assertEqual(webhooks.deliver_batch(self.ids), 5)
        self.assertEqual(set(self.status_of(self.ids)), {WebhookDelivery.DELIVERED})
        self.assertEqual(len(self.receiver.calls), 5)

    def test_a_failing_delivery_does_not_stop_the_rest_and_is_retried_later(self) -> None:
        self.receiver.status = 500
        self.assertEqual(webhooks.deliver_batch(self.ids), 0)
        self.assertEqual(len(self.receiver.calls), 5)  # all five were tried
        for pk in self.ids:
            row = WebhookDelivery.objects.get(pk=pk)
            self.assertEqual((row.status, row.attempts), (WebhookDelivery.PENDING, 1))
            self.assertIsNotNone(row.next_attempt_at)  # rescheduled by the usual backoff

    def test_ids_that_are_gone_or_already_done_are_skipped(self) -> None:
        webhooks.deliver(self.ids[0])
        ids = [str(uuid.uuid4()), *self.ids]  # one that never existed (a lost duplicate insert)
        self.assertEqual(webhooks.deliver_batch(ids), 4)
        self.assertEqual(len(self.receiver.calls), 5)  # the first was not sent twice

    def test_when_the_budget_is_spent_the_rest_goes_back_on_the_queue(self) -> None:
        clock = iter([0, 100]).__next__  # started at 0; second delivery finds 100 s have passed
        self.assertEqual(webhooks.deliver_batch(self.ids, clock=clock), 1)
        self.delay.assert_called_once_with(self.ids[1:])
        self.assertEqual(
            self.status_of(self.ids),
            [WebhookDelivery.DELIVERED] + [WebhookDelivery.PENDING] * 4,
        )

    def test_within_budget_nothing_is_requeued(self) -> None:
        webhooks.deliver_batch(self.ids)
        self.delay.assert_not_called()

    def test_failing_to_requeue_is_logged_and_the_sweep_covers_it(self) -> None:
        clock = iter([0, 100]).__next__
        self.delay.side_effect = RuntimeError('down')
        webhooks.deliver_batch(self.ids, clock=clock)  # must not raise
        self.assertEqual(self.status_of(self.ids[1:]), [WebhookDelivery.PENDING] * 4)

    def test_one_dead_endpoint_does_not_hold_up_another(self) -> None:
        def post(url: str, body: bytes, headers: dict) -> int:
            if 'slow.example.com' in url:
                raise TimeoutError('timed out')
            return 200

        everything = list(WebhookDelivery.objects.select_related('endpoint'))
        with patch.object(webhooks, '_post', side_effect=post):
            for chunk in webhooks._chunks(everything):
                webhooks.deliver_batch(chunk)
        fast = WebhookDelivery.objects.filter(endpoint=self.fast)
        slow = WebhookDelivery.objects.filter(endpoint=self.slow)
        self.assertEqual(set(fast.values_list('status', flat=True)), {WebhookDelivery.DELIVERED})
        self.assertEqual(set(slow.values_list('status', flat=True)), {WebhookDelivery.PENDING})
        self.assertIn('TimeoutError', slow.first().last_error)


class TaskTests(SimpleTestCase):
    def test_the_batch_task_is_registered_and_the_old_one_still_is(self) -> None:
        self.assertIn('mail.deliver_webhooks', app.tasks)
        self.assertIn('mail.deliver_webhook', app.tasks)  # messages already queued still run

    def test_a_slow_endpoint_cannot_hold_a_worker_for_long(self) -> None:
        # The budget is the time-slice a slow or dead endpoint gets before others have a turn.
        # On a real worker (4 processes, an endpoint answering in 3 s) 60 s left the others
        # waiting 61 s; 15 s kept it to 16 s. Raising it brings the stall back.
        self.assertLessEqual(webhooks.BATCH_BUDGET_SECONDS, 15)
        held = webhooks.BATCH_BUDGET_SECONDS + webhooks.TIMEOUT_SECONDS
        self.assertLessEqual(held, 30)  # budget plus the one attempt that can overrun it

    def test_the_time_limits_sit_above_the_budget_plus_one_attempt(self) -> None:
        task = app.tasks['mail.deliver_webhooks']
        one_attempt = webhooks.TIMEOUT_SECONDS + 20  # the post, a DNS check and the writes
        self.assertGreaterEqual(task.soft_time_limit, webhooks.BATCH_BUDGET_SECONDS + one_attempt)
        self.assertGreaterEqual(task.time_limit - task.soft_time_limit, 15)

    def test_the_task_hands_the_chunk_to_the_service(self) -> None:
        with patch.object(webhooks, 'deliver_batch', return_value=3) as batch:
            self.assertEqual(tasks.deliver_webhooks(['a', 'b', 'c']), 3)
        batch.assert_called_once_with(['a', 'b', 'c'])

    def test_the_old_single_delivery_task_still_delivers_one(self) -> None:
        with patch.object(webhooks, 'deliver', return_value=True) as deliver:
            self.assertTrue(tasks.deliver_webhook('abc'))
        deliver.assert_called_once_with('abc')
