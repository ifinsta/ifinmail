"""The scan jobs run under Celery time limits, and stopping one early loses nothing.

Mail and log lines are written by strangers, so a scan that hangs must not hold a worker for
good. The soft limit raises ``SoftTimeLimitExceeded`` inside the task; the services must let it
through (they catch ``Exception`` around each mailbox and each log line) and must leave their
position where the next run can finish the job.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.test import SimpleTestCase

from backend.apps.mail import tasks
from backend.apps.mail.models import WebhookDelivery
from backend.apps.mail.services import delivery_events, inbox_events
from backend.apps.mail.tests import test_delivery_events as delivery_tests
from backend.apps.mail.tests import test_inbox_webhooks as inbox_tests
from backend.apps.mail.tests.fake_imap import message
from backend.config.celery import app

STOP = SoftTimeLimitExceeded


class TaskLimitTests(SimpleTestCase):
    def scan_tasks(self) -> list:
        names = sorted(name for name in app.tasks if name.startswith('mail.scan_'))
        return [app.tasks[name] for name in names]

    def test_every_scan_task_has_a_soft_and_a_hard_limit(self) -> None:
        found = self.scan_tasks()
        self.assertGreaterEqual(len(found), 2, 'the scan tasks were not registered')
        for task in found:
            with self.subTest(task=task.name):
                self.assertEqual(task.soft_time_limit, tasks.SCAN_SOFT_TIME_LIMIT)
                self.assertEqual(task.time_limit, tasks.SCAN_TIME_LIMIT)

    def test_the_soft_limit_comes_first_and_leaves_room_to_stop_cleanly(self) -> None:
        self.assertLess(tasks.SCAN_SOFT_TIME_LIMIT, tasks.SCAN_TIME_LIMIT)
        self.assertGreaterEqual(tasks.SCAN_TIME_LIMIT - tasks.SCAN_SOFT_TIME_LIMIT, 15)

    def test_a_soft_stop_is_reported_as_one_and_the_task_ends_normally(self) -> None:
        for task, module in (
            (tasks.scan_inbox_events, inbox_events),
            (tasks.scan_delivery_events, delivery_events),
        ):
            with (
                self.subTest(task=task.name),
                patch.object(module, 'scan', side_effect=STOP()),
                self.assertLogs('backend', 'WARNING') as logged,
            ):
                self.assertEqual(task(), 0)
            output = ' '.join(logged.output)
            self.assertIn('time limit', output)
            self.assertNotIn('failed', output)


class InboxScanStopTests(inbox_tests.InboxEventsBase):
    def test_the_soft_stop_is_not_swallowed_by_the_per_mailbox_handler(self) -> None:
        self.watch()
        with (
            patch.object(inbox_events, 'scan_mailbox', side_effect=STOP()),
            self.assertRaises(STOP),
        ):
            inbox_events.scan()

    def test_an_ordinary_failure_still_skips_just_that_mailbox(self) -> None:
        self.watch()
        with patch.object(inbox_events, 'scan_mailbox', side_effect=RuntimeError('boom')):
            self.assertEqual(inbox_events.scan(), 0)

    def test_a_scan_stopped_part_way_is_finished_by_the_next_without_repeats(self) -> None:
        row = self.watch()
        inbox_events.scan()  # baseline
        box = inbox_tests.BOX
        self.store.deliver(box, message('First', 'one', to=box))
        self.store.deliver(box, message('Second', 'two', to=box))
        real = inbox_events.event_for
        calls: list[int] = []

        def stops_on_the_second(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            calls.append(1)
            if len(calls) == 2:
                raise STOP()
            return real(*args, **kwargs)

        with (
            patch.object(inbox_events, 'event_for', stops_on_the_second),
            self.assertRaises(STOP),
        ):
            inbox_events.scan()
        deliveries = WebhookDelivery.objects.filter(endpoint=row)
        self.assertEqual(deliveries.count(), 1)
        inbox_events.scan()
        subjects = sorted(deliveries.values_list('payload__data__subject', flat=True))
        self.assertEqual(subjects, ['First', 'Second'])  # the first was read again, not repeated


class DeliveryScanStopTests(delivery_tests.EventsBase):
    def setUp(self) -> None:
        super().setUp()
        self.enable()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'postfix.log'
        self.path.write_text('old line\n')
        patcher = patch.object(delivery_events, 'log_dir', return_value=Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        delivery_events.scan()  # a fresh install starts at the end of the log

    def append(self, *lines: str) -> None:
        with self.path.open('a') as handle:
            handle.write(''.join(f'{line}\n' for line in lines))

    def seen_by_the_next_scan(self) -> list[str]:
        seen: list[str] = []

        def record(line: str) -> int:
            seen.append(line)
            return 0

        with patch.object(delivery_events, 'handle_line', side_effect=record):
            delivery_events.scan()
        return seen

    def stopped_scan(self, side_effect: list | Exception) -> None:
        with (
            patch.object(delivery_events, 'handle_line', side_effect=side_effect),
            self.assertRaises(STOP),
        ):
            delivery_events.scan()

    def test_the_soft_stop_is_not_swallowed_by_the_per_line_handler(self) -> None:
        self.append('one')
        self.stopped_scan(STOP())

    def test_a_stop_part_way_puts_the_position_back_to_the_first_unhandled_line(self) -> None:
        self.append('alpha', 'bravo', 'charlie', 'delta')
        self.stopped_scan([0, 0, STOP()])
        # alpha and bravo were handled; charlie was in flight and delta never started.
        self.assertEqual(self.seen_by_the_next_scan(), ['charlie', 'delta'])
        self.assertEqual(self.seen_by_the_next_scan(), [])  # and then it is caught up

    def test_a_stop_before_the_first_line_loses_nothing(self) -> None:
        self.append('alpha', 'bravo')
        self.stopped_scan(STOP())
        self.assertEqual(self.seen_by_the_next_scan(), ['alpha', 'bravo'])

    def test_the_position_is_counted_in_bytes_not_characters(self) -> None:
        self.append('é' * 3 + ' one', 'two', 'three')  # a multi-byte line before the stop
        self.stopped_scan([0, STOP()])
        self.assertEqual(self.seen_by_the_next_scan(), ['two', 'three'])

    def test_a_line_that_fails_is_skipped_and_does_not_hold_the_rest(self) -> None:
        self.append('alpha', 'bravo')
        failing = [RuntimeError('bad line'), 0]
        with patch.object(delivery_events, 'handle_line', side_effect=failing) as handled:
            self.assertEqual(delivery_events.scan(), 0)
        self.assertEqual(handled.call_count, 2)
        self.assertEqual(self.seen_by_the_next_scan(), [])

    def test_lines_are_whole_records_split_on_newline_only(self) -> None:
        raw = b'crlf line\r\nplain\nsplit\xe2\x80\xa8here\nlast'
        self.path.write_bytes(self.path.read_bytes() + raw)
        self.assertEqual(
            delivery_events.read_new_lines(self.path),
            ['crlf line', 'plain', 'split here'],  # "last" waits for its newline
        )
