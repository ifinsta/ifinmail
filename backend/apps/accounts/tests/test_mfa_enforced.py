"""MFA_ENFORCEMENT=required: no postponing, no switching off, no skipping the prompt."""

from __future__ import annotations

import base64
import time
from datetime import timedelta
from io import StringIO

import yaml
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.mfa import MFAError, TOTPService, _hotp
from backend.apps.accounts.services.setup_state import SetupState
from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.core.tests.test_provisioning_contract import DOCKER

GOOD = 'Correct-Horse-9'


def _code_now(secret: str) -> str:
    return _hotp(base64.b32decode(secret), int(time.time() // 30))


@override_settings(MFA_ENFORCEMENT='required')
class RequiredPolicyTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        SetupState.mark_complete()
        self.user = MailUser.objects.create_user('admin@ifinmail.test', GOOD, is_staff=True)
        self.client.force_login(self.user)

    def _enroll(self) -> str:
        _, secret = TOTPService.start_enrollment(self.user)
        TOTPService.confirm_enrollment(self.user, _code_now(secret))
        return secret

    def test_the_policy_is_reported(self) -> None:
        self.assertTrue(TOTPService.enforced())
        with override_settings(MFA_ENFORCEMENT='optional'):
            self.assertFalse(TOTPService.enforced())
        with override_settings(MFA_ENFORCEMENT=' Required '):
            self.assertTrue(TOTPService.enforced())

    def test_the_enrollment_page_offers_no_postponing(self) -> None:
        response = self.client.get(reverse('accounts:mfa_setup'))
        self.assertContains(response, 'requires two-factor')
        self.assertNotContains(response, 'Remind me in a week')

    def test_postponing_is_refused_even_when_posted_directly(self) -> None:
        response = self.client.post(reverse('accounts:mfa_setup'), {'action': 'snooze'})
        self.assertContains(response, 'required by your administrator')
        self.user.refresh_from_db()
        self.assertIsNone(self.user.mfa_remind_after)
        self.assertFalse(AuditService.has('mfa_setup_postponed'))
        self.assertRedirects(
            self.client.get(reverse('accounts:dashboard')),
            reverse('accounts:mfa_setup'),
            fetch_redirect_response=False,
        )

    def test_a_snooze_set_earlier_no_longer_skips_enrollment(self) -> None:
        self.user.mfa_remind_after = timezone.now() + timedelta(days=5)
        self.user.save()
        self.assertTrue(TOTPService.prompt_due(self.user))
        self.assertRedirects(
            self.client.get(reverse('accounts:dashboard')),
            reverse('accounts:mfa_setup'),
            fetch_redirect_response=False,
        )

    def test_a_login_that_switched_it_off_earlier_is_prompted_again(self) -> None:
        self.user.mfa_required = False
        self.user.save()
        self.assertRedirects(
            self.client.get(reverse('accounts:dashboard')),
            reverse('accounts:mfa_setup'),
            fetch_redirect_response=False,
        )

    def test_an_enrolled_login_cannot_switch_it_off(self) -> None:
        secret = self._enroll()
        with self.assertRaises(MFAError):
            TOTPService.disable_second_factor(self.user, _code_now(secret))
        response = self.client.post(
            reverse('accounts:mfa_setup'), {'action': 'disable', 'code': _code_now(secret)}
        )
        self.assertContains(response, 'required by your administrator')
        self.assertTrue(TOTPService.has_verified_device(self.user))
        self.assertNotContains(
            self.client.get(reverse('accounts:mfa_setup')), 'Turn off two-factor'
        )

    def test_enrollment_itself_still_works(self) -> None:
        self._enroll()
        self.assertTrue(TOTPService.has_verified_device(self.user))
        self.assertFalse(TOTPService.prompt_due(self.user))


class OptionalPolicyIsUnchangedTests(MailTablesTestCase):
    """The default must not lock out existing installs on upgrade."""

    def test_default_policy_is_optional(self) -> None:
        from django.conf import settings

        self.assertEqual(settings.MFA_ENFORCEMENT, 'optional')
        self.assertFalse(TOTPService.enforced())


class BreakGlassCommandTests(MailTablesTestCase):
    def test_the_shell_command_removes_the_factor_and_is_audited(self) -> None:
        user = MailUser.objects.create_user('owner@ifinmail.test', GOOD, is_staff=True)
        _, secret = TOTPService.start_enrollment(user)
        TOTPService.confirm_enrollment(user, _code_now(secret))
        call_command('reset_mfa', 'Owner@ifinmail.test', stdout=StringIO())
        self.assertFalse(TOTPService.has_verified_device(user))
        self.assertTrue(AuditService.has('mfa_reset_cli', severity='warning'))

    def test_an_unknown_login_is_an_error(self) -> None:
        with self.assertRaises(CommandError):
            call_command('reset_mfa', 'nobody@ifinmail.test', stdout=StringIO())


class ProvisioningContractTests(MailTablesTestCase):
    def test_new_installs_default_to_required_and_the_setting_reaches_the_app(self) -> None:
        compose = yaml.safe_load((DOCKER / 'docker-compose.yml').read_text())['services']
        for service in ('api', 'worker'):
            env = compose[service]['environment']
            self.assertEqual(env['MFA_ENFORCEMENT'], '${MFA_ENFORCEMENT:-optional}')
            self.assertEqual(env['AUDIT_RETENTION_DAYS'], '${AUDIT_RETENTION_DAYS:-365}')
        scripts = DOCKER.parent / 'scripts'
        for name in ('bootstrap.sh', 'provision.sh', 'setup-wizard.sh'):
            self.assertIn('MFA_ENFORCEMENT=required', (scripts / name).read_text(), msg=name)
