"""Quota budget — available space vs. promised space, warnings, edge cases."""

import os
import shutil
import tempfile
from unittest.mock import patch

from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.mail.services import MailboxService, QuotaService
from backend.apps.mail.types.quota import MB, QuotaBudget, human_bytes

GOOD = 'Correct-Horse-9'
GB = 1024 * MB
_QUOTA_DIR = 'backend.apps.mail.services.quota._MAIL_VHOSTS_DIR'


def _usage(total: int | None, free: int | None):
    """Patch the disk inspection result."""
    return patch('backend.apps.mail.services.quota._disk_usage', return_value=(total, free))


class QuotaServiceTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.make_domain()
        # An isolated mail volume so tests never touch a real one.
        self.mail_root = tempfile.mkdtemp(prefix='ifinmail-vhosts-')
        self.addCleanup(shutil.rmtree, self.mail_root, True)

    def _store(self, local_part: str, size: int, domain: str = 'ifinmail.test') -> None:
        path = os.path.join(self.mail_root, domain, local_part, 'Maildir', 'cur')
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, 'msg'), 'wb') as handle:
            handle.write(b'x' * size)

    def test_counts_finite_quotas_and_unlimited_separately(self) -> None:
        MailboxService.create('ifinmail.test', 'one', GOOD, quota_bytes=GB)
        MailboxService.create('ifinmail.test', 'two', GOOD, quota_bytes=2 * GB)
        MailboxService.create('ifinmail.test', 'free', GOOD, quota_bytes=0)
        with _usage(10 * GB, 7 * GB), patch(_QUOTA_DIR, self.mail_root):
            budget = QuotaService.get_budget()
        self.assertEqual(budget.allocated_bytes, 3 * GB)
        self.assertEqual(budget.mailbox_count, 3)
        self.assertEqual(budget.unlimited_count, 1)
        self.assertEqual(budget.stored_bytes, 0)
        self.assertEqual(budget.unfilled_bytes, 3 * GB)
        # Nothing stored: all 7 GB free can still be promised.
        self.assertEqual(budget.headroom_bytes, 7 * GB - 3 * GB)
        self.assertFalse(budget.overcommitted)
        self.assertEqual(budget.disk_free_bytes, 7 * GB)

    def test_stored_mail_shrinks_the_promiseable_room(self) -> None:
        MailboxService.create('ifinmail.test', 'one', GOOD, quota_bytes=GB)
        self._store('one', GB // 2)
        with _usage(10 * GB, 4 * GB), patch(_QUOTA_DIR, self.mail_root):
            budget = QuotaService.get_budget()
        self.assertEqual(budget.stored_bytes, GB // 2)
        self.assertEqual(budget.unfilled_bytes, GB // 2)
        # Free 4 GB, only 0.5 GB of promises unfilled -> 3.5 GB headroom.
        self.assertEqual(budget.headroom_bytes, 4 * GB - GB // 2)
        self.assertEqual(budget.available_bytes, 4 * GB + GB // 2)

    def test_stored_mail_counts_towards_available_space(self) -> None:
        """disk free already excludes stored mail; adding it back avoids
        double-counting it against the promises."""
        MailboxService.create('ifinmail.test', 'one', GOOD, quota_bytes=2 * GB)
        self._store('one', 2 * GB)
        with _usage(10 * GB, 1 * GB), patch(_QUOTA_DIR, self.mail_root):
            budget = QuotaService.get_budget()
        self.assertEqual(budget.unfilled_bytes, 0)
        # Fully filled promise: all 1 GB free is still promiseable.
        self.assertEqual(budget.headroom_bytes, 1 * GB)

    def test_overquota_stored_mail_does_not_inflate_the_unfilled(self) -> None:
        MailboxService.create('ifinmail.test', 'one', GOOD, quota_bytes=GB)
        self._store('one', 2 * GB)  # already beyond its quota
        with _usage(10 * GB, 1 * GB), patch(_QUOTA_DIR, self.mail_root):
            budget = QuotaService.get_budget()
        self.assertEqual(budget.stored_bytes, 2 * GB)
        self.assertEqual(budget.unfilled_bytes, 0)
        self.assertEqual(budget.headroom_bytes, 1 * GB)

    def test_unlimited_mailbox_bytes_are_not_counted(self) -> None:
        MailboxService.create('ifinmail.test', 'free', GOOD, quota_bytes=0)
        self._store('free', 3 * GB)
        with _usage(10 * GB, 2 * GB), patch(_QUOTA_DIR, self.mail_root):
            budget = QuotaService.get_budget()
        self.assertEqual(budget.stored_bytes, 0)
        self.assertEqual(budget.unfilled_bytes, 0)
        self.assertEqual(budget.headroom_bytes, 2 * GB)

    def test_missing_mailbox_directory_counts_as_empty(self) -> None:
        MailboxService.create('ifinmail.test', 'one', GOOD, quota_bytes=GB)
        with _usage(10 * GB, 4 * GB), patch(_QUOTA_DIR, self.mail_root):
            budget = QuotaService.get_budget()
        self.assertEqual(budget.stored_bytes, 0)
        self.assertEqual(budget.unfilled_bytes, GB)

    def test_overcommit_is_detected(self) -> None:
        MailboxService.create('ifinmail.test', 'big', GOOD, quota_bytes=4 * GB)
        with _usage(2 * GB, 1 * GB), patch(_QUOTA_DIR, self.mail_root):
            budget = QuotaService.get_budget()
        self.assertTrue(budget.overcommitted)
        # 1 GB free but 4 GB of promises unfilled -> 3 GB short.
        self.assertEqual(budget.headroom_bytes, -3 * GB)

    def test_unknown_disk_leaves_headroom_none(self) -> None:
        MailboxService.create('ifinmail.test', 'one', GOOD, quota_bytes=GB)
        with _usage(None, None), patch(_QUOTA_DIR, self.mail_root):
            budget = QuotaService.get_budget()
        self.assertIsNone(budget.disk_total_bytes)
        self.assertIsNone(budget.headroom_bytes)
        self.assertFalse(budget.overcommitted)

    def test_empty_installation_budget(self) -> None:
        with _usage(5 * GB, 5 * GB), patch(_QUOTA_DIR, self.mail_root):
            budget = QuotaService.get_budget()
        self.assertEqual(budget.allocated_bytes, 0)
        self.assertEqual(budget.headroom_bytes, 5 * GB)

    def test_mail_volume_hidden_still_uses_disk_numbers(self) -> None:
        """No mail volume (dev machine): everything counts as unstored."""
        MailboxService.create('ifinmail.test', 'one', GOOD, quota_bytes=GB)
        with _usage(10 * GB, 5 * GB), patch(_QUOTA_DIR, '/nonexistent/vhosts'):
            budget = QuotaService.get_budget()
        self.assertEqual(budget.stored_bytes, 0)
        self.assertEqual(budget.unfilled_bytes, GB)
        self.assertEqual(budget.headroom_bytes, 4 * GB)


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
    def test_headroom_uses_available_space_minus_unfilled(self) -> None:
        budget = QuotaBudget(
            disk_total_bytes=10 * GB,
            disk_free_bytes=4 * GB,
            allocated_bytes=12 * GB,
            mailbox_count=2,
            unlimited_count=0,
            stored_bytes=10 * GB,
            unfilled_bytes=2 * GB,
        )
        # Free 4 GB, promises unfilled 2 GB -> 2 GB can still be promised.
        self.assertEqual(budget.available_bytes, 14 * GB)
        self.assertEqual(budget.headroom_bytes, 2 * GB)
        self.assertFalse(budget.overcommitted)

    def test_overcommit_property(self) -> None:
        budget = QuotaBudget(
            disk_total_bytes=10 * GB,
            disk_free_bytes=1 * GB,
            allocated_bytes=12 * GB,
            mailbox_count=2,
            unlimited_count=0,
            stored_bytes=8 * GB,
            unfilled_bytes=4 * GB,
        )
        self.assertEqual(budget.headroom_bytes, -3 * GB)
        self.assertTrue(budget.overcommitted)

    def test_unknown_volume_leaves_properties_none(self) -> None:
        budget = QuotaBudget(
            disk_total_bytes=10 * GB,
            disk_free_bytes=4 * GB,
            allocated_bytes=2 * GB,
            mailbox_count=1,
            unlimited_count=0,
            stored_bytes=None,
            unfilled_bytes=None,
        )
        self.assertIsNone(budget.headroom_bytes)
        self.assertFalse(budget.overcommitted)
