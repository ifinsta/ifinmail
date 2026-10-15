"""Human approval: mail from agents waits for a person when the rule says so."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.services.tokens import TokenService, key_id
from backend.apps.accounts.tests import test_api_v1 as base
from backend.apps.core.plugins.services import InstallationService
from backend.apps.mail.models import PendingMessage
from backend.apps.mail.services import approvals

PLUGIN = 'human-approval'
BODY = {'from': 'bot@ifinmail.test', 'to': ['ana@example.org'], 'subject': 'Hello', 'text': 'Hi Ana'}


@override_settings(CACHES=base.LOCMEM)
class ApprovalBase(base.ApiBase):
    def setUp(self) -> None:
        super().setUp()
        from django.core.cache import cache

        cache.clear()
        self.agent = self.make_key(['mail.send', 'agents.manage'])
        self.plain = self.make_key(['mail.send'])
        self.manager = self.make_key(['mail.manage', 'mail.send'])

    def make_key(self, scopes: list[str]) -> dict[str, str]:
        row, token = TokenService.create(
            self.owner, '+'.join(scopes), scopes, expires_in_days=30,
            allowed_senders=['bot@ifinmail.test', 'ops@ifinmail.test'],
        )
        return {'key': key_id(row.prefix), 'secret': token.split('.', 2)[2], 'prefix': row.prefix}

    def enable(self, **settings: object) -> None:
        InstallationService.install(PLUGIN, settings, 'root@ifinmail.test')

    def api(self, method: str, path: str, auth: dict, body: dict | None = None):  # noqa: ANN201
        return self.call(method, '/api/v1' + path, key=auth['key'], secret=auth['secret'], body=body)

    def send(self, auth: dict, **overrides: object):  # noqa: ANN201
        return self.api('post', '/messages', auth, {**BODY, **overrides})


class RuleTests(ApprovalBase):
    def test_without_the_plugin_mail_goes_at_once(self) -> None:
        response = self.send(self.agent)
        self.assertEqual(response.json()['status'], 'queued')
        self.assertEqual(len(mail.outbox), 1)

    def test_external_rule_holds_outside_mail_from_agents_only(self) -> None:
        self.enable(rule='external')
        held = self.send(self.agent)
        self.assertEqual(held.status_code, 202)
        self.assertEqual(held.json()['status'], 'pending_approval')
        self.assertEqual(mail.outbox[-1].subject if mail.outbox else '', 'A message is waiting for approval')
        self.assertEqual(len([m for m in mail.outbox if m.subject == BODY['subject']]), 0)
        inside = self.send(self.agent, to=['root@ifinmail.test'])
        self.assertEqual(inside.json()['status'], 'queued')
        not_agent = self.send(self.plain)
        self.assertEqual(not_agent.json()['status'], 'queued')

    def test_all_keys_and_every_message(self) -> None:
        self.enable(rule='all', applies_to='all')
        for auth in (self.agent, self.plain):
            self.assertEqual(self.send(auth, to=['root@ifinmail.test']).json()['status'], 'pending_approval')

    def test_first_contact_holds_only_new_recipients(self) -> None:
        self.enable(rule='first_contact')
        first = self.send(self.agent)
        self.assertEqual(first.json()['status'], 'pending_approval')
        approvals.approve(first.json()['id'], actor='root@ifinmail.test')
        again = self.send(self.agent)
        self.assertEqual(again.json()['status'], 'queued')  # Ana is known now
        new = self.send(self.agent, to=['bob@example.org'])
        self.assertEqual(new.json()['status'], 'pending_approval')

    def test_invalid_mail_is_refused_not_held(self) -> None:
        self.enable(rule='all')
        self.assertEqual(self.send(self.agent, **{'from': 'ceo@ifinmail.test'}).status_code, 403)
        self.assertFalse(PendingMessage.objects.exists())


class DecisionTests(ApprovalBase):
    def setUp(self) -> None:
        super().setUp()
        self.enable(rule='external')
        self.held_id = self.send(self.agent).json()['id']
        mail.outbox.clear()

    def test_the_agent_polls_its_message(self) -> None:
        mine = self.api('get', f'/approvals/{self.held_id}', self.agent).json()
        self.assertEqual(mine['status'], 'pending')
        self.assertEqual(self.api('get', f'/approvals/{self.held_id}', self.plain).status_code, 404)
        self.assertEqual(self.api('get', '/approvals?status=pending', self.agent).json()['count'], 1)

    def test_approval_sends_it_with_every_check(self) -> None:
        done = self.api('post', f'/approvals/{self.held_id}/approve', self.manager, {'note': 'ok'})
        self.assertEqual(done.status_code, 200, done.content)
        self.assertEqual(done.json()['status'], 'sent')
        self.assertTrue(done.json()['message_id'])
        self.assertEqual([m.subject for m in mail.outbox], ['Hello'])
        self.assertEqual(self.api('post', f'/approvals/{self.held_id}/approve', self.manager, {}).status_code, 409)

    def test_a_key_cannot_approve_its_own_messages(self) -> None:
        own = self.make_key(['mail.send', 'mail.manage', 'agents.manage'])
        held = self.send(own).json()['id']
        self.assertEqual(self.api('post', f'/approvals/{held}/approve', own, {}).status_code, 403)
        self.assertEqual(self.api('post', f'/approvals/{self.held_id}/approve', self.agent, {}).status_code, 403)  # no mail.manage

    def test_rejection_and_expiry(self) -> None:
        rejected = self.api('post', f'/approvals/{self.held_id}/reject', self.manager, {'note': 'no'})
        self.assertEqual(rejected.json()['status'], 'rejected')
        self.assertEqual(mail.outbox, [])
        late = self.send(self.agent, subject='Later').json()['id']
        PendingMessage.objects.filter(pk=late).update(created_at=timezone.now() - timedelta(hours=25))
        self.assertEqual(approvals.expire(), 1)
        self.assertEqual(PendingMessage.objects.get(pk=late).status, 'expired')

    def test_a_revoked_key_makes_approval_fail_not_send(self) -> None:
        from backend.apps.accounts.models import APIToken

        APIToken.objects.filter(prefix=self.agent['prefix']).delete()
        row = approvals.approve(self.held_id, actor='root@ifinmail.test')
        self.assertEqual(row.status, 'failed')
        self.assertEqual(mail.outbox, [])

    def test_a_sender_that_lost_its_rights_fails(self) -> None:
        from backend.apps.accounts.models import APIToken

        APIToken.objects.filter(prefix=self.agent['prefix']).update(allowed_senders=['ops@ifinmail.test'])
        row = approvals.approve(self.held_id, actor='root@ifinmail.test')
        self.assertEqual(row.status, 'failed')
        self.assertIn('may not send', row.note)

    def test_the_console_page_approves(self) -> None:
        self.client.force_login(self.owner, backend=base.MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()
        page = self.client.get(reverse('accounts:approvals'))
        self.assertContains(page, 'Hello')
        self.assertContains(page, 'outside this server')
        self.client.post(reverse('accounts:approvals_decide'), {'pending': self.held_id, 'decision': 'approve'})
        self.assertEqual(PendingMessage.objects.get(pk=self.held_id).status, 'sent')
        self.assertEqual([m.subject for m in mail.outbox], ['Hello'])

    def test_administrators_are_told_but_not_flooded(self) -> None:
        with patch.object(approvals, 'send_mail') as told:
            self.send(self.agent, subject='Two')
            self.send(self.agent, subject='Three')
        self.assertLessEqual(told.call_count, 1)
