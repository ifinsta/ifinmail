"""The server's default look: smooth until an administrator chooses another."""

from __future__ import annotations

import re

from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services import appearance
from backend.apps.core.tests.mail_base import MailTablesTestCase

MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'


class DefaultThemeTests(MailTablesTestCase):
    def sign_in(self, **flags: bool) -> None:
        user = MailUser.objects.create_user('root@ifinmail.test', 'Correct-Horse-9', **flags)
        self.client.force_login(user, backend=MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def default_in_page(self, url: str) -> str:
        html = self.client.get(url).content.decode()
        match = re.search(r'ifinmail-theme-init\.js"\s+data-default="(\w*)"', html)
        assert match, 'the theme bootstrap carries the default'
        return match.group(1)

    def test_every_page_starts_smooth(self) -> None:
        self.assertEqual(self.default_in_page(reverse('accounts:login')), 'smooth')
        self.assertEqual(self.default_in_page(reverse('landing')), 'smooth')

    def test_an_administrator_changes_the_default_for_everyone(self) -> None:
        self.sign_in(is_staff=True, is_superuser=True)
        response = self.client.post(reverse('accounts:appearance_default'), {'theme': 'light'})
        self.assertRedirects(response, reverse('accounts:settings_page', args=['appearance']))
        self.assertEqual(appearance.default_theme(), 'light')
        self.assertEqual(self.default_in_page(reverse('landing')), 'light')

    def test_unknown_themes_are_refused(self) -> None:
        self.sign_in(is_staff=True, is_superuser=True)
        self.client.post(reverse('accounts:appearance_default'), {'theme': 'neon'})
        self.assertEqual(appearance.default_theme(), 'smooth')

    def test_the_setting_is_for_those_who_manage_the_system(self) -> None:
        self.sign_in()
        self.client.post(reverse('accounts:appearance_default'), {'theme': 'dark'})
        self.assertEqual(appearance.default_theme(), 'smooth')

    def test_the_appearance_page_offers_the_setting_to_administrators_only(self) -> None:
        self.sign_in(is_staff=True, is_superuser=True)
        html = self.client.get(reverse('accounts:settings_page', args=['appearance'])).content.decode()
        self.assertIn('Default for everyone', html)
