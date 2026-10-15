"""Agent inboxes: one-call mailboxes for agents, read over the API through Dovecot."""

from __future__ import annotations

import os
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from backend.apps.accounts.services.tokens import TokenService, key_id
from backend.apps.accounts.tests import test_api_v1 as base
from backend.apps.core.plugins.services import InstallationService
from backend.apps.domains.models import Domain
from backend.apps.mail.models import AgentInbox, Mailbox
from backend.apps.mail.services import agent_inboxes, imap_reader
from backend.apps.mail.tests.fake_imap import PASSWORD, FakeStore, message

PLUGIN = 'agent-inboxes'
DOMAIN = 'agents.ifinmail.test'


@override_settings(CACHES=base.LOCMEM)
class InboxBase(base.ApiBase):
    def setUp(self) -> None:
        super().setUp()
        Domain.objects.create(name=DOMAIN)
        self.store = FakeStore()
        imap = patch.object(imap_reader.imaplib, 'IMAP4_SSL', side_effect=self.store.client)
        imap.start()
        self.addCleanup(imap.stop)
        env = patch.dict(os.environ, {'DOVECOT_MASTER_PASSWORD': PASSWORD})
        env.start()
        self.addCleanup(env.stop)
        sleep = patch.object(imap_reader.time, 'sleep')
        sleep.start()
        self.addCleanup(sleep.stop)
        self.agent = self.agent_key()

    def enable(self, **settings: object) -> None:
        InstallationService.install(PLUGIN, {'domain': DOMAIN, **settings}, 'root@ifinmail.test')

    def agent_key(self, scopes: tuple[str, ...] = ('agents.manage',)) -> dict[str, str]:
        row, token = TokenService.create(self.owner, 'agent', list(scopes), expires_in_days=30)
        return {'key': key_id(row.prefix), 'secret': token.split('.', 2)[2], 'prefix': row.prefix}

    def api(self, method: str, path: str, body: dict | None = None, auth: dict | None = None):  # noqa: ANN201
        auth = auth or self.agent
        return self.call(method, '/api/v1' + path, key=auth['key'], secret=auth['secret'], body=body)

    def new_inbox(self, **body: object) -> str:
        response = self.api('post', '/inboxes', body or {})
        self.assertEqual(response.status_code, 201, response.content)
        address = response.json()['address']
        self.store.boxes.setdefault(address, [])
        return address


class OffTests(InboxBase):
    def test_nothing_without_the_plugin(self) -> None:
        self.assertEqual(self.api('post', '/inboxes', {}).status_code, 403)

    def test_a_key_needs_the_agents_scope(self) -> None:
        self.enable()
        response = self.call('post', '/api/v1/inboxes', key=self.key, secret=self.secret, body={})
        self.assertEqual(response.status_code, 403)


class LifecycleTests(InboxBase):
    def setUp(self) -> None:
        super().setUp()
        self.enable()

    def test_create_with_a_random_or_chosen_name(self) -> None:
        random = self.new_inbox()
        self.assertRegex(random, rf'^agent-[0-9a-f]{{8}}@{DOMAIN}$')
        chosen = self.new_inbox(name='signup-bot', label='GitHub sign-up', ttl_hours=2)
        self.assertEqual(chosen, f'signup-bot@{DOMAIN}')
        row = AgentInbox.objects.get(address=chosen)
        self.assertEqual(row.label, 'GitHub sign-up')
        self.assertAlmostEqual(
            (row.expires_at - timezone.now()).total_seconds(), 7200, delta=60
        )
        self.assertTrue(Mailbox.objects.filter(local_part='signup-bot', domain__name=DOMAIN).exists())

    def test_names_and_limits(self) -> None:
        for name in ('Bad Name', 'x+y', 'postmaster', '-dash'):
            with self.subTest(name=name):
                self.assertIn(self.api('post', '/inboxes', {'name': name}).status_code, (409, 422))
        self.new_inbox(name='twin')
        self.assertEqual(self.api('post', '/inboxes', {'name': 'twin'}).status_code, 409)
        InstallationService.configure(PLUGIN, {'max_per_key': 2}, 'a')
        self.new_inbox()
        self.assertEqual(self.api('post', '/inboxes', {}).status_code, 409)

    def test_a_key_sees_only_its_own_inboxes(self) -> None:
        address = self.new_inbox()
        other = self.agent_key()
        self.assertEqual(self.api('get', '/inboxes', auth=other).json(), [])
        for method, path in (('get', ''), ('get', '/messages'), ('delete', '')):
            with self.subTest(path=path):
                self.assertEqual(self.api(method, f'/inboxes/{address}{path}', auth=other).status_code, 404)
        # Not even a person's mailbox through this route.
        self.assertEqual(self.api('get', '/inboxes/root@ifinmail.test/messages').status_code, 404)

    def test_delete_erases_the_mail_and_the_mailbox(self) -> None:
        address = self.new_inbox()
        self.store.deliver(address, message(to=address))
        self.assertEqual(self.api('delete', f'/inboxes/{address}').status_code, 204)
        self.assertEqual(self.store.boxes[address], [])  # emptied over IMAP first
        self.assertFalse(AgentInbox.objects.exists())
        self.assertFalse(Mailbox.objects.filter(domain__name=DOMAIN).exists())

    def test_expired_inboxes_are_removed(self) -> None:
        keep = self.new_inbox(ttl_hours=0)
        gone = self.new_inbox()
        AgentInbox.objects.filter(address=gone).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(agent_inboxes.expire(), 1)
        self.assertEqual(list(AgentInbox.objects.values_list('address', flat=True)), [keep])


