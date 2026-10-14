"""The Website pages plugin: pages on/off/custom, menus, footer, cross-links, and the editor."""

from __future__ import annotations

from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.core.plugins.services import InstallationService
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.core.website.services import content, policy, starter
from backend.apps.core.website.services import site as website_site
from backend.apps.core.website.types import KEYS, PAGES, ContentError

MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'
PLUGIN = 'website-pages'
PAGE_URLS = {p.key: reverse(p.key) for p in PAGES}


def modes(**chosen: str) -> dict[str, str]:
    return {f'mode_{k}': v for k, v in chosen.items()}


class PolicyTests(SimpleTestCase):
    def test_without_the_plugin_everything_is_as_shipped(self) -> None:
        p = policy.from_values({})
        self.assertFalse(p.installed)
        self.assertTrue(all(p.mode(k) == 'standard' for k in KEYS))
        self.assertTrue(p.powered_by and p.project_links)

    def test_values_parse_and_junk_is_ignored(self) -> None:
        p = policy.from_values(
            {'modes': 'pricing=off,docs=custom,nope=off,about=weird', 'powered_by': 'no', 'tagline': ' Hi '}
        )
        self.assertEqual((p.mode('pricing'), p.mode('docs'), p.mode('about')), ('off', 'custom', 'standard'))
        self.assertFalse(p.powered_by)
        self.assertEqual(p.tagline, 'Hi')


class SiteTests(SimpleTestCase):
    def site(self, **values: str) -> website_site.Site:
        return website_site.Site(policy.from_values(values), {'repo_url': 'https://git.example/x'})

    def test_menus_follow_the_pages_that_are_on(self) -> None:
        site = self.site(modes='pricing=off,changelog=off,download=off')
        self.assertEqual([l.key for l in site.nav_links], ['features', 'security', 'docs'])
        titles = {c.title: [l.key for l in c.links] for c in site.footer_columns}
        self.assertNotIn('pricing', titles['Product'])

    def test_project_links_can_be_hidden(self) -> None:
        shown = [l.url for c in self.site().footer_columns for l in c.links if l.external]
        self.assertIn('https://git.example/x', shown)
        hidden = self.site(project_links='no')
        self.assertEqual([l for c in hidden.footer_columns for l in c.links if l.external], [])

    def test_a_column_with_nothing_in_it_is_dropped(self) -> None:
        site = self.site(modes='terms=off,privacy=off', project_links='no')
        self.assertNotIn('Legal', [c.title for c in site.footer_columns])

    def test_get_started_needs_the_install_guide(self) -> None:
        self.assertIsNotNone(self.site().get_started)
        self.assertIsNone(self.site(modes='docs=off').get_started)

    def test_the_home_link_goes_to_sign_in_when_the_home_page_is_off(self) -> None:
        self.assertEqual(self.site().home_url, reverse('landing'))
        self.assertEqual(self.site(modes='landing=off').home_url, reverse('accounts:login'))


class ContentTests(MailTablesTestCase):
    def test_save_read_and_clear(self) -> None:
        saved = content.save('about', {'heading': ' Who we are ', 'body': '## Us\n\nHello'}, 'a@x.test')
        self.assertEqual(saved.heading, 'Who we are')
        self.assertEqual(content.get('about').body, '## Us\n\nHello')
        self.assertEqual(content.has_text(), {'about'})
        content.clear('about', 'a@x.test')
        self.assertFalse(content.get('about').usable)

    def test_limits_and_shapes_are_refused_with_a_message_per_field(self) -> None:
        with self.assertRaises(ContentError) as caught:
            content.clean(
                {
                    'heading': 'x' * 500,
                    'title': 'two\nlines',
                    'cta_label': 'Go',
                    'cta_url': 'javascript:alert(1)',
                    'body': 'ok',
                }
            )
        self.assertEqual(set(caught.exception.errors), {'heading', 'title', 'cta_url'})
        with self.assertRaises(ContentError):
            content.clean({'cta_label': 'Go', 'cta_url': ''})  # a button needs both
        with self.assertRaises(ContentError):
            content.clean({'body': 'x' * 20001})

    def test_an_unknown_page_is_refused(self) -> None:
        with self.assertRaises(ContentError):
            content.save('admin', {'heading': 'x'}, 'a@x.test')


