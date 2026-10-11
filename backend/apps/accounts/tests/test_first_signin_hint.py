"""No logo uploaded → the brand name, never a broken image; the login page says how to sign in first."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse

from backend.apps.accounts.models import MailUser
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.config.branding import BrandingConfig

PRINTED = 'Printed-By-Installer-1'


class MissingLogoTests(SimpleTestCase):
    def _brand(self, logo_url: str, create_file: bool) -> BrandingConfig:
        base = tempfile.mkdtemp(prefix='ifinmail-brand-')
        if create_file:
            os.makedirs(os.path.join(base, 'media', 'branding'))
            with open(os.path.join(base, 'media', 'branding', 'logo.png'), 'wb') as handle:
                handle.write(b'png')
        env = {'BRAND_LOGO_URL': logo_url, 'BRANDING_OVERRIDES_PATH': os.path.join(base, 'none.json')}
        with patch.dict(os.environ, env):
            os.environ.pop('MEDIA_ROOT', None)
            return BrandingConfig.from_env(base)

    def test_a_logo_whose_upload_is_missing_is_ignored(self) -> None:
        brand = self._brand('/media/branding/logo.png', create_file=False)
        self.assertEqual(brand.logo_url, '')
        self.assertEqual(brand.name, 'ifinmail')

    def test_an_uploaded_logo_is_kept(self) -> None:
        self.assertEqual(
            self._brand('/media/branding/logo.png', create_file=True).logo_url,
            '/media/branding/logo.png',
        )

    def test_paths_outside_the_media_root_are_refused(self) -> None:
        self.assertEqual(self._brand('/media/../../etc/passwd', create_file=True).logo_url, '')

    def test_external_logo_urls_are_left_alone(self) -> None:
        url = 'https://cdn.example.org/logo.svg'
        self.assertEqual(self._brand(url, create_file=False).logo_url, url)

    def test_the_shipped_overrides_file_names_no_logo(self) -> None:
        import json

        from django.conf import settings

        with open(os.path.join(settings.BASE_DIR, 'branding_overrides.json'), encoding='utf-8') as f:
            self.assertNotIn('logo_url', json.load(f))


class FirstSigninHintTests(MailTablesTestCase):
    def test_login_names_the_installer_admin_and_where_the_password_is(self) -> None:
        MailUser.objects.create_superuser(
            'admin@ifinmail.test', PRINTED, password_change_required=True
        )
        with patch.dict(os.environ, {'IFINMAIL_INSTALL_DIR': '/srv/ifinmail'}):
            response = self.client.get(reverse('accounts:login'))
        self.assertContains(response, 'First sign-in')
        self.assertContains(response, 'value="admin@ifinmail.test"')
        self.assertContains(response, '/srv/ifinmail/provisioning/.env')
        self.assertNotContains(response, PRINTED)

    def test_no_hint_once_the_password_was_changed(self) -> None:
        MailUser.objects.create_superuser('admin@ifinmail.test', PRINTED)
        response = self.client.get(reverse('accounts:login'))
        self.assertNotContains(response, 'First sign-in')
        self.assertNotContains(response, 'admin@ifinmail.test')
