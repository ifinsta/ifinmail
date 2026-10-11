"""Until first-run setup is finished, every web page leads to the setup wizard."""

from __future__ import annotations

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.setup_state import SetupState
from backend.apps.core.tests.mail_base import MailTablesTestCase

GOOD = 'Correct-Horse-9'


@override_settings(SETUP_REQUIRED_REDIRECT=True)
class SetupRequiredTests(MailTablesTestCase):
    def test_pages_lead_to_the_wizard_before_setup(self) -> None:
        for path in ('/', '/terms/', reverse('accounts:dashboard'), '/dns/'):
            response = self.client.get(path)
            self.assertRedirects(
                response, reverse('accounts:setup_wizard'), fetch_redirect_response=False
            )

    def test_signed_out_visitor_reaches_login_with_the_wizard_as_next(self) -> None:
        response = self.client.get('/', follow=True)
        login = reverse('accounts:login')
        self.assertEqual(response.request['PATH_INFO'], login)
        self.assertIn(reverse('accounts:setup_wizard'), response.redirect_chain[-1][0])

    def test_machine_and_sign_in_paths_are_never_redirected(self) -> None:
        for path in (
            reverse('accounts:login'),
            '/health/',
            '/.well-known/mta-sts.txt',
            '/mail/config-v1.1.xml',
            '/manifest.webmanifest',
        ):
            response = self.client.get(path)
            self.assertNotEqual(
                response.get('Location'), reverse('accounts:setup_wizard'), msg=path
            )

    def test_admin_lands_in_the_wizard_not_the_dashboard(self) -> None:
        admin = MailUser.objects.create_superuser('admin@ifinmail.test', GOOD)
        self.client.force_login(admin)
        response = self.client.get(reverse('accounts:dashboard'))
        self.assertRedirects(
            response, reverse('accounts:setup_wizard'), fetch_redirect_response=False
        )

    def test_first_password_still_comes_before_the_wizard(self) -> None:
        admin = MailUser.objects.create_superuser(
            'admin@ifinmail.test', GOOD, password_change_required=True
        )
        self.client.force_login(admin)
        response = self.client.get('/')
        self.assertRedirects(
            response, reverse('accounts:first_password'), fetch_redirect_response=False
        )

    def test_after_setup_pages_open_normally(self) -> None:
        SetupState.mark_complete()
        self.assertEqual(self.client.get('/').status_code, 200)
        admin = MailUser.objects.create_superuser('admin@ifinmail.test', GOOD)
        self.client.force_login(admin)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()
        self.assertEqual(self.client.get(reverse('accounts:dashboard')).status_code, 200)


class FormEndpointGetTests(MailTablesTestCase):
    """Reloading a URL a form posted to lands on the form's page, not a bare 405."""

    def setUp(self) -> None:
        super().setUp()
        SetupState.mark_complete()
        admin = MailUser.objects.create_superuser('admin@ifinmail.test', GOOD)
        self.client.force_login(admin)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def test_browser_get_on_a_form_endpoint_goes_to_its_page(self) -> None:
        response = self.client.get(
            '/accounts/settings/mailboxes/registration/', HTTP_ACCEPT='text/html'
        )
        self.assertRedirects(
            response, '/accounts/settings/mailboxes/', fetch_redirect_response=False
        )

    def test_non_browser_clients_keep_the_405(self) -> None:
        response = self.client.get(
            '/accounts/settings/mailboxes/registration/', HTTP_ACCEPT='application/json'
        )
        self.assertEqual(response.status_code, 405)

    def test_the_form_still_works(self) -> None:
        response = self.client.post('/accounts/settings/mailboxes/registration/', {'open': 'on'})
        self.assertRedirects(
            response, '/accounts/settings/mailboxes/', fetch_redirect_response=False
        )
