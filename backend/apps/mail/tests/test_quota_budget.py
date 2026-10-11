"""Quota budget — disk vs. promised space, warning threshold, edge cases."""

from unittest.mock import patch

from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.mail.services import MailboxService, QuotaService
from backend.apps.mail.types.quota import MB, QuotaBudget, human_bytes

GOOD = 'Correct-Horse-9'
GB = 1024 * MB


def _usage(total: int | None, free: int | None):
    """Patch ``shutil.disk_usage`` through the service's own inspection."""
    return patch(
        'backend.apps.mail.services.quota._disk_usage',
        return_value=(total, free),
    )


class QuotaServiceTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.make_domain()

    def test_counts_finite_quotas_and_unlimited_separately(self) -> None:
        MailboxService.create('ifinmail.test', 'one', GOOD, quota_bytes=GB)
        MailboxService.create('ifinmail.test', 'two', GOOD, quota_bytes=2 * GB)
        MailboxService.create('ifinmail.test', 'free', GOOD, quota_bytes=0)
        with _usage(10 * GB, 7 * GB):
            budget = QuotaService.get_budget()
        self.assertEqual(budget.allocated_bytes, 3 * GB)
        self.assertEqual(budget.mailbox_count, 3)
        self.assertEqual(budget.unlimited_count, 1)
        self.assertEqual(budget.headroom_bytes, 7 * GB)
        self.assertFalse(budget.overcommitted)
        self.assertEqual(budget.disk_free_bytes, 7 * GB)

    def test_overcommit_is_detected(self) -> None:
        MailboxService.create('ifinmail.test', 'big', GOOD, quota_bytes=4 * GB)
        with _usage(2 * GB, 1 * GB):
            budget = QuotaService.get_budget()
        self.assertTrue(budget.overcommitted)
        self.assertEqual(budget.headroom_bytes, -2 * GB)

    def test_unknown_disk_leaves_headroom_none(self) -> None:
        MailboxService.create('ifinmail.test', 'one', GOOD, quota_bytes=GB)
        with _usage(None, None):
            budget = QuotaService.get_budget()
        self.assertIsNone(budget.disk_total_bytes)
        self.assertIsNone(budget.headroom_bytes)
        self.assertFalse(budget.overcommitted)

    def test_empty_installation_budget(self) -> None:
        with _usage(5 * GB, 5 * GB):
            budget = QuotaService.get_budget()
        self.assertEqual(budget.allocated_bytes, 0)
        self.assertEqual(budget.headroom_bytes, 5 * GB)


class HumanBytesTests(MailTablesTestCase):
    def test_labels(self) -> None:
        self.assertEqual(human_bytes(None), '—')
        self.assertEqual(human_bytes(0), '0 B')
        self.assertEqual(human_bytes(1536), '2 KB')
        self.assertEqual(human_bytes(5 * MB), '5 MB')
        self.assertEqual(human_bytes(3 * GB), '3.0 GB')
        self.assertEqual(human_bytes(-2 * GB), '-2.0 GB')
        self.assertEqual(human_bytes(2 * 1024**4), '2.0 TB')


class QuotaBudgetTypeTests(MailTablesTestCase):
    def test_headroom_and_overcommit_properties(self) -> None:
        budget = QuotaBudget(
            disk_total_bytes=10 * GB,
            disk_free_bytes=4 * GB,
            allocated_bytes=12 * GB,
            mailbox_count=2,
            unlimited_count=0,
        )
        self.assertEqual(budget.headroom_bytes, -2 * GB)
        self.assertTrue(budget.overcommitted)
