"""Developer sandbox: mail from sandbox keys is checked like real mail, kept, and never delivered."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.services.tokens import TokenService, key_id
from backend.apps.accounts.tests import test_api_messages as send_base
from backend.apps.accounts.tests import test_api_v1 as base
from backend.apps.core.plugins.services import InstallationService
from backend.apps.mail.models import SandboxMessage
from backend.apps.mail.services import containment, sandbox

URL = '/api/v1/messages'
GOOD = dict(send_base.GOOD_MESSAGE)
PLUGIN = 'developer-sandbox'


@override_settings(CACHES=base.LOCMEM)
class SandboxBase(send_base.SendBase):
    def sandbox_key(self, name: str = 'ci', senders: list[str] | None = None) -> dict[str, str]:
        row, token = TokenService.create(
            self.owner,
            name,
            ['mail.send'],
            expires_in_days=30,
            allowed_senders=senders or ['billing@ifinmail.test'],
            sandbox=True,
        )
        return {'key': key_id(row.prefix), 'secret': token.split('.', 2)[2], 'prefix': row.prefix}

    def enable(self, **settings: object) -> None:
        InstallationService.install(PLUGIN, settings, 'root@ifinmail.test')

    def send_as(self, auth: dict[str, str], body: dict | None = None, headers: dict | None = None):  # noqa: ANN201
        return self.call(
            'post', URL, key=auth['key'], secret=auth['secret'], body=body or GOOD, extra=headers
        )

    def get_as(self, auth: dict[str, str], path: str):  # noqa: ANN201
        return self.call('get', path, key=auth['key'], secret=auth['secret'])


class SandboxOffTests(SandboxBase):
    def test_a_sandbox_key_is_refused_never_delivered_when_the_plugin_is_off(self) -> None:
        auth = self.sandbox_key()
        response = self.send_as(auth)
        self.assertEqual(response.status_code, 403)
        self.assertIn('sandbox', response.json()['detail'])
        self.assertEqual(mail.outbox, [])
        self.assertFalse(SandboxMessage.objects.exists())

    def test_a_normal_key_is_unaffected(self) -> None:
        self.enable()
        auth, _ = self.sender_key()
        response = self.send(GOOD, **auth)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['status'], 'queued')
        self.assertEqual(len(mail.outbox), 1)


class SandboxCaptureTests(SandboxBase):
    def setUp(self) -> None:
        super().setUp()
        self.enable()
        self.auth = self.sandbox_key()

    def test_mail_is_captured_not_delivered(self) -> None:
        with patch.object(containment, 'record_send') as counted:
            response = self.send_as(
                self.auth,
                {**GOOD, 'cc': ['bob@example.org'], 'html': '<p>Hi</p>', 'reply_to': 'help@ifinmail.test'},
            )
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json()['status'], 'captured')
        self.assertEqual(mail.outbox, [])
        counted.assert_not_called()  # test traffic never looks like a compromised mailbox
        row = SandboxMessage.objects.get()
        self.assertEqual(row.sender, 'billing@ifinmail.test')
        self.assertEqual(row.to, ['ana@example.org'])
        self.assertEqual(row.cc, ['bob@example.org'])
        self.assertEqual(row.html, '<p>Hi</p>')
        self.assertEqual(row.message_id, response.json()['id'])

    def test_every_real_check_still_applies(self) -> None:
        wrong_sender = self.send_as(self.auth, {**GOOD, 'from': 'ceo@ifinmail.test'})
        self.assertEqual(wrong_sender.status_code, 403)
        from backend.apps.domains.models import Domain

        Domain.objects.create(name='gone.test')
        leaving = self.sandbox_key('other', ['a@gone.test'])
        Domain.objects.filter(name='gone.test').delete()  # removed after the key was made
        not_hosted = self.send_as(leaving, {**GOOD, 'from': 'a@gone.test'})
        self.assertEqual(not_hosted.status_code, 403)
        bad = self.send_as(self.auth, {**GOOD, 'to': ['not an address']})
        self.assertEqual(bad.status_code, 422)
        with send_base.capabilities(
            **{
                'developer.sandbox': {'enabled': 'yes'},
                'sending.blocked_destinations': {'domains': 'example.org'},
            }
        ):
            blocked = self.send_as(self.auth)
        self.assertEqual(blocked.status_code, 403)
        self.assertFalse(SandboxMessage.objects.exists())

    def test_reading_back_listing_filtering_and_clearing(self) -> None:
        self.send_as(self.auth, {**GOOD, 'to': ['ana@example.org'], 'subject': 'One'})
        self.send_as(self.auth, {**GOOD, 'to': ['bob@example.org'], 'subject': 'Two'})
        listing = self.get_as(self.auth, '/api/v1/sandbox/messages').json()
        self.assertEqual(listing['count'], 2)
        self.assertEqual([m['subject'] for m in listing['items']], ['Two', 'One'])
        only_ana = self.get_as(self.auth, '/api/v1/sandbox/messages?to=ANA@example.org').json()
        self.assertEqual([m['subject'] for m in only_ana['items']], ['One'])
        one = only_ana['items'][0]
        detail = self.get_as(self.auth, f"/api/v1/sandbox/messages/{one['id']}")
        self.assertEqual(detail.json()['text'], GOOD['text'])
        cleared = self.call('delete', '/api/v1/sandbox/messages', key=self.auth['key'], secret=self.auth['secret'])
        self.assertEqual(cleared.status_code, 204)
        self.assertEqual(self.get_as(self.auth, '/api/v1/sandbox/messages').json()['count'], 0)

    def test_a_key_sees_only_its_own_captures(self) -> None:
        other = self.sandbox_key('other')
        self.send_as(self.auth)
        row = SandboxMessage.objects.get()
        self.assertEqual(self.get_as(other, '/api/v1/sandbox/messages').json()['count'], 0)
        self.assertEqual(self.get_as(other, f'/api/v1/sandbox/messages/{row.pk}').status_code, 404)

    def test_a_normal_key_has_no_sandbox(self) -> None:
        auth, _ = self.sender_key()
        response = self.call('get', '/api/v1/sandbox/messages', key=auth['key'], secret=auth['secret'])
        self.assertEqual(response.status_code, 403)

    def test_idempotency_still_holds(self) -> None:
        headers = {'HTTP_IDEMPOTENCY_KEY': 'run-1'}
        first = self.send_as(self.auth, headers=headers).json()
        again = self.send_as(self.auth, headers=headers).json()
        self.assertEqual(first, again)
        self.assertEqual(SandboxMessage.objects.count(), 1)

    def test_each_key_keeps_at_most_its_cap(self) -> None:
        InstallationService.configure(PLUGIN, {'max_messages': 10}, 'root@ifinmail.test')
        for n in range(12):
            self.send_as(self.auth, {**GOOD, 'subject': f'm{n}'})
        subjects = set(SandboxMessage.objects.values_list('subject', flat=True))
        self.assertEqual(len(subjects), 10)
        self.assertNotIn('m0', subjects)  # the oldest went first
        self.assertIn('m11', subjects)

    def test_old_captures_are_purged(self) -> None:
        self.send_as(self.auth)
        SandboxMessage.objects.update(created_at=timezone.now() - timedelta(days=8))
        self.send_as(self.auth, {**GOOD, 'subject': 'fresh'})
        self.assertEqual(sandbox.purge(), 1)
        self.assertEqual(list(SandboxMessage.objects.values_list('subject', flat=True)), ['fresh'])

    def test_the_audit_trail_says_captured(self) -> None:
        from backend.apps.core.platform.services.audit import AuditService

        self.send_as(self.auth)
        self.assertTrue(AuditService.has('api_message_captured'))
        self.assertFalse(AuditService.has('api_message_sent'))


class SandboxConsoleTests(SandboxBase):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_login(self.owner, backend=base.MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def test_the_page_lists_and_shows_captures(self) -> None:
        self.enable()
        auth = self.sandbox_key('staging')
        self.send_as(auth, {**GOOD, 'subject': 'Welcome to Contoso', 'html': '<script>x</script>'})
        page = self.client.get(reverse('accounts:api_key_sandbox'))
        self.assertContains(page, 'Welcome to Contoso')
        row = SandboxMessage.objects.get()
        detail = self.client.get(reverse('accounts:api_key_sandbox_message', args=[row.pk]))
        self.assertContains(detail, 'ana@example.org')
        self.assertContains(detail, '&lt;script&gt;x&lt;/script&gt;')  # source, never rendered
        self.assertNotContains(detail, '<script>x</script>')

    def test_the_page_says_when_the_plugin_is_off(self) -> None:
        self.assertContains(self.client.get(reverse('accounts:api_key_sandbox')), 'plugin is off')

    def test_a_key_is_created_as_a_sandbox_key_from_the_form(self) -> None:
        with patch('backend.apps.accounts.views.api_keys.StepUpService.confirm', return_value=''):
            self.client.post(
                reverse('accounts:api_key_create'),
                {
                    'name': 'ci',
                    'scopes': ['mail.send'],
                    'expires_in_days': 30,
                    'senders': 'billing@ifinmail.test',
                    'sandbox': 'on',
                },
            )
        from backend.apps.accounts.models import APIToken

        self.assertTrue(APIToken.objects.get(name='ci').sandbox)