class PublicPagesTests(MailTablesTestCase):
    def install(self, **settings: object) -> None:
        InstallationService.install(PLUGIN, settings, 'a@x.test')

    def test_without_the_plugin_nothing_changes(self) -> None:
        for key, url in PAGE_URLS.items():
            with self.subTest(page=key):
                self.assertEqual(self.client.get(url).status_code, 200)
        body = self.client.get(PAGE_URLS['landing']).content.decode()
        self.assertIn('Powered by', body)

    def test_installed_with_defaults_is_the_same_site(self) -> None:
        self.install()
        for key, url in PAGE_URLS.items():
            with self.subTest(page=key):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_a_page_that_is_off_is_gone_everywhere(self) -> None:
        self.install(**modes(pricing='off', changelog='off'))
        self.assertEqual(self.client.get(PAGE_URLS['pricing']).status_code, 404)
        self.assertEqual(self.client.get(PAGE_URLS['changelog']).status_code, 404)
        for key in ('landing', 'features', 'about', 'docs'):
            html = self.client.get(PAGE_URLS[key]).content.decode()
            self.assertNotIn(f'href="{PAGE_URLS["pricing"]}"', html, key)
            self.assertNotIn(f'href="{PAGE_URLS["changelog"]}"', html, key)

    def test_the_home_page_off_sends_visitors_to_sign_in(self) -> None:
        self.install(**modes(landing='off'))
        response = self.client.get(PAGE_URLS['landing'])
        self.assertRedirects(response, reverse('accounts:login'), fetch_redirect_response=False)

    def test_every_page_off_leaves_nothing_to_link_to(self) -> None:
        self.install(**modes(**{k: 'off' for k in KEYS}), powered_by=False, project_links=False)
        self.assertEqual(self.client.get(reverse('accounts:login')).status_code, 200)
        login = self.client.get(reverse('accounts:login')).content.decode()
        for url in PAGE_URLS.values():
            if url != '/':
                self.assertNotIn(f'href="{url}"', login)

    def test_custom_text_is_shown_in_the_standard_layout(self) -> None:
        content.save(
            'features',
            {
                'heading': 'What Contoso Mail does',
                'lede': 'Mail for Contoso.',
                'body': '## One\n\n- fast\n- safe\n\n<script>x</script>',
                'cta_label': 'Sign in',
                'cta_url': '/accounts/login/',
                'title': 'Contoso features',
                'description': 'About Contoso mail',
            },
            'a@x.test',
        )
        self.install(**modes(features='custom'))
        html = self.client.get(PAGE_URLS['features']).content.decode()
        self.assertIn('<h1>What Contoso Mail does</h1>', html)
        self.assertIn('<li>fast</li>', html)
        self.assertIn('&lt;script&gt;x&lt;/script&gt;', html)
        self.assertNotIn('Everything a mail server needs', html)
        self.assertIn('<title>Contoso features', html)
        self.assertIn('content="About Contoso mail"', html)
        self.assertIn('ifinmail-site-header', html)  # same chrome

    def test_custom_with_no_text_shows_the_standard_page(self) -> None:
        self.install(**modes(features='custom'))
        html = self.client.get(PAGE_URLS['features']).content.decode()
        self.assertIn('Everything a mail server needs', html)

    def test_uninstalling_brings_the_standard_site_back_and_keeps_the_text(self) -> None:
        content.save('about', {'heading': 'Us', 'body': 'x'}, 'a@x.test')
        self.install(**modes(about='custom', pricing='off'))
        self.assertEqual(self.client.get(PAGE_URLS['pricing']).status_code, 404)
        InstallationService.uninstall(PLUGIN, 'a@x.test')
        self.assertEqual(self.client.get(PAGE_URLS['pricing']).status_code, 200)
        self.assertTrue(content.get('about').usable)

    def test_footer_choices(self) -> None:
        self.install(powered_by=False, project_links=False, tagline='Contoso secure mail')
        html = self.client.get(PAGE_URLS['features']).content.decode()
        self.assertNotIn('Powered by', html)
        self.assertIn('Contoso secure mail', html)
        self.assertNotIn('github.com', html)
        InstallationService.configure(PLUGIN, {'footer_note': 'Contoso Ltd, reg. 123'}, 'a@x.test')
        html = self.client.get(PAGE_URLS['features']).content.decode()
        self.assertIn('Contoso Ltd, reg. 123', html)

    def test_custom_text_is_escaped_in_every_field(self) -> None:
        content.save(
            'terms',
            {'heading': '<b>h</b>', 'lede': '<i>l</i>', 'title': '<u>t</u>', 'body': '<s>b</s>'},
            'a@x.test',
        )
        self.install(**modes(terms='custom'))
        html = self.client.get(PAGE_URLS['terms']).content.decode()
        for raw in ('<b>h</b>', '<i>l</i>', '<u>t</u>', '<s>b</s>'):
            self.assertNotIn(raw, html)

    def test_preview_needs_a_signed_in_administrator(self) -> None:
        content.save('about', {'heading': 'Us', 'body': 'x'}, 'a@x.test')
        self.install(**modes(about='off'))
        self.assertEqual(self.client.get(PAGE_URLS['about'] + '?preview=custom').status_code, 404)
        admin = MailUser.objects.create_user('root@ifinmail.test', 'Correct-Horse-9', is_staff=True)
        self.client.force_login(admin, backend=MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()
        response = self.client.get(PAGE_URLS['about'] + '?preview=custom')
        self.assertContains(response, 'Preview')
        self.assertEqual(self.client.get(PAGE_URLS['about']).status_code, 404)


class StarterTests(MailTablesTestCase):
    def test_the_standard_text_becomes_editable_markdown(self) -> None:
        from backend.config import public_pages
        from django.test import RequestFactory

        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        html = public_pages.standard_html(request, 'features')
        start = starter.convert(html)
        self.assertEqual(start.heading, 'Everything a mail server needs, and nothing it does not.')
        self.assertIn('Each part below ships in the box', start.lede)
        self.assertIn('## Mail', start.body)
        self.assertIn('- **Send and receive with any client.**', start.body)
        self.assertNotIn('Read the install guide', start.body)  # buttons are not text
        self.assertNotIn('<', start.body)
        self.assertTrue(start.title)
        self.assertTrue(start.description)

    def test_every_standard_page_converts(self) -> None:
        from backend.config import public_pages
        from django.test import RequestFactory

        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        for key in KEYS:
            with self.subTest(page=key):
                start = starter.convert(public_pages.standard_html(request, key))
                self.assertTrue(start.heading or start.body)
                content.clean(start.__dict__ | {'cta_label': '', 'cta_url': ''})


class EditorTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        admin = MailUser.objects.create_user('root@ifinmail.test', 'Correct-Horse-9', is_staff=True)
        self.client.force_login(admin, backend=MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def test_the_overview_lists_every_page_and_says_when_the_plugin_is_missing(self) -> None:
        response = self.client.get(reverse('accounts:website_pages'))
        self.assertContains(response, 'Every page shows its standard text')
        for page in PAGES:
            self.assertContains(response, PAGE_URLS[page.key])

    def test_write_save_and_remove(self) -> None:
        url = reverse('accounts:website_page', args=['about'])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {'action': 'save', 'heading': 'Us', 'body': 'Hello', 'cta_label': '', 'cta_url': ''})
        self.assertRedirects(response, url)
        self.assertEqual(content.get('about').heading, 'Us')
        self.client.post(url, {'action': 'clear'})
        self.assertFalse(content.get('about').usable)

    def test_errors_are_shown_next_to_the_field_and_nothing_is_saved(self) -> None:
        url = reverse('accounts:website_page', args=['about'])
        response = self.client.post(url, {'action': 'save', 'heading': 'Us', 'cta_url': 'javascript:x', 'cta_label': 'Go'})
        self.assertContains(response, 'Use an https')
        self.assertContains(response, 'value="Us"')  # what was typed is kept
        self.assertFalse(content.get('about').usable)

    def test_start_from_the_standard_text_fills_the_form_without_saving(self) -> None:
        url = reverse('accounts:website_page', args=['features'])
        response = self.client.post(url, {'action': 'starter'})
        self.assertContains(response, 'Everything a mail server needs')
        self.assertFalse(content.get('features').usable)

    def test_unknown_pages_and_outsiders(self) -> None:
        self.assertEqual(self.client.get('/accounts/website/nope/').status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('accounts:website_pages')).status_code, 302)


class PolicyCacheTests(MailTablesTestCase):
    def test_a_public_request_reads_the_policy_from_the_cache(self) -> None:
        from django.core.cache import cache
        from django.test import override_settings

        locmem = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
        with override_settings(CACHES=locmem):
            cache.clear()
            InstallationService.install(PLUGIN, modes(pricing='off'), 'a@x.test')
            self.assertIn('"pricing": "off"', cache.get(policy.CACHE_KEY))
            with self.assertNumQueries(0):
                self.assertEqual(policy.current().mode('pricing'), 'off')
            InstallationService.uninstall(PLUGIN, 'a@x.test')
            self.assertEqual(policy.current().mode('pricing'), 'standard')

    def test_a_flushed_cache_is_rebuilt_from_the_plugin(self) -> None:
        from django.core.cache import cache
        from django.test import override_settings

        locmem = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
        with override_settings(CACHES=locmem):
            InstallationService.install(PLUGIN, modes(about='off'), 'a@x.test')
            cache.clear()
            self.assertEqual(policy.current().mode('about'), 'off')
