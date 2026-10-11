"""Two-factor setup is offered, not forced: "Remind me in a week" postpones the prompt."""

from __future__ import annotations

import base64
import time
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.mfa import TOTPService, _hotp
from backend.apps.core.tests.mail_base import MailTablesTestCase

GOOD = 'Correct-Horse-9'


def _code_now(secret: str) -> str:
    return _hotp(base64.b32decode(secret), int(time.time() // 30))


class MFASnoozeTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        from backend.apps.accounts.services.setup_state import SetupState

        SetupState.mark_complete()
        self.user = MailUser.objects.create_user('admin@ifinmail.test', GOOD, is_staff=True)
        self.client.force_login(self.user)

    def test_without_a_snooze_console_pages_offer_enrollment(self) -> None:
        response = self.client.get(reverse('accounts:dashboard'))
        self.assertRedirects(response, reverse('accounts:mfa_setup'), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse('accounts:mfa_setup')), 'Remind me in a week')

    def test_remind_me_in_a_week_opens_the_console(self) -> None:
        response = self.client.post(reverse('accounts:mfa_setup'), {'action': 'snooze'})
        self.assertRedirects(response, reverse('accounts:dashboard'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        remaining = self.user.mfa_remind_after - timezone.now()
        self.assertGreater(remaining, timedelta(days=6, hours=23))
        self.assertEqual(self.client.get(reverse('accounts:dashboard')).status_code, 200)
        from backend.apps.core.platform.services.audit import AuditService

        self.assertTrue(AuditService.has('mfa_setup_postponed'))

    def test_the_prompt_returns_after_the_week(self) -> None:
        self.user.mfa_remind_after = timezone.now() - timedelta(minutes=1)
        self.user.save()
        response = self.client.get(reverse('accounts:dashboard'))
        self.assertRedirects(response, reverse('accounts:mfa_setup'), fetch_redirect_response=False)

    def test_signing_in_during_a_snooze_goes_to_the_dashboard(self) -> None:
        TOTPService.snooze(self.user)
        self.client.logout()
        response = self.client.post(
            reverse('accounts:login'), {'email': self.user.email, 'password': GOOD}
        )
        self.assertRedirects(response, reverse('accounts:dashboard'), fetch_redirect_response=False)

    def test_an_enrolled_login_cannot_postpone_and_still_needs_its_code(self) -> None:
        _, secret = TOTPService.start_enrollment(self.user)
        TOTPService.confirm_enrollment(self.user, _code_now(secret))
        self.client.post(reverse('accounts:mfa_setup'), {'action': 'snooze'})
        self.user.refresh_from_db()
        self.assertIsNone(self.user.mfa_remind_after)
        self.assertNotContains(self.client.get(reverse('accounts:mfa_setup')), 'Remind me in a week')
        self.client.logout()
        response = self.client.post(
            reverse('accounts:login'), {'email': self.user.email, 'password': GOOD}
        )
        self.assertRedirects(response, reverse('accounts:mfa_verify'), fetch_redirect_response=False)
