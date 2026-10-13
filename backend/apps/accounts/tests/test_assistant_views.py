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
from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.plugins.models import PluginInstallation
from backend.apps.core.plugins.services import InstallationService
from backend.apps.core.tests.mail_base import MailTablesTestCase

GOOD = 'Correct-Horse-9'


class AssistantBase(MailTablesTestCase):
    """A signed-in owner, a scripted model server and the assistant plugin on demand."""

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


class AssistantPageTests(AssistantBase):
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
        self.assertContains(response, '<p>No PTR record.\nAsk your VPS provider.</p>')
        self.assertContains(response, 'Checked 1 thing · sent to 127.0.0.1')
        self.assertContains(response, 'system_health')
        self.assertNotContains(response, 'hunter2')
        self.assertNotContains(response, KEY)
        conversation = AssistantConversation.objects.get()
        status = self.client.get(
            reverse('accounts:assistant_status', kwargs={'conversation_id': conversation.pk})
        )
        self.assertEqual(status.json(), {'status': 'idle', 'messages': 4})

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

    def test_answers_are_rendered_as_markdown_and_never_as_html(self) -> None:
        self.connect()
        reply = (
            '## Findings\n\n1. **No PTR** for `203.0.113.5`\n2. DMARC is [missing](https://dmarc.org)\n\n'
            '| Check | State |\n|---|---|\n| PTR | fail |\n\n```bash\nmake update\n```\n\n'
            '<script>alert(1)</script> ![x](https://attacker.test/p.png)'
        )
        self.fake.push(answer(reply))
        page = self.client.post(
            reverse('accounts:assistant_ask'), {'question': 'Summarise'}, follow=True
        )
        for expected in (
            '<h4 class="ifinmail-md-h">Findings</h4>',
            '<strong>No PTR</strong>',
            '<code>203.0.113.5</code>',
            '<a href="https://dmarc.org"',
            '<table>',
            'data-lang="bash"',
            '&lt;script&gt;alert(1)&lt;/script&gt;',
        ):
            self.assertContains(page, expected)
        self.assertNotContains(page, '<script>alert(1)')
        self.assertNotContains(page, '<img')
        self.assertContains(page, 'data-assistant-copy=')  # the raw answer, for the Copy button

    def test_delete_a_conversation(self) -> None:
        self.connect()
        self.fake.push(answer('ok'))
        self.client.post(reverse('accounts:assistant_ask'), {'question': 'hello'})
        conversation = AssistantConversation.objects.get()
        url = reverse('accounts:assistant_delete', kwargs={'conversation_id': conversation.pk})
        # Someone else cannot delete it; a running one cannot be deleted.
        other = self.login('other@ifinmail.test', superuser=True)
        self.client.post(url)
        self.assertEqual(AssistantConversation.objects.count(), 1)
        self.client.force_login(self.admin, backend='django.contrib.auth.backends.ModelBackend')
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()
        AssistantConversation.objects.filter(pk=conversation.pk).update(
            status=ConversationStatus.RUNNING
        )
        self.client.post(url)
        self.assertEqual(AssistantConversation.objects.count(), 1)
        AssistantConversation.objects.filter(pk=conversation.pk).update(
            status=ConversationStatus.IDLE
        )
        response = self.client.post(url, follow=True)
        self.assertContains(response, 'Conversation deleted.')
        self.assertEqual(AssistantConversation.objects.count(), 0)
        self.assertTrue(AuditService.has('assistant_conversation_deleted', user=self.admin.email))
        self.assertTrue(other.is_superuser)

    def test_start_page_offers_questions_and_lists_conversations(self) -> None:
        self.connect()
        page = self.client.get(reverse('accounts:assistant'))
        self.assertContains(page, 'How can I help with this server?')
        self.assertContains(page, 'Is anything wrong with this server?')
        self.assertContains(page, 'Tokens today: 0 of 200,000')
        self.fake.push(answer('ok'))
        self.client.post(reverse('accounts:assistant_ask'), {'question': 'Why is it slow?'})
        page = self.client.get(reverse('accounts:assistant'))
        self.assertContains(page, 'Why is it slow?')
        self.assertContains(page, 'data-assistant-rail')

    def test_page_is_a_chat_workspace_with_hooks_for_in_place_updates(self) -> None:
        self.connect()
        empty = self.client.get(reverse('accounts:assistant')).content.decode()
        # Greeting, composer and suggestions share one empty-state container.
        self.assertIn('ifinmail-assistant-chat--empty', empty)
        self.assertIn('data-assistant-composer', empty)
        self.assertEqual(empty.count('data-assistant-ask'), 1 + 8)  # composer + 8 suggestions
        self.assertIn('data-assistant-scroll', empty)
        self.assertNotIn('ifinmail-assistant-chat--empty', self._with_conversation())

    def _with_conversation(self) -> str:
        self.fake.push(answer('ok'))
        self.client.post(reverse('accounts:assistant_ask'), {'question': 'Why is it slow?'})
        conversation = AssistantConversation.objects.get()
        return self.client.get(
            reverse('accounts:assistant_conversation', kwargs={'conversation_id': conversation.pk})
        ).content.decode()

    def test_everything_still_works_as_plain_forms_without_the_script(self) -> None:
        self.connect()
        page = self._with_conversation()
        # The composer and every suggestion are ordinary POST forms with a CSRF token.
        self.assertIn(f'action="{reverse("accounts:assistant_ask")}"', page)
        self.assertIn('csrfmiddlewaretoken', page)
        self.assertIn('<textarea id="as-question" name="question"', page)
        # Each conversation in the list can be deleted from the list itself.
        conversation = AssistantConversation.objects.get()
        delete = reverse('accounts:assistant_delete', kwargs={'conversation_id': conversation.pk})
        self.assertIn(f'action="{delete}"', page)

    def test_history_is_grouped_by_recency(self) -> None:
        from datetime import timedelta

        self.connect()
        now = timezone.now()
        for title, age in (
            ('today one', 0),
            ('yesterday one', 1),
            ('last week', 5),
            ('ancient', 90),
        ):
            row = AssistantConversation.objects.create(user=self.admin.email, title=title)
            AssistantConversation.objects.filter(pk=row.pk).update(
                updated_at=now - timedelta(days=age)
            )
        page = self.client.get(reverse('accounts:assistant')).content.decode()
        labels = [
            page.index(label)
            for label in ('>Today<', '>Yesterday<', '>Previous 7 days<', '>Older<')
        ]
        self.assertEqual(labels, sorted(labels))
        self.assertLess(page.index('today one'), page.index('yesterday one'))
        self.assertLess(page.index('last week'), page.index('ancient'))
        self.assertNotIn('>Previous 30 days<', page)  # empty groups are not shown


