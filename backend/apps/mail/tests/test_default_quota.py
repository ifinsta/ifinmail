"""The 1024 MB default quota: service default, form semantics, and backfill."""

import importlib

from django.db import connection

from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.mail.models import Mailbox
from backend.apps.mail.services import MailboxService
from backend.apps.mail.types.quota import DEFAULT_QUOTA_BYTES

backfill_mod = importlib.import_module('backend.apps.mail.migrations.0002_default_quota_backfill')

GOOD = 'Correct-Horse-9'


class _Editor:
    """Minimal schema_editor stand-in for the backfill migration function."""

    def __init__(self, connection):
        self.connection = connection


class QuotaBackfillTests(MailTablesTestCase):
    def test_unlimited_rows_move_to_the_new_default(self) -> None:
        self.make_domain()
        MailboxService.create('ifinmail.test', 'legacy', GOOD, quota_bytes=0)
        MailboxService.create('ifinmail.test', 'custom', GOOD, quota_bytes=5_000_000)
        backfill_mod.backfill_default_quota(None, _Editor(connection))
        rows = {m.local_part: m.quota_bytes for m in Mailbox.objects.all()}
        self.assertEqual(rows['legacy'], DEFAULT_QUOTA_BYTES)
        self.assertEqual(rows['custom'], 5_000_000)  # explicit quotas untouched

    def test_backfill_is_idempotent(self) -> None:
        self.make_domain()
        MailboxService.create('ifinmail.test', 'legacy', GOOD, quota_bytes=0)
        backfill_mod.backfill_default_quota(None, _Editor(connection))
        backfill_mod.backfill_default_quota(None, _Editor(connection))
        self.assertEqual(Mailbox.objects.get().quota_bytes, DEFAULT_QUOTA_BYTES)


class QuotaServiceDefaultTests(MailTablesTestCase):
    def test_claim_for_login_gets_the_default_quota(self) -> None:
        from backend.apps.accounts.models import MailUser

        self.make_domain()
        user = MailUser.objects.create_user('pending@elsewhere.test', GOOD)
        mailbox = MailboxService.claim_for_login(user, 'ifinmail.test', 'pending')
        self.assertEqual(mailbox.quota_bytes, DEFAULT_QUOTA_BYTES)
