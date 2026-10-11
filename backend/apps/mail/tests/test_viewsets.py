"""mail viewsets — api.py → viewsets/ → serializers/ → services/ layer tests."""

from unittest.mock import patch

from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.mail.api import (
    create_alias,
    create_mailbox,
    delete_alias,
    delete_mailbox,
    get_outbound_state,
    list_aliases,
    list_mailboxes,
    render_outbound,
    set_active,
    set_max_hops,
    set_quota,
    set_smart_host,
)
from backend.apps.mail.serializers import AliasCreateIn, MailboxCreateIn, MailboxOut
from backend.apps.mail.services.postfix_runtime import OutboundConfigError
from backend.apps.mail.types.provisioning import MailboxError

GOOD = 'Correct-Horse-9'


class MailboxViewsetTests(MailTablesTestCase):
    def test_create_and_list_are_shaped_without_secrets(self) -> None:
        self.make_domain()
        out = create_mailbox(MailboxCreateIn('ifinmail.test', 'alice', GOOD))
        self.assertIsInstance(out, MailboxOut)
        self.assertEqual(out.address, 'alice@ifinmail.test')
        self.assertFalse(hasattr(out, 'password'))
        self.assertFalse(hasattr(out, 'password_hash'))
        rows = list_mailboxes()
        self.assertEqual([r.address for r in rows], ['alice@ifinmail.test'])

    def test_duplicate_is_refused(self) -> None:
        self.make_domain()
        create_mailbox(MailboxCreateIn('ifinmail.test', 'alice', GOOD))
        with self.assertRaises(MailboxError):
            create_mailbox(MailboxCreateIn('ifinmail.test', 'alice', GOOD))

    def test_quota_set_and_negative_refused(self) -> None:
        self.make_domain()
        create_mailbox(MailboxCreateIn('ifinmail.test', 'alice', GOOD))
        set_quota('alice@ifinmail.test', 5_000_000)
        self.assertEqual(list_mailboxes()[0].quota_bytes, 5_000_000)
        with self.assertRaises(MailboxError):
            set_quota('alice@ifinmail.test', -1)

    def test_last_admin_cannot_be_disabled(self) -> None:
        self.make_domain()
        create_mailbox(MailboxCreateIn('ifinmail.test', 'admin', GOOD, is_admin=True))
        with self.assertRaises(MailboxError):
            set_active('admin@ifinmail.test', False)

    def test_delete_removes_mailbox(self) -> None:
        self.make_domain()
        create_mailbox(MailboxCreateIn('ifinmail.test', 'alice', GOOD))
        delete_mailbox('alice@ifinmail.test')
        self.assertEqual(list_mailboxes(), [])


class AliasViewsetTests(MailTablesTestCase):
    def test_create_list_delete(self) -> None:
        self.make_domain()
        out = create_alias(AliasCreateIn('sales@ifinmail.test', 'alice@example.com'))
        self.assertEqual(out.source, 'sales@ifinmail.test')
        self.assertEqual([a.source for a in list_aliases()], ['sales@ifinmail.test'])
        delete_alias(out.id)
        self.assertEqual(list_aliases(), [])

    def test_loop_is_refused(self) -> None:
        self.make_domain()
        create_alias(AliasCreateIn('a@ifinmail.test', 'b@ifinmail.test'))
        with self.assertRaises(MailboxError):
            create_alias(AliasCreateIn('b@ifinmail.test', 'a@ifinmail.test'))


class OutboundViewsetTests(MailTablesTestCase):
    def test_state_is_shaped_and_rendered(self) -> None:
        with patch.dict('os.environ', {}, clear=False):
            state = get_outbound_state()
        self.assertIsInstance(state.max_hops, int)
        text = render_outbound()
        self.assertIn('hopcount_limit =', text)

    def test_hop_limit_is_bounded(self) -> None:
        for bad in (4, 31, -1):
            with self.assertRaises(OutboundConfigError):
                set_max_hops(bad)

    def test_smart_host_without_env_is_refused(self) -> None:
        with (
            patch.dict('os.environ', {'MAIL_SMART_HOST': ''}),
            self.assertRaises(OutboundConfigError),
        ):
            set_smart_host(True)
