"""A configured logo reaches every surface that shows a brand mark.

Covers the public pages (landing, terms, privacy) and the system emails, which
render outside the request context and must receive the brand explicitly.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core import mail
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.test.utils import override_settings
from django.urls import reverse

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.views.registration import _send_verification_email
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.config.branding import BrandingConfig

LOGO = '/media/branding/logo.png'
BRAND = BrandingConfig(name='Acme Mail', tagline='mail infrastructure', logo_url=LOGO)
PLAIN_BRAND = BrandingConfig(name='Acme Mail', tagline='mail infrastructure')


class PublicPageLogoTests(TestCase):
    def test_landing_nav_and_footer_use_the_uploaded_logo(self) -> None:
        with override_settings(BRAND_CONFIG=BRAND):
            response = self.client.get(reverse('landing'))
        self.assertContains(response, f'src="{LOGO}"')
        self.assertEqual(response.content.decode().count(f'src="{LOGO}"'), 2)

    def test_legal_pages_use_the_uploaded_logo(self) -> None:
        with override_settings(BRAND_CONFIG=BRAND):
            for route in ('terms', 'privacy'):
                with self.subTest(route=route):
                    response = self.client.get(reverse(route))
                    self.assertContains(response, f'src="{LOGO}"')

    def test_login_card_uses_the_uploaded_logo(self) -> None:
        with override_settings(BRAND_CONFIG=BRAND):
            response = self.client.get(reverse('accounts:login'))
        self.assertContains(response, f'src="{LOGO}"')
        self.assertNotContains(response, 'ifinmail-login-card__brand--name')

    def test_login_card_shows_the_brand_name_without_a_logo(self) -> None:
        with override_settings(BRAND_CONFIG=PLAIN_BRAND):
            response = self.client.get(reverse('accounts:login'))
        self.assertContains(response, 'Acme Mail')
        self.assertContains(response, 'ifinmail-login-card__brand--name')
        self.assertNotContains(response, 'ifinmail-login-card__logo')

    def test_public_pages_show_the_brand_name_without_a_logo(self) -> None:
        with override_settings(BRAND_CONFIG=PLAIN_BRAND):
            response = self.client.get(reverse('landing'))
        self.assertContains(response, 'Acme Mail')
        self.assertNotContains(response, 'ifinmail-brand-logo')
        self.assertNotContains(response, 'ifinmail-site-brand__logo')

    def test_error_page_shows_the_brand_name_without_a_logo(self) -> None:
        with override_settings(BRAND_CONFIG=PLAIN_BRAND):
            response = self.client.get('/definitely-not-a-real-page/', HTTP_ACCEPT='text/html')
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Acme Mail', status_code=404)


class ConsoleSidebarLogoTests(MailTablesTestCase):
    def _login_console(self) -> None:
        from django.utils import timezone

        admin = MailUser.objects.create_user('root@ifinmail.test', 'Correct-Horse-9', is_staff=True)
        self.client.force_login(admin, backend='django.contrib.auth.backends.ModelBackend')
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def test_console_sidebar_uses_the_uploaded_logo(self) -> None:
        self._login_console()
        with override_settings(BRAND_CONFIG=BRAND):
            response = self.client.get(reverse('accounts:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'src="{LOGO}"')

    def test_console_sidebar_shows_the_name_without_a_logo(self) -> None:
        self._login_console()
        with override_settings(BRAND_CONFIG=PLAIN_BRAND):
            response = self.client.get(reverse('accounts:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Acme Mail')
        self.assertNotContains(response, 'ifinmail-admin-brand-icon')


class ManifestBrandingTests(TestCase):
    def test_manifest_uses_the_brand_name_and_default_icons(self) -> None:
        with override_settings(BRAND_CONFIG=PLAIN_BRAND):
            data = self.client.get(reverse('manifest')).json()
        self.assertEqual(data['name'], 'Acme Mail — Mail Server Admin')
        self.assertEqual(data['short_name'], 'Acme Mail')
        self.assertTrue(any('icon-192' in icon['src'] for icon in data['icons']))

    def test_manifest_uses_the_uploaded_favicon_when_set(self) -> None:
        brand = BrandingConfig(name='Acme Mail', favicon_url='/media/branding/favicon.ico')
        with override_settings(BRAND_CONFIG=brand):
            data = self.client.get(reverse('manifest')).json()
        self.assertEqual(len(data['icons']), 1)
        self.assertEqual(data['icons'][0]['src'], '/media/branding/favicon.ico')
        self.assertEqual(data['icons'][0]['type'], 'image/x-icon')


class StandaloneCardBrandTests(TestCase):
    STANDALONE = (
        'admin/login.html',
        'admin/mfa_setup.html',
        'admin/mfa_verify.html',
        'admin/mailbox_setup.html',
        'admin/password_reset_form.html',
        'admin/password_reset_done.html',
        'admin/password_reset_confirm.html',
        'admin/password_reset_complete.html',
        'registration/step_profile.html',
        'registration/step_password.html',
        'registration/step_username.html',
        'registration/step_verify.html',
        'registration/step_complete.html',
        'setup/welcome.html',
        'setup/dns_provider.html',
        'setup/dns_auto.html',
        'setup/dns_manual.html',
        'setup/dns_server.html',
        'setup/create_account.html',
        'setup/done.html',
        'error_base.html',
    )

    def test_every_standalone_card_uses_the_shared_brand_block(self) -> None:
        templates = Path(settings.BASE_DIR) / 'frontend' / 'templates'
        for name in self.STANDALONE:
            with self.subTest(template=name):
                source = (templates / name).read_text(encoding='utf-8')
                self.assertIn('includes/card_brand.html', source)
                self.assertNotIn('logo_svg', source)

    def test_the_brand_block_shows_the_logo_or_the_system_name(self) -> None:
        templates = Path(settings.BASE_DIR) / 'frontend' / 'templates'
        source = (templates / 'includes' / 'card_brand.html').read_text(encoding='utf-8')
        self.assertIn('brand.logo_url', source)
        # One source for the default name: BrandingConfig (DEFAULT_BRAND_NAME), not each template.
        self.assertIn('{{ brand.name }}', source)
        self.assertNotIn("default:'ifinmail'", source)
        self.assertIn('ifinmail-login-card__brand--name', source)


class SystemEmailLogoTests(MailTablesTestCase):
    def test_verification_email_carries_the_logo_as_an_absolute_url(self) -> None:
        user = MailUser.objects.create_user('new@ifinmail.test', 'Correct-Horse-9')
        request = RequestFactory().get('/accounts/registration/')
        with override_settings(BRAND_CONFIG=BRAND):
            sent, _ = _send_verification_email(request, user.email)
        self.assertTrue(sent)
        body = mail.outbox[0].alternatives[0][0]
        self.assertIn(f'src="http://testserver{LOGO}"', body)
        self.assertIn('Acme Mail', body)

    def test_password_reset_email_carries_the_logo_as_an_absolute_url(self) -> None:
        MailUser.objects.create_user('reset@ifinmail.test', 'Correct-Horse-9')
        with override_settings(BRAND_CONFIG=BRAND):
            response = self.client.post(
                reverse('accounts:password_reset'), {'email': 'reset@ifinmail.test'}
            )
        self.assertEqual(response.status_code, 302)
        body = mail.outbox[0].alternatives[0][0]
        self.assertIn(f'src="http://testserver{LOGO}"', body)

    def test_password_reset_email_falls_back_without_a_logo(self) -> None:
        MailUser.objects.create_user('reset2@ifinmail.test', 'Correct-Horse-9')
        with override_settings(BRAND_CONFIG=PLAIN_BRAND):
            self.client.post(reverse('accounts:password_reset'), {'email': 'reset2@ifinmail.test'})
        body = mail.outbox[0].alternatives[0][0]
        self.assertNotIn('<img', body)
        self.assertIn('Acme Mail', body)


class DefaultBrandNameTests(SimpleTestCase):
    def test_no_template_spells_out_its_own_default_name(self) -> None:
        templates = Path(settings.BASE_DIR) / 'frontend' / 'templates'
        offenders = [
            str(path.relative_to(templates))
            for path in templates.rglob('*.html')
            if "default:'ifinmail'" in path.read_text(encoding='utf-8')
        ]
        self.assertEqual(offenders, [])

    def test_without_configuration_the_brand_is_the_default_name(self) -> None:
        from backend.config.branding import DEFAULT_BRAND_NAME, BrandingConfig

        brand = BrandingConfig()
        self.assertEqual(brand.name, DEFAULT_BRAND_NAME)
        self.assertFalse(brand.is_custom)
