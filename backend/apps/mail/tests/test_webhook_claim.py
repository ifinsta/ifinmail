"""A delivery is sent by one worker at a time, and the sweep only queues work.

On a real worker the minute sweep used to send due deliveries itself, one after another, for as
long as the slowest endpoint took (226 s in one run, with no time limit), and it sent the rows a
queued chunk was about to send: 50 duplicate requests in a run of 300 deliveries. Now a worker
claims a delivery with one conditional UPDATE before sending it, and the sweep queues chunks
instead of sending.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

from backend.apps.mail import tasks
from backend.apps.mail.models import WebhookDelivery
from backend.apps.mail.services import webhooks
from backend.apps.mail.tests.test_webhook_publishing import PublishingBase
from backend.config.celery import app


class ClaimTests(PublishingBase):
    def setUp(self) -> None:
        super().setUp()
        webhooks.emit_many(self.events(3))
        self.delay.reset_mock()
        self.ids = self.ids_for(self.fast)

    def stored(self, pk: str) -> WebhookDelivery:
        return WebhookDelivery.objects.get(pk=pk)

    def test_a_claim_takes_a_due_delivery_for_a_while(self) -> None:
        claimed = webhooks._claim(self.ids[0])
        self.assertIsNotNone(claimed)
        row = self.stored(self.ids[0])
        self.assertEqual(row.status, WebhookDelivery.PENDING)
        self.assertEqual(row.attempts, 0)  # claiming is not an attempt
        lease = row.next_attempt_at - timezone.now()
        self.assertGreater(lease, timedelta(seconds=webhooks.CLAIM_SECONDS - 5))
        self.assertLessEqual(lease, timedelta(seconds=webhooks.CLAIM_SECONDS))

    def test_a_second_claim_fails_while_the_first_holds_it(self) -> None:
        self.assertIsNotNone(webhooks._claim(self.ids[0]))
        self.assertIsNone(webhooks._claim(self.ids[0]))
        self.assertFalse(webhooks.deliver(self.ids[0]))
        self.assertEqual(self.receiver.calls, [])  # nobody sent while it was held

    def test_a_delivery_asked_for_again_while_it_is_being_sent_is_not_sent_twice(self) -> None:
        inner: list[bool] = []

        def post(url: str, body: bytes, headers: dict) -> int:
            inner.append(webhooks.deliver(self.ids[0]))  # another worker, mid-request
            return 200

        with patch.object(webhooks, '_post', side_effect=post):
            self.assertTrue(webhooks.deliver(self.ids[0]))
        self.assertEqual(inner, [False])
        self.assertEqual(self.stored(self.ids[0]).status, WebhookDelivery.DELIVERED)

    def test_a_chunk_and_the_sweep_holding_the_same_rows_send_each_once(self) -> None:
        # The failure seen on a real worker: the rows were queued in a chunk and the sweep found
        # them due too. Both are run here, in either order; every row goes out exactly once.
        webhooks.emit_many(self.events(5, prefix='x'))
        webhooks.sweep()
        messages = [call.args[0] for call in self.delay.call_args_list]
        self.assertGreaterEqual(len(messages), 4)  # the emit's chunks and the sweep's
        for ids in [*messages[::2], *messages[1::2]]:
            webhooks.deliver_batch(ids)
        total = WebhookDelivery.objects.count()
        posts = [(url, headers['X-Ifinmail-Event-Id']) for url, _, headers in self.receiver.calls]
        self.assertEqual(len(posts), total)  # one request per delivery
        self.assertEqual(len(set(posts)), total)  # and none of them a repeat
        delivered = WebhookDelivery.objects.filter(status=WebhookDelivery.DELIVERED)
        self.assertEqual(delivered.count(), total)

    def test_an_abandoned_claim_expires_and_the_sweep_queues_the_delivery_again(self) -> None:
        webhooks._claim(self.ids[0])  # a worker took it and died
        self.delay.reset_mock()
        queued_now = webhooks.sweep()
        self.assertEqual(queued_now, 5)  # the other five rows; this one is claimed, not due
        WebhookDelivery.objects.filter(pk=self.ids[0]).update(
            next_attempt_at=timezone.now() - timedelta(seconds=1)  # the claim has run out
        )
        self.delay.reset_mock()
        self.assertEqual(webhooks.sweep(), 6)
        queued = [i for call in self.delay.call_args_list for i in call.args[0]]
        self.assertIn(self.ids[0], queued)
        self.assertTrue(webhooks.deliver(self.ids[0]))

    def test_deliveries_that_are_not_due_or_are_finished_cannot_be_claimed(self) -> None:
        WebhookDelivery.objects.filter(pk=self.ids[0]).update(
            next_attempt_at=timezone.now() + timedelta(hours=1)
        )
        WebhookDelivery.objects.filter(pk=self.ids[1]).update(status=WebhookDelivery.DELIVERED)
        self.assertIsNone(webhooks._claim(self.ids[0]))
        self.assertIsNone(webhooks._claim(self.ids[1]))
        self.assertIsNone(webhooks._claim(str(uuid.uuid4())))
        self.assertFalse(webhooks.deliver(str(uuid.uuid4())))

    def test_the_outcome_replaces_the_claim(self) -> None:
        with patch.object(webhooks, 'CLAIM_SECONDS', 5):
            self.assertTrue(webhooks.deliver(self.ids[0]))
            done = self.stored(self.ids[0])
            self.assertEqual((done.status, done.next_attempt_at), ('delivered', None))
            self.receiver.status = 500
            self.assertFalse(webhooks.deliver(self.ids[1]))
        retry = self.stored(self.ids[1])
        self.assertEqual((retry.status, retry.attempts), (WebhookDelivery.PENDING, 1))
        wait = retry.next_attempt_at - timezone.now()
        self.assertGreater(wait, timedelta(seconds=webhooks.BACKOFF[0] - 5))  # backoff, not 5 s

    def test_the_claim_outlasts_an_attempt(self) -> None:
        self.assertGreaterEqual(webhooks.CLAIM_SECONDS, webhooks.TIMEOUT_SECONDS + 30)


class SweepTests(PublishingBase):
    def setUp(self) -> None:
        super().setUp()
        webhooks.emit_many(self.events(3))
        self.delay.reset_mock()

    def queued(self) -> list[str]:
        return [i for call in self.delay.call_args_list for i in call.args[0]]

    def test_it_queues_what_is_due_and_sends_nothing_itself(self) -> None:
        with patch.object(webhooks, '_post', side_effect=AssertionError('the sweep sent')):
            self.assertEqual(webhooks.sweep(), 6)
        self.assertEqual(self.delay.call_count, 2)  # one chunk per endpoint
        everything = {str(pk) for pk in WebhookDelivery.objects.values_list('pk', flat=True)}
        self.assertEqual(set(self.queued()), everything)

    def test_it_leaves_alone_what_is_finished_or_not_yet_due(self) -> None:
        ids = self.ids_for(self.fast)
        WebhookDelivery.objects.filter(pk=ids[0]).update(status=WebhookDelivery.DELIVERED)
        WebhookDelivery.objects.filter(pk=ids[1]).update(
            next_attempt_at=timezone.now() + timedelta(minutes=5)
        )
        self.assertEqual(webhooks.sweep(), 4)
        self.assertNotIn(ids[0], self.queued())
        self.assertNotIn(ids[1], self.queued())

    def test_it_queues_in_the_same_chunks_as_new_deliveries(self) -> None:
        WebhookDelivery.objects.all().delete()
        webhooks.emit_many(self.events(60, prefix='b'))
        self.delay.reset_mock()
        self.assertEqual(webhooks.sweep(), 120)
        endpoint_of = dict(WebhookDelivery.objects.values_list('pk', 'endpoint_id'))
        order = [endpoint_of[uuid.UUID(call.args[0][0])] for call in self.delay.call_args_list]
        self.assertEqual(len(order), 6)  # 25 + 25 + 10 for each endpoint
        for first, second in zip(order, order[1:], strict=False):
            self.assertNotEqual(first, second)  # round-robin, never one endpoint's run
        for call in self.delay.call_args_list:
            self.assertLessEqual(len(call.args[0]), webhooks.DELIVERY_CHUNK)

    def test_it_queues_at_most_its_limit(self) -> None:
        self.assertEqual(webhooks.sweep(limit=4), 4)
        self.assertEqual(len(self.queued()), 4)

    def test_it_still_forgets_old_finished_deliveries_but_keeps_pending_ones(self) -> None:
        ids = self.ids_for(self.fast)
        old = timezone.now() - timedelta(days=webhooks.KEEP_DAYS + 1)
        WebhookDelivery.objects.filter(pk__in=ids[:2]).update(
            created_at=old, status=WebhookDelivery.DELIVERED
        )
        WebhookDelivery.objects.filter(pk=ids[2]).update(created_at=old)  # still pending
        webhooks.sweep()
        remaining = set(WebhookDelivery.objects.values_list('pk', flat=True))
        self.assertFalse({uuid.UUID(i) for i in ids[:2]} & remaining)
        self.assertIn(uuid.UUID(ids[2]), remaining)

    def test_a_broker_failure_while_queuing_does_not_raise(self) -> None:
        self.delay.side_effect = RuntimeError('broker down')
        self.assertEqual(webhooks.sweep(), 6)  # the next sweep tries again

    def test_the_sweep_task_has_time_limits(self) -> None:
        task = app.tasks['mail.sweep_webhooks']
        self.assertEqual(task.soft_time_limit, tasks.SCAN_SOFT_TIME_LIMIT)
        self.assertEqual(task.time_limit, tasks.SCAN_TIME_LIMIT)