class AssistantApiKnowledgeTests(AssistantBase):
    """The assistant knows the API integrations: what exists, what is set up, what is unsafe."""

    def run_tool(self, name: str, **arguments: object) -> dict:
        from backend.apps.core.assistant.services import tools

        tool = tools.get(name)
        assert tool is not None, f'{name} is not registered'
        self.assertIsNone(tool.check_arguments(dict(arguments)))
        return tool.handler(dict(arguments), tools.ToolContext(user=self.admin.email))

    def make_key(self, name: str, scopes: list[str], **kwargs: object):
        from backend.apps.accounts.services.tokens import TokenService

        return TokenService.create(self.admin, name, scopes, expires_in_days=30, **kwargs)

    def test_both_tools_are_read_tier_and_the_prompt_points_at_them(self) -> None:
        from backend.apps.core.assistant.services import agent, tools
        from backend.apps.core.assistant.types import ToolTier

        for name in ('api_overview', 'api_keys'):
            tool = tools.get(name)
            assert tool is not None
            self.assertEqual(tool.tier, ToolTier.READ)
            self.assertIn(name, agent.SYSTEM_PROMPT)

    def test_overview_is_the_live_contract_not_a_copy(self) -> None:
        from backend.apps.accounts.api import api
        from backend.apps.accounts.viewsets.contract import operations

        overview = self.run_tool('api_overview')
        live = operations(api)
        self.assertEqual(len(overview['operations']), len(live))
        listed = {(o['method'], o['path']): o for o in overview['operations']}
        self.assertEqual(listed[('GET', '/api/v1/mailboxes')]['needs_scope'], 'mail.manage')
        self.assertEqual(listed[('GET', '/api/v1/health')]['needs_scope'], 'none (anonymous)')
        self.assertIn('dns.manage', overview['scopes_in_use'])
        self.assertEqual(overview['base_path'], '/api/v1/')
        self.assertIn('/api/<path>', overview['old_paths_that_redirect'])
        self.assertIn('Settings > API keys', overview['authentication']['create_a_key'])

    def test_overview_can_be_narrowed(self) -> None:
        narrowed = self.run_tool('api_overview', area='aliases')
        self.assertTrue(narrowed['operations'])
        self.assertTrue(all('aliases' in o['path'] for o in narrowed['operations']))

    def test_keys_report_findings_and_never_a_secret(self) -> None:
        from datetime import timedelta

        from backend.apps.accounts.models import APIToken

        broad, broad_token = self.make_key('Billing', ['mail.manage'])
        locked, _ = self.make_key('Monitor', ['audit.view'], allowed_networks=['203.0.113.0/24'])
        old, _ = self.make_key('Forgotten', ['console.access'])
        APIToken.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=60))
        APIToken.objects.filter(pk=locked.pk).update(expires_at=timezone.now() + timedelta(days=3))
        report = self.run_tool('api_keys')
        text = str(report)
        self.assertEqual(report['count'], 3)
        by_name = {k['name']: k for k in report['keys']}
        self.assertIn('works from any address', ' '.join(by_name['Billing']['notes']))
        self.assertNotIn('works from any address', ' '.join(by_name['Monitor']['notes']))
        self.assertIn('expires in', ' '.join(by_name['Monitor']['notes']))
        self.assertIn('never used', ' '.join(by_name['Forgotten']['notes']))
        self.assertIn(f'ifm_{broad.prefix}', text)
        self.assertNotIn(broad_token.split('.', 2)[2], text)
        self.assertNotIn(broad.token_hash, text)
        self.assertEqual(by_name['Monitor']['only_from_networks'], ['203.0.113.0/24'])

    def test_keys_report_failed_sign_ins_and_changes_made_with_keys(self) -> None:
        AuditService.record(
            action='api_auth_failed',
            user='api:ifm_abcdefghijkl',
            detail='bad_secret from 198.51.100.7',
            severity='warning',
        )
        AuditService.record(
            action='api_mailbox_created', user='api:ifm_abcdefghijkl (a@b.test)', detail='x@b.test'
        )
        report = self.run_tool('api_keys')
        self.assertEqual(report['failed_sign_ins_last_24h'], 1)
        self.assertIn('bad_secret', report['recent_failures'][0]['why'])
        self.assertEqual(
            report['recent_changes_made_with_keys'][0]['action'], 'api_mailbox_created'
        )

    def test_redaction_masks_api_secrets_wherever_they_appear(self) -> None:
        from backend.apps.core.assistant.services.redaction import redact

        secret = 'ifs_' + 'A1b2C3d4' * 5
        bearer = 'ifm.abcdefghijkl.' + secret
        text = redact({'note': f'use {secret} or {bearer}', 'fine': 'ifm_abcdefghijkl'})
        self.assertNotIn(secret, text)
        self.assertNotIn('abcdefghijkl.ifs_', text)
        self.assertIn('ifm_abcdefghijkl', text)  # the key id is public and stays

    def test_an_api_question_is_answered_through_the_tools_end_to_end(self) -> None:
        self.connect()
        _, token = self.make_key('Billing', ['mail.manage'])
        self.fake.push(tool_call('api_overview', {'area': 'mailboxes'}))
        self.fake.push(tool_call('api_keys', {}, 'call_2'))
        self.fake.push(answer('Use `POST /api/v1/mailboxes` with the `mail.manage` scope.'))
        response = self.client.post(
            reverse('accounts:assistant_ask'),
            {'question': 'How can a program create mailboxes?'},
            follow=True,
        )
        self.assertContains(response, 'Checked 2 things')
        self.assertContains(response, 'api_overview')
        self.assertContains(response, 'api_keys')
        sent = self.fake.sent_text()
        self.assertIn('/api/v1/mailboxes', sent)
        self.assertIn('Billing', sent)
        self.assertNotIn(token.split('.', 2)[2], sent)
        self.assertNotIn(token, sent)
