"""The public pages know who is signed in.

The marketing header used to show "Sign in" and "Get started" to everyone, including the
administrator who had just come from the console. It now shows the person, a way into the console
(only when their login may open it) and a way out; the sign-in page sends someone who is already
signed in where they were going.
"""

from __future__ import annotations

from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.roles import RoleService
from backend.apps.core.tests.mail_base import MailTablesTestCase

GOOD = 'Correct-Horse-9'
BACKEND = 'django.contrib.auth.backends.ModelBackend'


class SiteSessionBase(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        RoleService.ensure_seed()
        self.admin = MailUser.objects.create_user(
            'root@ifinmail.test', GOOD, is_staff=True, is_superuser=True, full_name='Rhoda Admin'
        )
        self.mailbox = MailUser.objects.create_user(
            'bob@ifinmail.test', GOOD, full_name='Bob Mailbox'
        )

    def sign_in(self, user: MailUser) -> None:
        self.client.force_login(user, backend=BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()


class PublicHeaderTests(SiteSessionBase):
    def test_a_visitor_sees_sign_in_and_get_started(self) -> None:
        html = self.client.get(reverse('landing')).content.decode()
        self.assertIn('Sign in', html)
        self.assertIn('Get started', html)
        self.assertNotIn('ifinmail-site-account', html)
        self.assertNotIn('Open console', html)

    def test_an_administrator_sees_themselves_and_a_way_into_the_console(self) -> None:
        self.sign_in(self.admin)
        html = self.client.get(reverse('landing')).content.decode()
        self.assertIn('Rhoda Admin', html)
        self.assertIn('root@ifinmail.test', html)
        self.assertIn(f'href="{reverse("accounts:dashboard")}"', html)
        self.assertIn('Open console', html)
        self.assertIn(reverse('accounts:logout'), html)
        self.assertNotIn('Get started', html)
        self.assertIn('ifinmail-site-header--session', html)
        # the header and the phone menu each carry the account row
        self.assertEqual(html.count('<span class="ifinmail-site-account__text">'), 2)

    def test_a_plain_mailbox_can_sign_out_but_is_not_offered_the_console(self) -> None:
        self.sign_in(self.mailbox)
        html = self.client.get(reverse('landing')).content.decode()
        self.assertIn('Bob Mailbox', html)
        self.assertIn('Sign out', html)
        self.assertNotIn('Open console', html)
        self.assertNotIn('Get started', html)

    def test_every_public_page_uses_the_same_header(self) -> None:
        self.sign_in(self.admin)
        for name in ('features', 'pricing', 'security', 'docs', 'changelog', 'about', 'download'):
            with self.subTest(page=name):
                html = self.client.get(reverse(name)).content.decode()
                self.assertIn('Open console', html)

    def test_the_download_page_sends_an_administrator_to_app_releases(self) -> None:
        html = self.client.get(reverse('download')).content.decode()
        self.assertIn('Administrators: sign in to publish a build', html)
        self.sign_in(self.admin)
        html = self.client.get(reverse('download')).content.decode()
        self.assertIn(reverse('releases:console'), html)
        self.assertNotIn('Administrators: sign in to publish a build', html)


class SignInPageWhenSignedInTests(SiteSessionBase):
    def test_goes_to_the_console(self) -> None:
        self.sign_in(self.admin)
        response = self.client.get(reverse('accounts:login'))
        self.assertRedirects(response, reverse('accounts:dashboard'), fetch_redirect_response=False)

    def test_goes_to_where_they_were_headed(self) -> None:
        self.sign_in(self.admin)
        target = reverse('accounts:logs')
        response = self.client.get(reverse('accounts:login'), {'next': target})
        self.assertRedirects(response, target, fetch_redirect_response=False)

    def test_never_to_another_site(self) -> None:
        self.sign_in(self.admin)
        for bad in ('//evil.example', 'https://evil.example/', 'javascript:alert(1)'):
            with self.subTest(next=bad):
                response = self.client.get(reverse('accounts:login'), {'next': bad})
                self.assertRedirects(
                    response, reverse('accounts:dashboard'), fetch_redirect_response=False
                )

    def test_switch_keeps_the_form_for_another_account(self) -> None:
        self.sign_in(self.admin)
        response = self.client.get(reverse('accounts:login'), {'switch': '1'})
        self.assertEqual(response.status_code, 200)

    def test_a_visitor_still_gets_the_form(self) -> None:
        self.assertEqual(self.client.get(reverse('accounts:login')).status_code, 200)
