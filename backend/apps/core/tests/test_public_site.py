"""The public site: every page renders for a visitor, says only what is true, and stays quiet.

Pages are static copy, so these tests guard the properties that matter more than wording:
reachable without signing in, one heading level one, a main landmark, nothing fetched from a
third party, no gradients, and none of the claims the project cannot back.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from backend.config import public_pages

PAGES = (
    'landing',
    'features',
    'pricing',
    'security',
    'docs',
    'changelog',
    'about',
    'contact',
    'terms',
    'privacy',
)
ROOT = Path(__file__).resolve().parents[4]
SITE_TEMPLATES = ROOT / 'frontend' / 'templates' / 'site'
SITE_CSS = ROOT / 'frontend' / 'static' / 'css' / 'ifinmail-site.css'

# Things this project cannot honestly say. A reviewer adding copy meets this list first.
FORBIDDEN = (
    'SOC 2',
    'SOC2',
    'ISO 27001',
    'GDPR compliant',
    'HIPAA',
    '99.9',
    '$29',
    'PGP',
    'Premium',
    'enterprise-grade',
    'military',
)


@override_settings(SETUP_REQUIRED_REDIRECT=False)
class PublicSiteTests(TestCase):
    def get(self, name: str):
        response = self.client.get(reverse(name))
        self.assertEqual(response.status_code, 200, msg=name)
        return response

    def test_every_page_renders_without_signing_in(self) -> None:
        for name in PAGES:
            with self.subTest(page=name):
                self.get(name)

    def test_each_page_has_one_h1_and_a_main_landmark(self) -> None:
        for name in PAGES:
            with self.subTest(page=name):
                html = self.get(name).content.decode()
                self.assertEqual(len(re.findall(r'<h1[\s>]', html)), 1)
                self.assertEqual(html.count('<main '), 1)
                self.assertIn('id="content"', html)

    def test_pages_load_nothing_from_a_third_party(self) -> None:
        for name in PAGES:
            with self.subTest(page=name):
                html = self.get(name).content.decode()
                self.assertNotIn('fonts.googleapis.com', html)
                self.assertNotRegex(html, r'<(?:script|link|img)[^>]+(?:src|href)="https?://')

    def test_the_stylesheet_has_no_gradients_or_literal_colours(self) -> None:
        css = SITE_CSS.read_text(encoding='utf-8')
        self.assertNotIn('gradient(', css)
        self.assertNotRegex(css, r'#[0-9a-fA-F]{3,8}\b')
        self.assertNotRegex(css, r'rgba?\(')

    def test_fonts_are_shipped_with_the_stylesheet(self) -> None:
        css = SITE_CSS.read_text(encoding='utf-8')
        for name in re.findall(r"url\('\.\./fonts/([^']+)'\)", css):
            self.assertTrue((ROOT / 'frontend' / 'static' / 'fonts' / name).is_file(), name)

    def test_no_claim_the_project_cannot_back(self) -> None:
        for template in sorted(SITE_TEMPLATES.glob('*.html')):
            text = template.read_text(encoding='utf-8')
            for phrase in FORBIDDEN:
                # "What we do not claim" names certifications in order to deny them.
                if template.name == 'security.html' and phrase in ('SOC 2', 'ISO 27001'):
                    continue
                with self.subTest(template=template.name, phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_the_main_navigation_marks_the_current_page(self) -> None:
        for name in ('features', 'pricing', 'security', 'docs', 'changelog'):
            with self.subTest(page=name):
                html = self.get(name).content.decode()
                self.assertRegex(html, rf'href="{reverse(name)}" aria-current="page"')

    def test_docs_contents_point_at_sections_that_exist(self) -> None:
        html = self.get('docs').content.decode()
        targets = re.findall(r'<a href="#([a-z-]+)"', html)
        self.assertGreaterEqual(len(targets), 6)
        for target in targets:
            with self.subTest(anchor=target):
                self.assertIn(f'id="{target}"', html)

    def test_terms_and_privacy_carry_their_date(self) -> None:
        for name in ('terms', 'privacy'):
            with self.subTest(page=name):
                self.assertContains(self.get(name), f'{public_pages.LEGAL_UPDATED.year}')


class ChangelogTests(TestCase):
    TEXT = (
        '# Changelog\n\n## v0.0.3\n- **Third** thing\n- Fourth\n\n'
        '## v0.0.2\nSecond release.\n\n## v0.0.1\n- First\n'
    )

    def test_releases_are_split_newest_first(self) -> None:
        releases = public_pages.parse_changelog(self.TEXT)
        self.assertEqual([r['version'] for r in releases], ['v0.0.3', 'v0.0.2', 'v0.0.1'])
        self.assertEqual(releases[0]['anchor'], 'v0-0-3')
        self.assertIn('Third', releases[0]['body'])
        self.assertNotIn('Second', releases[0]['body'])

    def test_limit_and_empty_input(self) -> None:
        self.assertEqual(len(public_pages.parse_changelog(self.TEXT, limit=2)), 2)
        self.assertEqual(public_pages.parse_changelog(''), [])
        self.assertEqual(public_pages.parse_changelog('no headings here'), [])

    def test_the_page_shows_the_repository_changelog(self) -> None:
        with override_settings(SETUP_REQUIRED_REDIRECT=False):
            response = self.client.get(reverse('changelog'))
        newest = public_pages.changelog_releases()[0]['version']
        self.assertContains(response, newest)
        self.assertContains(response, 'ifinmail-md')

    def test_a_missing_file_gives_an_empty_page_not_an_error(self) -> None:
        public_pages._changelog.cache_clear()
        with override_settings(BASE_DIR=Path('/nonexistent'), SETUP_REQUIRED_REDIRECT=False):
            response = self.client.get(reverse('changelog'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No changelog on this server')
        public_pages._changelog.cache_clear()
