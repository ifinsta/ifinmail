"""URLs are variables, and the domain people are on is the authority.

A template, script or view that spells out a path (``/accounts/login/``) or a host breaks the day
a route moves or the server is installed under another domain. These tests scan the source for
those mistakes and check the one helper (``backend.config.site_url``) that decides which domain a
link that leaves the page carries.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.http import HttpRequest
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import get_resolver, reverse

from backend.config import site_url

ROOT = Path(settings.BASE_DIR)
TEMPLATES = ROOT / 'frontend' / 'templates'
JS = ROOT / 'frontend' / 'static' / 'js'
BACKEND = ROOT / 'backend'

# External references that are not "this server": XML namespaces, the font host, a link to the
# Nextcloud app store shown on the setup page.
ALLOWED_EXTERNAL = (
    'www.w3.org',
    'fonts.googleapis.com',
    'fonts.gstatic.com',
    'apps.nextcloud.com',
)


def source_files(base: Path, suffixes: tuple[str, ...]) -> list[Path]:
    return [
        p
        for p in sorted(base.rglob('*'))
        if p.suffix in suffixes and '__pycache__' not in p.parts and 'mydoc' not in p.parts
    ]


class TemplateUrlTests(SimpleTestCase):
    def test_no_template_spells_out_an_internal_path(self) -> None:
        pattern = re.compile(
            r"""(?:href|action|src|data-[\w-]*url|data-path|formaction)=["'](/[^"']*)["']"""
        )
        found = [
            f'{p.relative_to(TEMPLATES)}: {m.group(0)}'
            for p in source_files(TEMPLATES, ('.html', '.txt'))
            for m in pattern.finditer(p.read_text(encoding='utf-8', errors='ignore'))
            if '{%' not in m.group(1) and '{{' not in m.group(1)
        ]
        self.assertEqual(found, [], 'use {% url %} or {% static %}')

    def test_no_template_names_a_host_of_its_own(self) -> None:
        pattern = re.compile(r'https?://([A-Za-z0-9.-]+)')
        found: list[str] = []
        for p in source_files(TEMPLATES, ('.html', '.txt')):
            for m in pattern.finditer(p.read_text(encoding='utf-8', errors='ignore')):
                if m.group(1) not in ALLOWED_EXTERNAL:
                    found.append(f'{p.relative_to(TEMPLATES)}: {m.group(0)}')
        self.assertEqual(found, [], 'use {{ site_origin }} or a URL variable')


class ScriptAndCodeUrlTests(SimpleTestCase):
    def test_scripts_take_their_urls_from_the_page(self) -> None:
        pattern = re.compile(
            r"""['"`](/(?:accounts|api|updates|download|dns|mail|media)/[^'"`]*)['"`]"""
        )
        # service-worker.js runs outside any page and keeps its own cache list (STATIC_URL is the
        # fixed '/static/'); ifinmail-api.js is a client for the legacy /v1 base and is not loaded.
        skip = {'service-worker.js', 'ifinmail-api.js'}
        found = [
            f'{p.name}: {m.group(1)}'
            for p in source_files(JS, ('.js',))
            if p.name not in skip
            for m in pattern.finditer(p.read_text(encoding='utf-8'))
        ]
        self.assertEqual(found, [], 'render the URL into a data- attribute with {% url %}')

    def test_views_build_urls_with_reverse(self) -> None:
        pattern = re.compile(r"""['"`](/accounts/[a-z][^'"`]*)['"`]""")
        skip_names = {'urls.py', 'middleware.py'}
        found = [
            f'{p.relative_to(BACKEND)}: {m.group(1)}'
            for p in source_files(BACKEND, ('.py',))
            if p.name not in skip_names and 'tests' not in p.parts and 'migrations' not in p.parts
            for m in pattern.finditer(p.read_text(encoding='utf-8', errors='ignore'))
            if not re.match(
                r'^\s*(?:#|"""|\'\'\')',
                p.read_text(encoding='utf-8').splitlines()[
                    p.read_text(encoding='utf-8')[: m.start()].count('\n')
                ],
            )
        ]
        self.assertEqual(found, [], 'use reverse() / site_url.absolute_url()')

    def test_no_default_points_at_a_domain_that_is_not_ours(self) -> None:
        pattern = re.compile(r'ifinmail\.(?:io|dev|com|org|net)\b')
        found = [
            f'{p.relative_to(ROOT)}: {m.group(0)}'
            for base in (BACKEND, TEMPLATES, JS)
            for p in source_files(base, ('.py', '.html', '.txt', '.js'))
            if 'tests' not in p.parts
            for m in pattern.finditer(p.read_text(encoding='utf-8', errors='ignore'))
        ]
        self.assertEqual(found, [])

    def test_the_middleware_exemptions_name_real_routes(self) -> None:
        from backend.apps.accounts.middleware import SetupRequiredMiddleware

        routes: list[str] = []

        def walk(patterns: list, prefix: str = '') -> None:
            for entry in patterns:
                part = str(entry.pattern)
                if hasattr(entry, 'url_patterns'):
                    walk(entry.url_patterns, prefix + part)
                else:
                    routes.append(prefix + part)

        walk(get_resolver().url_patterns)
        served_elsewhere = ('/static/', '/media/', '/.well-known/', '/Autodiscover/', '/telemetry/')
        missing = [
            prefix
            for prefix in SetupRequiredMiddleware.exempt_prefixes
            if prefix not in served_elsewhere
            and not any(route.startswith(prefix.lstrip('/')) for route in routes)
        ]
        self.assertEqual(missing, [], 'stale exemptions: no route starts with these')


class SiteOriginTests(SimpleTestCase):
    factory = RequestFactory()

    def request(self, host: str, *, secure: bool = True) -> HttpRequest:
        return self.factory.get(
            '/', HTTP_HOST=host, **({'wsgi.url_scheme': 'https'} if secure else {})
        )

    @override_settings(ALLOWED_HOSTS=['*'], DEBUG=False)
    def test_a_named_host_is_the_current_domain(self) -> None:
        with patch.dict('os.environ', {'MAIL_HOSTNAME': 'mail.other.test'}):
            self.assertEqual(
                site_url.origin(self.request('console.example.org')), 'https://console.example.org'
            )

    @override_settings(ALLOWED_HOSTS=['*'], DEBUG=False)
    def test_an_ip_address_falls_back_to_the_configured_hostname(self) -> None:
        with patch.dict('os.environ', {'MAIL_HOSTNAME': 'mail.example.org'}):
            self.assertEqual(
                site_url.origin(self.request('203.0.113.9')), 'https://mail.example.org'
            )
            self.assertEqual(site_url.host(self.request('203.0.113.9')), 'mail.example.org')

    @override_settings(ALLOWED_HOSTS=['*'], DEBUG=False)
    def test_localhost_is_never_the_public_address(self) -> None:
        with patch.dict('os.environ', {'MAIL_HOSTNAME': 'mail.example.org'}):
            self.assertEqual(
                site_url.origin(self.request('localhost:8000')), 'https://mail.example.org'
            )

    @override_settings(ALLOWED_HOSTS=['*'], DEBUG=True)
    def test_a_development_server_keeps_the_address_in_use(self) -> None:
        with patch.dict('os.environ', {'MAIL_HOSTNAME': 'mail.example.org'}):
            self.assertEqual(
                site_url.origin(self.request('localhost:8000', secure=False)),
                'http://localhost:8000',
            )

    @override_settings(ALLOWED_HOSTS=['*'], DEBUG=False)
    def test_nothing_configured_uses_the_request_as_is(self) -> None:
        with patch.dict('os.environ', {'MAIL_HOSTNAME': ''}):
            self.assertEqual(site_url.origin(self.request('203.0.113.9')), 'https://203.0.113.9')

    def test_without_a_request_the_configured_hostname_is_used(self) -> None:
        with patch.dict('os.environ', {'MAIL_HOSTNAME': 'Mail.Example.org.'}):
            self.assertEqual(site_url.origin(None), 'https://mail.example.org')
        with patch.dict('os.environ', {'MAIL_HOSTNAME': ''}):
            self.assertEqual(site_url.origin(None), '')

    def test_ipv6_and_ports(self) -> None:
        self.assertFalse(site_url.is_named_host('[2001:db8::1]:443'))
        self.assertFalse(site_url.is_named_host('127.0.0.1:8000'))
        self.assertTrue(site_url.is_named_host('mail.example.org:8443'))

    @override_settings(ALLOWED_HOSTS=['*'], DEBUG=False)
    def test_absolute_url_for_a_route_name(self) -> None:
        with patch.dict('os.environ', {'MAIL_HOSTNAME': 'mail.example.org'}):
            url = site_url.absolute_url(self.request('198.51.100.7'), 'accounts:login')
        self.assertEqual(url, f'https://mail.example.org{reverse("accounts:login")}')


@override_settings(ALLOWED_HOSTS=['*'], DEBUG=False)
class PagesCarryTheCurrentDomainTests(TestCase):
    def test_docs_examples_use_this_servers_address(self) -> None:
        with patch.dict('os.environ', {'MAIL_HOSTNAME': 'mail.example.org'}):
            html = self.client.get(
                reverse('docs'), HTTP_HOST='console.example.test', secure=True
            ).content.decode()
        self.assertIn('https://console.example.test/accounts/login/', html)
        self.assertIn(
            'curl -u ifm_KEY:ifs_SECRET https://console.example.test/api/v1/mailboxes', html
        )
        self.assertNotIn('mail.your-domain', html)

    def test_docs_examples_fall_back_to_the_hostname_when_opened_by_ip(self) -> None:
        with patch.dict('os.environ', {'MAIL_HOSTNAME': 'mail.example.org'}):
            html = self.client.get(reverse('docs'), HTTP_HOST='203.0.113.9').content.decode()
        self.assertIn('https://mail.example.org/accounts/login/', html)

    def test_the_download_page_names_the_current_domain(self) -> None:
        with patch.dict('os.environ', {'MAIL_HOSTNAME': 'mail.example.org'}):
            html = self.client.get(reverse('download'), HTTP_HOST='203.0.113.9').content.decode()
        self.assertNotIn('203.0.113.9', html)

    def test_no_foreign_support_address_or_docs_link_by_default(self) -> None:
        with patch.dict('os.environ', {'SUPPORT_EMAIL': '', 'DOCS_URL': ''}):
            from backend.config.server_context import server_context

            request = RequestFactory().get('/', HTTP_HOST='mail.example.org')
            context = server_context(request)
        self.assertEqual(context['support_email'], '')
        self.assertEqual(context['docs_url'], reverse('docs'))
        self.assertEqual(context['site_host'], 'mail.example.org')
