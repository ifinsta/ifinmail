"""The assistant's website tools: it understands each page, drafts text, and a person applies it."""

from __future__ import annotations

import json

from backend.apps.core.assistant.services import ConversationService, tools
from backend.apps.core.assistant.tests.fake_provider import answer, tool_call
from backend.apps.core.assistant.tests.test_assistant import ADMIN, _Base
from backend.apps.core.assistant.types import AssistantError
from backend.apps.core.plugins.services import InstallationService
from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.website.services import content, guide
from backend.apps.core.website.types import KEYS, PLUGIN_ID


class WebsiteToolsTests(_Base):
    def run_tool(self, name: str, arguments: dict):  # noqa: ANN201
        self.connect()
        self.fake.push(tool_call(name, arguments))
        self.fake.push(answer('done'))
        conversation = self.ask('Brand the website')
        return [m for m in ConversationService.messages(conversation) if m.role == 'tool'][-1]

    def test_every_page_has_a_guide_with_what_is_at_stake(self) -> None:
        self.assertEqual(set(guide.GUIDES), set(KEYS))
        for key, g in guide.GUIDES.items():
            with self.subTest(page=key):
                self.assertIn(g.risk, ('low', 'medium', 'high'))
                for text in (g.purpose, g.audience, g.layout, g.stakes, g.write):
                    self.assertGreater(len(text), 20)
                self.assertTrue(g.typical)
        for key in ('terms', 'privacy', 'security', 'pricing', 'contact'):
            self.assertEqual(guide.GUIDES[key].risk, 'high', key)

    def test_the_tools_are_registered_and_none_changes_state_on_its_own(self) -> None:
        names = {t.name: t for t in tools.all_tools()}
        for name in ('website_overview', 'website_page_text', 'propose_website_page'):
            self.assertIn(name, names)
        self.assertEqual(names['propose_website_page'].tier, 'propose')
        self.assertEqual(names['website_overview'].tier, 'read')

    def test_overview_gives_layout_stakes_and_state_for_every_page(self) -> None:
        step = self.run_tool('website_overview', {})
        data = json.loads(step.content)
        self.assertEqual([p['page'] for p in data['pages']], list(KEYS))
        terms = next(p for p in data['pages'] if p['page'] == 'terms')
        self.assertEqual(terms['risk'], 'high')
        self.assertEqual(terms['mode'], 'standard')
        self.assertNotIn('truncated', step.content)
        self.assertIn('Markdown', data['custom_page_layout'])
        self.assertIn('heading', data['limits_in_characters'])
        self.assertFalse(data['plugin_installed'])

    def test_every_page_fits_in_one_tool_result(self) -> None:
        from backend.apps.core.assistant.services.redaction import redact
        from backend.apps.core.assistant.types import MAX_TOOL_OUTPUT_CHARS
        from backend.apps.core.assistant.services.tools import ToolContext
        from backend.apps.core.website import assistant_handlers as handlers

        context = ToolContext(user=ADMIN)
        for key in KEYS:
            with self.subTest(page=key):
                text = redact(handlers._page_text({'page': key}, context))
                self.assertLess(len(text), MAX_TOOL_OUTPUT_CHARS - 40, key)
                self.assertNotIn('[truncated', text)
        self.assertLess(len(redact(handlers._overview({}, context))), 8000)

    def test_page_text_returns_the_standard_text_and_outline(self) -> None:
        step = self.run_tool('website_page_text', {'page': 'features'})
        data = json.loads(step.content)
        self.assertIn('Everything a mail server needs', data['standard']['heading'])
        self.assertIn('Mail', data['standard']['outline'])
        self.assertIn('## Mail', data['standard']['text'])
        self.assertEqual(data['risk'], 'medium')
        self.assertIn('Over-claiming', data['at_stake'])
        self.assertIsNone(data['saved_custom_text'])

    def test_a_draft_changes_nothing_until_applied_then_installs_and_publishes(self) -> None:
        step = self.run_tool(
            'propose_website_page',
            {
                'page': 'contact',
                'heading': 'Contact Contoso IT',
                'lede': 'We answer within one working day.',
                'body': '## Help\n\nEmail [it@contoso.example](mailto:it@contoso.example).',
                'mode': 'custom',
            },
        )
        self.assertIsNotNone(step.proposal)
        self.assertEqual(step.proposal['kind'], 'website_page')
        self.assertFalse(step.proposal['installed'])  # applying installs the plugin
        self.assertFalse(content.get('contact').usable)
        self.assertIsNone(InstallationService.get(PLUGIN_ID))
        labels = [c['setting'] for c in step.proposal['changes']]
        self.assertIn('Heading', labels)
        self.assertIn('Visitors see', labels)

        summary = ConversationService.apply_proposal(ADMIN, str(step.pk))
        self.assertIn('Contact page saved and the page is now custom', summary)
        self.assertEqual(content.get('contact').heading, 'Contact Contoso IT')
        self.assertEqual(InstallationService.get(PLUGIN_ID).settings['mode_contact'], 'custom')
        html = self.client.get('/contact/').content.decode()
        self.assertIn('<h1>Contact Contoso IT</h1>', html)
        self.assertTrue(AuditService.has('assistant_proposal_applied', user=ADMIN))
        with self.assertRaisesMessage(AssistantError, 'already applied'):
            ConversationService.apply_proposal(ADMIN, str(step.pk))

    def test_text_without_a_mode_is_saved_but_not_shown(self) -> None:
        InstallationService.install(PLUGIN_ID, {}, ADMIN)
        step = self.run_tool('propose_website_page', {'page': 'about', 'heading': 'Us', 'body': 'x'})
        self.assertTrue(step.proposal['installed'])
        summary = ConversationService.apply_proposal(ADMIN, str(step.pk))
        self.assertIn('not shown to visitors until its mode is Custom', summary)
        self.assertEqual(self.client.get('/about/').status_code, 200)
        self.assertNotIn('<h1>Us</h1>', self.client.get('/about/').content.decode())

    def test_invalid_drafts_are_refused_with_the_reasons(self) -> None:
        step = self.run_tool(
            'propose_website_page',
            {'page': 'about', 'heading': 'Us', 'cta_label': 'Go', 'cta_url': 'javascript:alert(1)'},
        )
        self.assertIsNone(step.proposal)
        data = json.loads(step.content)
        self.assertEqual(data['error'], 'the draft is not valid')
        self.assertIn('cta_url', data['problems'])

    def test_unknown_pages_and_fields_never_reach_the_handler(self) -> None:
        step = self.run_tool('propose_website_page', {'page': 'admin', 'heading': 'x'})
        self.assertIn('page must be one of', step.content)
        step = self.run_tool('propose_website_page', {'page': 'about', 'script': 'x'})
        self.assertIn('unknown argument', step.content)

    def test_a_page_edited_since_the_draft_is_not_overwritten(self) -> None:
        step = self.run_tool('propose_website_page', {'page': 'about', 'heading': 'Draft', 'body': 'a'})
        content.save('about', {'heading': 'Typed by a person', 'body': 'b'}, ADMIN)
        with self.assertRaisesMessage(AssistantError, 'changed since this draft'):
            ConversationService.apply_proposal(ADMIN, str(step.pk))
        self.assertEqual(content.get('about').heading, 'Typed by a person')

    def test_a_forged_proposal_with_unsafe_content_is_refused_on_apply(self) -> None:
        from backend.apps.core.assistant.models import AssistantMessage

        step = self.run_tool('propose_website_page', {'page': 'about', 'heading': 'Us', 'body': 'a'})
        bad = {**step.proposal, 'content': {**step.proposal['content'], 'cta_label': 'x', 'cta_url': 'javascript:1'}}
        AssistantMessage.objects.filter(pk=step.pk).update(proposal=bad)
        with self.assertRaisesMessage(AssistantError, 'no longer validates'):
            ConversationService.apply_proposal(ADMIN, str(step.pk))
