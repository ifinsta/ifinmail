"""Installer's administrator: created flagged, must choose a new password before anything else."""

from __future__ import annotations

import os
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.setup_guide import ACTION, GuideStatus, GuideStep
from backend.apps.core.tests.mail_base import MailTablesTestCase

PRINTED = 'Printed-By-Installer-1'
NEW = 'Chosen-By-Admin-2'


class EnsureAdminCommandTests(MailTablesTestCase):
    def _run(self, password: str = PRINTED) -> str:
        out = StringIO()
        env = {'DJANGO_SUPERUSER_EMAIL': 'admin@ifinmail.test', 'DJANGO_SUPERUSER_PASSWORD': password}
        with patch.dict(os.environ, env):
            call_command('ensure_admin', stdout=out)
        return out.getvalue()

    def test_creates_flagged_superuser(self) -> None:
        self.assertIn('Created administrator', self._run())
        user = MailUser.objects.get(email='admin@ifinmail.test')
        self.assertTrue(user.is_superuser and user.is_staff)
        self.assertTrue(user.password_change_required)
        self.assertTrue(user.check_password(PRINTED))

    def test_rerun_leaves_existing_login_alone(self) -> None:
        self._run()
        user = MailUser.objects.get(email='admin@ifinmail.test')
        user.set_password(NEW)
        user.password_change_required = False
        user.save()
        self.assertIn('already exists', self._run(password='Another-Printed-3'))
        user.refresh_from_db()
        self.assertTrue(user.check_password(NEW))
        self.assertFalse(user.password_change_required)


class FirstPasswordFlowTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.user = MailUser.objects.create_superuser(
            'admin@ifinmail.test', PRINTED, password_change_required=True
        )
        self.client.force_login(self.user)

    def test_every_console_page_goes_to_first_password_first(self) -> None:
        for name in ('accounts:dashboard', 'accounts:setup_wizard', 'accounts:mfa_setup'):
            response = self.client.get(reverse(name))
            self.assertRedirects(
                response, reverse('accounts:first_password'), fetch_redirect_response=False
            )
        self.assertEqual(self.client.get(reverse('accounts:first_password')).status_code, 200)

    def test_rejects_mismatch_short_and_unchanged_passwords(self) -> None:
        url = reverse('accounts:first_password')
        for new1, new2, message in (
            (NEW, NEW + 'x', 'do not match'),
            ('short', 'short', 'at least'),
            (PRINTED, PRINTED, 'different from the one the installer printed'),
        ):
            response = self.client.post(url, {'new_password1': new1, 'new_password2': new2})
            self.assertContains(response, message)
        self.user.refresh_from_db()
        self.assertTrue(self.user.password_change_required)

    def test_new_password_clears_flag_keeps_session_then_wizard_then_mfa(self) -> None:
        response = self.client.post(
            reverse('accounts:first_password'), {'new_password1': NEW, 'new_password2': NEW}
        )
        self.assertRedirects(
            response, reverse('accounts:setup_wizard'), fetch_redirect_response=False
        )
        self.user.refresh_from_db()
        self.assertFalse(self.user.password_change_required)
        self.assertTrue(self.user.check_password(NEW))
        self.assertIn('_auth_user_id', self.client.session)
        # Afterwards the usual guards resume: MFA enrollment for console pages.
        response = self.client.get(reverse('accounts:dashboard'))
        self.assertRedirects(response, reverse('accounts:mfa_setup'), fetch_redirect_response=False)
        from backend.apps.core.platform.services.audit import AuditService

        self.assertTrue(AuditService.has('initial_password_changed'))

    def test_unflagged_login_never_sees_the_page(self) -> None:
        self.user.password_change_required = False
        self.user.save()
        response = self.client.get(reverse('accounts:first_password'))
        self.assertRedirects(response, reverse('accounts:dashboard'), fetch_redirect_response=False)


class ReadinessPanelTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        from backend.apps.accounts.services.setup_state import SetupState

        SetupState.mark_complete()
        self.user = MailUser.objects.create_superuser('admin@ifinmail.test', NEW)
        self.client.force_login(self.user)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def test_dashboard_shows_pending_registrar_steps(self) -> None:
        status = GuideStatus(
            domain='ifinmail.test',
            mail_hostname='mail.ifinmail.test',
            server_ip='192.0.2.10',
            steps=[
                GuideStep(
                    'ptr',
                    'Set reverse DNS (PTR)',
                    ACTION,
                    '192.0.2.10 currently points to nothing.',
                    [('Reverse DNS / PTR name', 'mail.ifinmail.test')],
                )
            ],
        )
        with patch(
            'backend.apps.accounts.services.setup_guide.SetupGuide.status', return_value=status
        ) as status_mock:
            response = self.client.get(reverse('accounts:dashboard') + '?recheck=1')
        status_mock.assert_called_once_with(refresh=True)
        self.assertContains(response, 'Server readiness')
        self.assertContains(response, 'Set reverse DNS (PTR)')
        self.assertContains(response, 'mail.ifinmail.test')

    def test_landing_page_is_not_the_setup_guide(self) -> None:
        self.client.logout()
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Server readiness')
