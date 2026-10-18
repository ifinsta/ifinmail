"""Sign-in lockout (django-axes) counts the person, not the reverse proxy in front of them."""

from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.setup_state import SetupState

from .test_views import create_unmanaged_table, drop_unmanaged_table


@override_settings(AXES_ENABLED=True)
class LoginLockoutTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        create_unmanaged_table(MailUser)

    @classmethod
    def tearDownClass(cls) -> None:
        drop_unmanaged_table(MailUser)
        super().tearDownClass()

    def _fixture_teardown(self=None) -> None:
        pass

    def _fixture_setup(self=None) -> None:
        pass

    def tearDown(self) -> None:
        from axes.models import AccessAttempt

        AccessAttempt.objects.all().delete()
        MailUser.objects.all().delete()
        super().tearDown()

    def setUp(self) -> None:
        SetupState.mark_complete()
        MailUser.objects.create_user(
            email='alex@ifinmail.test', password='right-pass-123', is_staff=True
        )
        MailUser.objects.create_user(
            email='dana@ifinmail.test', password='right-pass-456', is_staff=True
        )

    def _post(self, email: str, password: str, forwarded_for: str):
        # Every request arrives from the proxy (REMOTE_ADDR); only the header tells people apart.
        return self.client.post(
            reverse('accounts:login'),
            {'email': email, 'password': password},
            REMOTE_ADDR='172.18.0.12',
            HTTP_X_FORWARDED_FOR=forwarded_for,
        )

    def test_one_persons_failures_do_not_lock_out_others(self) -> None:
        for _ in range(5):
            self._post('alex@ifinmail.test', 'wrong', '203.0.113.7')
        # The same person is now locked out of that account...
        blocked = self._post('alex@ifinmail.test', 'right-pass-123', '203.0.113.7')
        self.assertContains(blocked, 'locked', status_code=blocked.status_code, html=False)
        self.assertNotEqual(blocked.status_code, 302)
        # ...but someone else on another network, behind the same proxy, signs in normally.
        other = self._post('dana@ifinmail.test', 'right-pass-456', '198.51.100.9')
        self.assertEqual(other.status_code, 302)
        same_account_elsewhere = self._post('alex@ifinmail.test', 'right-pass-123', '198.51.100.9')
        self.assertEqual(same_account_elsewhere.status_code, 302)

    def test_failures_are_recorded_with_the_account_and_client_address(self) -> None:
        from axes.models import AccessAttempt

        self._post('alex@ifinmail.test', 'wrong', '203.0.113.7')
        attempt = AccessAttempt.objects.get()
        self.assertEqual(attempt.username, 'alex@ifinmail.test')
        self.assertEqual(attempt.ip_address, '203.0.113.7')

    def test_a_forged_first_forwarded_entry_does_not_choose_the_address(self) -> None:
        from axes.models import AccessAttempt

        self._post('alex@ifinmail.test', 'wrong', '10.9.9.9, 203.0.113.7')
        self.assertEqual(AccessAttempt.objects.get().ip_address, '203.0.113.7')
