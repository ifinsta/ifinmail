"""Assistant pages: permissions, the ask journey, what was sent, drafts, secret handling."""

from __future__ import annotations

from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.roles import RoleService
from backend.apps.accounts.services.setup_state import SetupState
from backend.apps.core.assistant.models import AssistantConversation
from backend.apps.core.assistant.services import provider as provider_module
from backend.apps.core.assistant.tests.fake_provider import FakeProvider, answer, tool_call
from backend.apps.core.assistant.tests.test_assistant import KEY, LEAKY_HEALTH
from backend.apps.core.assistant.types import ConversationStatus
from backend.apps.core.plugins.models import PluginInstallation
from backend.apps.core.plugins.services import InstallationService
from backend.apps.core.tests.mail_base import MailTablesTestCase

GOOD = 'Correct-Horse-9'


class AssistantPageTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        SetupState.mark_complete()
        RoleService.ensure_seed()
        self.fake = FakeProvider()
        self.addCleanup(self.fake.close)
        for target, kwargs in ((provider_module.time, {'attribute': 'sleep'}),):
            p = patch.object(target, kwargs['attribute'])
            p.start()
            self.addCleanup(p.stop)
        health = patch(
            'backend.apps.accounts.services.system_health.SystemHealth.report',
            return_value=LEAKY_HEALTH,
        )
        health.start()
        self.addCleanup(health.stop)
        self.admin = self.login('root@ifinmail.test', superuser=True)

    def login(self, email: str, *, superuser: bool = False, role: str | None = None) -> MailUser:
        user = MailUser.objects.create_user(email, GOOD, is_staff=True, is_superuser=superuser)
        if role:
            RoleService.assign(user, role)
        self.client.force_login(user, backend='django.contrib.auth.backends.ModelBackend')
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()
        return user

    def connect(self) -> None:
        InstallationService.install(
            'assistant',
            {'base_url': self.fake.url, 'model': 'test-model', 'api_key': KEY},
            self.admin.email,
        )

    def test_only_managers_can_use_it(self) -> None:
        self.login('support@ifinmail.test', role='support')
        self.assertEqual(self.client.get(reverse('accounts:assistant')).status_code, 403)
        page = self.client.get(reverse('accounts:marketplace'))
        self.assertNotContains(page, reverse('accounts:assistant'))
        self.assertEqual(
            self.client.post(reverse('accounts:assistant_ask'), {'question': 'x'}).status_code, 403
        )

    def test_not_connected_says_so_and_sends_nothing(self) -> None:
        page = self.client.get(reverse('accounts:assistant'))
        self.assertContains(page, 'No model is connected')
        self.assertContains(
            page, reverse('accounts:marketplace_plugin', kwargs={'plugin_id': 'assistant'})
        )
        response = self.client.post(
            reverse('accounts:assistant_ask'), {'question': 'hi'}, follow=True
        )
        self.assertContains(response, 'No model is connected')
        self.assertEqual(self.fake.requests, [])
        # The header offers the assistant to managers.
        self.assertContains(page, f'href="{reverse("accounts:assistant")}"')

    def test_ask_answer_and_what_was_sent(self) -> None:
        self.connect()
        self.fake.push(tool_call('system_health', {}))
        self.fake.push(answer('No PTR record.\nAsk your VPS provider.'))
        response = self.client.post(
            reverse('accounts:assistant_ask'), {'question': 'Why do mails bounce?'}, follow=True
        )
        self.assertContains(response, 'Why do mails bounce?')
        self.assertContains(response, 'No PTR record.<br>Ask your VPS provider.')
        self.assertContains(response, 'What was sent to 127.0.0.1: 1 check')
        self.assertContains(response, 'system_health')
        self.assertNotContains(response, 'hunter2')
        self.assertNotContains(response, KEY)
        conversation = AssistantConversation.objects.get()
        status = self.client.get(
            reverse('accounts:assistant_status', kwargs={'conversation_id': conversation.pk})
        )
        self.assertEqual(status.json(), {'status': 'idle'})

    def test_running_page_polls_and_failures_are_shown(self) -> None:
        self.connect()
        conversation = AssistantConversation.objects.create(
            user=self.admin.email, title='t', status=ConversationStatus.RUNNING
        )
        url = reverse(
            'accounts:assistant_conversation', kwargs={'conversation_id': conversation.pk}
        )
        page = self.client.get(url)
        self.assertContains(page, 'data-assistant-poll=')
        self.assertContains(page, 'ifinmail-assistant.js')
        AssistantConversation.objects.filter(pk=conversation.pk).update(
            status=ConversationStatus.FAILED, error='example.test: the API key was refused.'
        )
        self.assertContains(self.client.get(url), 'the API key was refused')
        other = self.login('other@ifinmail.test', superuser=True)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertTrue(other.is_superuser)

    def test_apply_a_draft_from_the_page(self) -> None:
        self.connect()
        self.fake.push(
            tool_call(
                'propose_plugin_settings',
                {'plugin_id': 'mailbox-care', 'settings': {'trash_days': 14}},
            )
        )
        self.fake.push(answer('Drafted.'))
        page = self.client.post(
            reverse('accounts:assistant_ask'),
            {'question': 'Empty trash after 2 weeks'},
            follow=True,
        )
        self.assertContains(page, 'Draft: Mailbox care')
        self.assertContains(page, 'Apply these settings')
        self.assertIsNone(InstallationService.get('mailbox-care'))
        step = next(m for m in AssistantConversation.objects.get().messages.all() if m.proposal)
        done = self.client.post(
            reverse('accounts:assistant_apply', kwargs={'message_id': step.pk}),
            {'conversation': str(step.conversation_id)},
            follow=True,
        )
        self.assertContains(done, 'Mailbox care installed.')
        self.assertContains(done, 'Applied')
        self.assertEqual(InstallationService.get('mailbox-care').settings['trash_days'], 14)

    def test_connection_test_button(self) -> None:
        self.connect()
        self.fake.push(tool_call('ping', {}))
        page = self.client.post(reverse('accounts:assistant_test'), follow=True)
        self.assertContains(page, 'can use tools')
        self.fake.push({'error': {'message': 'nope'}}, status=401)
        page = self.client.post(reverse('accounts:assistant_test'), follow=True)
        self.assertContains(page, 'Connection test failed')

    def test_the_key_never_reaches_the_plugin_page_and_an_empty_field_keeps_it(self) -> None:
        self.connect()
        url = reverse('accounts:marketplace_plugin', kwargs={'plugin_id': 'assistant'})
        page = self.client.get(url)
        self.assertNotContains(page, KEY)
        self.assertNotContains(page, 'plugin-secret:')
        self.assertContains(page, 'type="password"')
        self.assertContains(page, 'set — leave empty to keep')
        stored = PluginInstallation.objects.get(plugin_id='assistant').settings['api_key']
        row = PluginInstallation.objects.get(plugin_id='assistant')
        self.client.post(
            reverse('accounts:marketplace_plugin_action', kwargs={'plugin_id': 'assistant'}),
            {
                'action': 'configure',
                'revision': str(row.revision),
                'setting__base_url': self.fake.url,
                'setting__model': 'new-model',
                'setting__api_key': '',
                'setting__daily_tokens': '5000',
            },
        )
        row.refresh_from_db()
        self.assertEqual(row.settings['api_key'], stored)
        self.assertEqual(row.settings['model'], 'new-model')

    def test_system_health_offers_to_ask_once_a_model_is_connected(self) -> None:
        self.assertNotContains(
            self.client.get(reverse('accounts:system_health')), 'Ask the assistant'
        )
        self.connect()
        page = self.client.get(reverse('accounts:system_health'))
        self.assertContains(page, 'Ask the assistant')
        self.assertContains(page, '?q=System%20health%20says')
        prefilled = self.client.get(reverse('accounts:assistant') + '?q=Why+is+PTR+missing')
        self.assertContains(prefilled, 'Why is PTR missing')