class ReadingTests(InboxBase):
    def setUp(self) -> None:
        super().setUp()
        self.enable()
        self.address = self.new_inbox(name='bot')

    def test_list_read_and_find_the_code(self) -> None:
        self.store.deliver(self.address, message('Welcome', 'Hello there', to=self.address))
        uid = self.store.deliver(
            self.address,
            message('Your GitHub launch code', 'Your launch code: 48291037', to=self.address),
        )
        listing = self.api('get', f'/inboxes/{self.address}/messages').json()
        self.assertEqual([m['subject'] for m in listing], ['Your GitHub launch code', 'Welcome'])
        self.assertFalse(listing[0]['seen'])  # reading never marks it read
        self.assertEqual(listing[0]['from'], 'no-reply@service.example')
        newer = self.api('get', f'/inboxes/{self.address}/messages?since_uid={uid - 1}').json()
        self.assertEqual([m['uid'] for m in newer], [uid])
        full = self.api('get', f'/inboxes/{self.address}/messages/{uid}').json()
        self.assertIn('48291037', full['text'])
        found = self.api('get', f'/inboxes/{self.address}/messages/{uid}/code').json()
        self.assertEqual(found['code'], '48291037')
        self.assertEqual(self.api('get', f'/inboxes/{self.address}/messages/999').status_code, 404)
        self.assertTrue(all(login.endswith('*ifinmail-console') for login in self.store.logins))

    def test_html_only_mail_and_magic_links(self) -> None:
        uid = self.store.deliver(
            self.address,
            message(
                'Sign in to Acme', 'Sign in below', to=self.address,
                html='<p>Click</p><a href="https://acme.example.com/magic-login?token=xyz">Sign in</a>',
            ),
        )
        found = self.api('get', f'/inboxes/{self.address}/messages/{uid}/code').json()
        self.assertEqual(found['link'], 'https://acme.example.com/magic-login?token=xyz')

    def test_wait_returns_the_next_message_with_its_code(self) -> None:
        self.store.deliver(self.address, message('Old', 'old code 111111', to=self.address))
        arriving = {'done': False}

        def arrive() -> None:
            if not arriving['done']:
                arriving['done'] = True
                self.store.deliver(self.address, message('Verify', 'Your verification code is 739204', to=self.address))

        self.store.on_noop = arrive
        response = self.api('get', f'/inboxes/{self.address}/wait?since_uid=1&timeout=5')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['code'], '739204')
        self.assertEqual(response.json()['message']['uid'], 2)

    def test_wait_answers_204_when_nothing_comes(self) -> None:
        self.assertEqual(self.api('get', f'/inboxes/{self.address}/wait?timeout=0').status_code, 204)

    def test_plus_tags_tell_tasks_apart(self) -> None:
        self.store.deliver(self.address, message('A', 'code 111222', to=f'bot+github@{DOMAIN}'))
        self.store.deliver(self.address, message('B', 'code 333444', to=f'bot+slack@{DOMAIN}'))
        tagged = self.api('get', f'/inboxes/{self.address}/messages?tag=slack').json()
        self.assertEqual([m['subject'] for m in tagged], ['B'])
        waited = self.api('get', f'/inboxes/{self.address}/wait?tag=github&timeout=1').json()
        self.assertEqual(waited['code'], '111222')

    def test_delete_one_message(self) -> None:
        uid = self.store.deliver(self.address, message(to=self.address))
        self.assertEqual(self.api('delete', f'/inboxes/{self.address}/messages/{uid}').status_code, 204)
        self.assertEqual(self.api('get', f'/inboxes/{self.address}/messages').json(), [])

    def test_a_missing_master_password_is_a_clear_503(self) -> None:
        with patch.dict(os.environ, {'DOVECOT_MASTER_PASSWORD': ''}):
            response = self.api('get', f'/inboxes/{self.address}/messages')
        self.assertEqual(response.status_code, 503)
        self.assertIn('DOVECOT_MASTER_PASSWORD', response.json()['detail'])


class SendingAsAnInboxTests(InboxBase):
    def test_a_key_sends_as_its_own_inboxes_only(self) -> None:
        self.enable()
        agent = self.agent_key(('agents.manage', 'mail.send'))  # no allowed senders needed
        address = self.api('post', '/inboxes', {'name': 'helper'}, auth=agent).json()['address']
        body = {'from': address, 'to': ['ana@example.org'], 'subject': 'Hi', 'text': 'Hello'}
        sent = self.api('post', '/messages', body, auth=agent)
        self.assertEqual(sent.status_code, 202, sent.content)
        foreign = self.api('post', '/messages', {**body, 'from': 'root@ifinmail.test'}, auth=agent)
        self.assertEqual(foreign.status_code, 403)
        someone_elses = self.new_inbox()  # created by a different key
        self.assertEqual(self.api('post', '/messages', {**body, 'from': someone_elses}, auth=agent).status_code, 403)
