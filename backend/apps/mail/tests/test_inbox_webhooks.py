"""Inbox webhooks: new mail in watched mailboxes becomes signed message.received events."""

from __future__ import annotations

import os
import socket
from unittest.mock import patch

from django.test import override_settings

from backend.apps.accounts.services.tokens import TokenService, key_id
from backend.apps.accounts.tests import test_api_v1 as base
from backend.apps.core.plugins.services import InstallationService
from backend.apps.domains.models import Domain
from backend.apps.mail.models import WebhookDelivery
from backend.apps.mail.services import imap_reader, inbox_events, webhooks
from backend.apps.mail.services.mailboxes import MailboxService
from backend.apps.mail.tests.fake_imap import PASSWORD, FakeStore, message
from backend.apps.mail.tests.test_delivery_events import fake_dns

BOX = 'support@ifinmail.test'


@override_settings(CACHES=base.LOCMEM)
class InboxEventsBase(base.ApiBase):
    def setUp(self) -> None:
        super().setUp()
        from django.core.cache import cache

        cache.clear()
        MailboxService.create('ifinmail.test', 'support', 'Correct-Horse-9-pass')
        self.store = FakeStore()
        self.store.boxes[BOX] = []
        for active in (
            patch.object(imap_reader.imaplib, 'IMAP4_SSL', side_effect=self.store.client),
            patch.dict(os.environ, {'DOVECOT_MASTER_PASSWORD': PASSWORD}),
            patch.object(socket, 'getaddrinfo', side_effect=fake_dns),
            patch.object(webhooks, '_schedule'),
        ):
            active.start()
            self.addCleanup(active.stop)
        InstallationService.install('inbox-webhooks', {}, 'root@ifinmail.test')

    def watch(self, boxes=(BOX,), **kw):  # noqa: ANN001, ANN201
        row, secret = webhooks.create_endpoint(
            name=kw.pop('name', 'desk'),
            url='https://hooks.example.com/in',
            events=['message.received'],
            mailboxes=list(boxes),
            **kw,
        )
        return row


class ScanTests(InboxEventsBase):
    def test_first_look_starts_from_now_then_new_mail_becomes_events(self) -> None:
        self.store.deliver(BOX, message('Old', 'was already here', to=BOX))
        row = self.watch()
        self.assertEqual(inbox_events.scan(), 0)  # baseline: no replay
        self.store.deliver(BOX, message('Help!', 'My order is late', to=BOX))
        self.store.deliver(BOX, message('Verify', 'Your verification code is 739204', to=BOX))
        self.assertEqual(inbox_events.scan(), 2)
        events = list(WebhookDelivery.objects.filter(endpoint=row).order_by('payload__data__uid'))
        subjects = sorted(e.payload['data']['subject'] for e in events)
        self.assertEqual(subjects, ['Help!', 'Verify'])
        verify = next(e for e in events if e.payload['data']['subject'] == 'Verify')
        data = verify.payload['data']
        self.assertEqual(verify.event_type, 'message.received')
        self.assertEqual(data['mailbox'], BOX)
        self.assertEqual(data['code'], '739204')
        self.assertIn('739204', data['text'])
        self.assertEqual(data['from'], 'no-reply@service.example')
        self.assertEqual(inbox_events.scan(), 0)  # nothing new, nothing repeated

    def test_the_body_can_be_left_out(self) -> None:
        InstallationService.configure('inbox-webhooks', {'include_body': False}, 'a')
        self.watch()
        inbox_events.scan()
        self.store.deliver(BOX, message('Private', 'secret contents 123', to=BOX))
        inbox_events.scan()
        data = WebhookDelivery.objects.get().payload['data']
        self.assertNotIn('text', data)
        self.assertNotIn('html', data)
        self.assertTrue(data['snippet'])

    def test_a_recreated_mailbox_starts_over_without_replaying(self) -> None:
        from django.core.cache import cache

        self.watch()
        inbox_events.scan()
        self.store.deliver(BOX, message('One', to=BOX))
        inbox_events.scan()
        cache.set(inbox_events._state_key(BOX), {'validity': 1, 'last_uid': 99}, None)  # stale
        self.assertEqual(inbox_events.scan(), 0)
        self.assertEqual(WebhookDelivery.objects.count(), 1)

    def test_only_webhooks_watching_that_mailbox_get_it(self) -> None:
        MailboxService.create('ifinmail.test', 'sales', 'Correct-Horse-9-pass')
        self.store.boxes['sales@ifinmail.test'] = []
        desk = self.watch()
        sales = self.watch(boxes=('sales@ifinmail.test',), name='sales')
        inbox_events.scan()
        self.store.deliver(BOX, message('For support', to=BOX))
        inbox_events.scan()
        self.assertEqual(WebhookDelivery.objects.filter(endpoint=desk).count(), 1)
        self.assertEqual(WebhookDelivery.objects.filter(endpoint=sales).count(), 0)

    def test_nothing_without_the_plugin(self) -> None:
        self.watch()
        InstallationService.uninstall('inbox-webhooks', 'a')
        self.store.deliver(BOX, message(to=BOX))
        self.assertEqual(inbox_events.scan(), 0)

    def test_only_existing_mailboxes(self) -> None:
        with self.assertRaisesMessage(webhooks.WebhookError, 'not a mailbox'):
            self.watch(boxes=('ghost@ifinmail.test',))


class KeyPermissionTests(InboxEventsBase):
    def make_key(self, scopes):  # noqa: ANN001, ANN201
        row, token = TokenService.create(
            self.owner, 'k', list(scopes), expires_in_days=30, allowed_senders=['*@ifinmail.test']
        )
        return {'key': key_id(row.prefix), 'secret': token.split('.', 2)[2]}

    def create(self, auth, boxes):  # noqa: ANN001, ANN201
        return self.call(
            'post', '/api/v1/webhooks', key=auth['key'], secret=auth['secret'],
            body={'name': 'w', 'url': 'https://h.example.com/', 'events': ['message.received'], 'mailboxes': boxes},
        )

    def test_sending_rights_do_not_grant_reading_people_mail(self) -> None:
        sender = self.make_key(['mail.send'])  # may send as *@ifinmail.test
        self.assertEqual(self.create(sender, [BOX]).status_code, 403)

    def test_mail_managers_may_watch_mailboxes(self) -> None:
        manager = self.make_key(['mail.send', 'mail.manage'])
        self.assertEqual(self.create(manager, [BOX]).status_code, 201)

    def test_a_key_may_watch_its_own_agent_inbox(self) -> None:
        Domain.objects.create(name='agents.ifinmail.test')
        InstallationService.install('agent-inboxes', {'domain': 'agents.ifinmail.test'}, 'a')
        row, token = TokenService.create(self.owner, 'agent', ['agents.manage', 'mail.send'], expires_in_days=30)
        auth = {'key': key_id(row.prefix), 'secret': token.split('.', 2)[2]}
        inbox = self.call('post', '/api/v1/inboxes', key=auth['key'], secret=auth['secret'], body={}).json()['address']
        self.assertEqual(self.create(auth, [inbox]).status_code, 201)
