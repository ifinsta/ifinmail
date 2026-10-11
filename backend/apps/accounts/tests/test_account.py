"""Self-service Account page: display name and password change."""

from __future__ import annotations

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.profile import ProfileError, ProfileService
from backend.apps.core.tests.mail_base import MailTablesTestCase

GOOD = 'Correct-Horse-9'
NEW = 'Better-Horse-10'
MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'


class AccountPageTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.user = MailUser.objects.create_user(
            'root@ifinmail.test', GOOD, is_staff=True, is_superuser=True
        )

    def _client(self) -> Client:
        client = Client()
        client.force_login(self.user, backend=MODEL_BACKEND)
        session = client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()
        return client

    def test_anonymous_is_sent_to_sign_in(self) -> None:
        response = Client().get(reverse('accounts:account'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_the_page_renders_inside_the_settings_hub(self) -> None:
        html = self._client().get(reverse('accounts:account')).content.decode()
        self.assertIn('ifinmail-settings__nav', html)
        self.assertIn('root@ifinmail.test', html)

    def test_a_display_name_can_be_set_and_shows_afterwards(self) -> None:
        client = self._client()
        response = client.post(
            reverse('accounts:account_name'), {'full_name': '  Ada Root  '}, follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.full_name, 'Ada Root')
        self.assertIn('Ada Root', client.get(reverse('accounts:account')).content.decode())

    def test_a_blank_display_name_is_refused(self) -> None:
        client = self._client()
        response = client.post(reverse('accounts:account_name'), {'full_name': '   '}, follow=True)
        self.assertContains(response, 'Full name')
        self.user.refresh_from_db()
        self.assertEqual(self.user.full_name, '')

    def test_the_wrong_current_password_changes_nothing(self) -> None:
        client = self._client()
        response = client.post(
            reverse('accounts:account_password'),
            {'old_password': 'Not-My-Password', 'new_password': NEW, 'confirm_password': NEW},
            follow=True,
        )
        self.assertContains(response, 'not correct')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(GOOD))

    def test_mismatched_new_passwords_are_refused(self) -> None:
        client = self._client()
        response = client.post(
            reverse('accounts:account_password'),
            {'old_password': GOOD, 'new_password': NEW, 'confirm_password': 'Different-1'},
            follow=True,
        )
        self.assertContains(response, 'do not match')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(GOOD))

    def test_a_changed_password_keeps_this_session_signed_in(self) -> None:
        client = self._client()
        response = client.post(
            reverse('accounts:account_password'),
            {'old_password': GOOD, 'new_password': NEW, 'confirm_password': NEW},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW))
        # Session survived: the page still renders for this client.
        self.assertEqual(client.get(reverse('accounts:account')).status_code, 200)


class ProfileServiceTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.user = MailUser.objects.create_user('plain@ifinmail.test', GOOD)

    def test_short_passwords_are_refused_before_touching_the_model(self) -> None:
        with self.assertRaises(ProfileError):
            ProfileService.change_password(self.user, GOOD, 'short')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(GOOD))

    def test_get_full_name_is_empty_until_set(self) -> None:
        self.assertEqual(self.user.get_full_name(), '')
        ProfileService.set_full_name(self.user, 'Ada')
        self.user.refresh_from_db()
        self.assertEqual(self.user.get_full_name(), 'Ada')
