"""MFA: TOTP math, enrollment, login verification, enforcement, recovery."""

from __future__ import annotations

import base64
import time

from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.mfa import (
    MFAError,
    TOTPService,
    _hotp,
    generate_secret,
    verify_code,
)
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.mail.models import Mailbox

GOOD = 'Correct-Horse-9'
MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'
# RFC 6238 vector: secret "12345678901234567890", T=59 -> 94287082 (last6 287082).
RFC_SECRET = base64.b32encode(b'12345678901234567890').decode()


def _code_now(secret: str) -> str:
    step = int(time.time() // 30)
    return _hotp(base64.b32decode(secret), step)


class TOTPMathTests(SimpleTestCase):
    def test_rfc_vector_matches(self) -> None:
        self.assertTrue(verify_code(RFC_SECRET, '287082', at=59))
        self.assertTrue(verify_code(RFC_SECRET, '94287082', at=59))
        self.assertFalse(verify_code(RFC_SECRET, '000000', at=59))

    def test_drift_one_step_ok_two_steps_out(self) -> None:
        self.assertTrue(verify_code(RFC_SECRET, '287082', at=59 + 30))
        self.assertTrue(verify_code(RFC_SECRET, '287082', at=59 - 30))
        self.assertFalse(verify_code(RFC_SECRET, '287082', at=59 + 61))
        self.assertFalse(verify_code(RFC_SECRET, '287082', at=59 - 61))

    def test_garbage_is_rejected(self) -> None:
        for bad in ('', 'abcdef', '12 34', '!!!!!!', '1234567!'):
            self.assertFalse(verify_code(RFC_SECRET, bad, at=59))
        self.assertFalse(verify_code('not-base32!!!', '287082', at=59))

    def test_generated_secrets_verify(self) -> None:
        secret = generate_secret()
        self.assertTrue(verify_code(secret, _code_now(secret)))


class MFAEnrollmentTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.user = MailUser.objects.create_user('admin@ifinmail.test', GOOD, is_staff=True)

    def test_start_confirm_and_login_with_totp(self) -> None:
        uri, secret = TOTPService.start_enrollment(self.user)
        self.assertIn('otpauth://totp/', uri)
        self.assertFalse(TOTPService.has_verified_device(self.user))
        with self.assertRaises(MFAError):
            TOTPService.confirm_enrollment(self.user, '000000')
        codes = TOTPService.confirm_enrollment(self.user, _code_now(secret))
        self.assertEqual(len(codes), 10)
        self.assertTrue(TOTPService.has_verified_device(self.user))
        self.assertEqual(TOTPService.verify_login(self.user, _code_now(secret)), 'totp')

    def test_recovery_code_works_once_then_dies(self) -> None:
        _, secret = TOTPService.start_enrollment(self.user)
        codes = TOTPService.confirm_enrollment(self.user, _code_now(secret))
        self.assertEqual(TOTPService.verify_login(self.user, codes[3]), 'recovery')
        with self.assertRaises(MFAError):
            TOTPService.verify_login(self.user, codes[3])
        # TOTP still fine after a recovery use.
        self.assertEqual(TOTPService.verify_login(self.user, _code_now(secret)), 'totp')

    def test_secrets_encrypted_and_status_hides_them(self) -> None:
        _, secret = TOTPService.start_enrollment(self.user)
        from backend.apps.accounts.models import TOTPDevice

        row = TOTPDevice.objects.get(user=self.user)
        self.assertNotIn(secret, row.secret_encrypted)
        status = TOTPService.status_for(self.user)
        self.assertFalse(status['enabled'])
        self.assertTrue(status['pending'])

    def test_reset_wipes_everything(self) -> None:
        _, secret = TOTPService.start_enrollment(self.user)
        TOTPService.confirm_enrollment(self.user, _code_now(secret))
        TOTPService.reset(self.user)
        self.assertFalse(TOTPService.has_verified_device(self.user))
        self.assertEqual(TOTPService.remaining_recovery_codes(self.user), 0)


class MFALoginFlowTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.user = MailUser.objects.create_user('admin@ifinmail.test', GOOD, is_staff=True)

    def _staff_session(self) -> None:
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def test_password_then_code_signs_in(self) -> None:
        from backend.apps.accounts.services.setup_state import SetupState

        SetupState.mark_complete()
        _, secret = TOTPService.start_enrollment(self.user)
        TOTPService.confirm_enrollment(self.user, _code_now(secret))
        response = self.client.post(
            reverse('accounts:login'), {'email': self.user.email, 'password': GOOD}
        )
        self.assertRedirects(response, reverse('accounts:mfa_verify'))
        self.assertNotIn('_auth_user_id', self.client.session)
        response = self.client.post(
            reverse('accounts:mfa_verify'), {'code': _code_now(secret)}, follow=True
        )
        self.assertContains(response, 'Dashboard')
        self.assertIn('_auth_user_id', self.client.session)
        self.assertIn('mfa_verified_at', self.client.session)

    def test_wrong_code_keeps_you_out_and_is_audited(self) -> None:
        _, secret = TOTPService.start_enrollment(self.user)
        TOTPService.confirm_enrollment(self.user, _code_now(secret))
        self.client.post(
            reverse('accounts:login'), {'email': self.user.email, 'password': GOOD}
        )
        response = self.client.post(reverse('accounts:mfa_verify'), {'code': '000000'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'did not match')
        self.assertNotIn('_auth_user_id', self.client.session)
        from backend.services.models import AuditEvent

        self.assertTrue(AuditEvent.objects.filter(action='mfa_failed').exists())

    def test_verify_rate_limits_after_five_bad_codes(self) -> None:
        with override_settings(
            CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
        ):
            _, secret = TOTPService.start_enrollment(self.user)
            TOTPService.confirm_enrollment(self.user, _code_now(secret))
            self.client.post(
                reverse('accounts:login'), {'email': self.user.email, 'password': GOOD}
            )
            for _ in range(5):
                self.client.post(reverse('accounts:mfa_verify'), {'code': '000000'})
            response = self.client.post(
                reverse('accounts:mfa_verify'), {'code': _code_now(secret)}
            )
            self.assertContains(response, 'Too many attempts')
            self.assertNotIn('_auth_user_id', self.client.session)

    def test_device_less_login_goes_to_enrollment(self) -> None:
        from backend.apps.accounts.services.setup_state import SetupState

        SetupState.mark_complete()
        response = self.client.post(
            reverse('accounts:login'), {'email': self.user.email, 'password': GOOD}
        )
        self.assertRedirects(response, reverse('accounts:mfa_setup'))
        # ...and the middleware holds every console page there.
        self.assertRedirects(
            self.client.get(reverse('accounts:dashboard')), reverse('accounts:mfa_setup')
        )

    def test_enrollment_pages_flow_end_to_end(self) -> None:
        self.client.force_login(self.user, backend=MODEL_BACKEND)
        self._staff_session()
        response = self.client.post(reverse('accounts:mfa_setup'), {'action': 'start'})
        secret = response.context['secret']
        self.assertContains(response, 'authenticator app')
        response = self.client.post(
            reverse('accounts:mfa_setup'),
            {'action': 'confirm', 'code': _code_now(secret)},
            follow=True,
        )
        self.assertContains(response, 'recovery codes')
        self.assertTrue(TOTPService.has_verified_device(self.user))

    def test_admin_can_reset_another_profiles_factor(self) -> None:
        from backend.apps.domains.models import Domain

        domain = Domain.objects.create(name='ifinmail.test')
        mailbox = Mailbox.objects.create(domain=domain, local_part='alice')
        MailUser.objects.create_user('alice@ifinmail.test', GOOD)
        self.client.force_login(self.user, backend=MODEL_BACKEND)
        self._staff_session()
        _, secret = TOTPService.start_enrollment(
            MailUser.objects.get(email='alice@ifinmail.test')
        )
        TOTPService.confirm_enrollment(
            MailUser.objects.get(email='alice@ifinmail.test'), _code_now(secret)
        )
        response = self.client.post(
            reverse('accounts:mailbox_mfa_reset', kwargs={'mailbox_id': mailbox.id}),
            follow=True,
        )
        self.assertContains(response, 'Second factor removed')
        self.assertFalse(
            TOTPService.has_verified_device(MailUser.objects.get(email='alice@ifinmail.test'))
        )

    def test_cannot_reset_your_own_factor(self) -> None:
        from backend.apps.domains.models import Domain

        # admin@ifinmail.test is both viewer and target here.
        domain = Domain.objects.create(name='ifinmail.test')
        mailbox = Mailbox.objects.create(domain=domain, local_part='admin')
        self.client.force_login(self.user, backend=MODEL_BACKEND)
        self._staff_session()
        response = self.client.post(
            reverse('accounts:mailbox_mfa_reset', kwargs={'mailbox_id': mailbox.id}),
            follow=True,
        )
        self.assertContains(response, 'your own second factor')


class SessionIdleTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.user = MailUser.objects.create_user('admin@ifinmail.test', GOOD, is_staff=True)
        self.client.force_login(self.user, backend=MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def test_fresh_session_passes_and_stamps_activity(self) -> None:
        response = self.client.get(reverse('accounts:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('last_activity', self.client.session)

    def test_idle_session_is_ended_with_a_message(self) -> None:
        import time

        session = self.client.session
        session['last_activity'] = time.time() - 3700
        session.save()
        response = self.client.get(reverse('accounts:dashboard'), follow=True)
        self.assertContains(response, 'signed out after 30 minutes of inactivity')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_non_staff_sessions_expire_too(self) -> None:
        import time

        plain = MailUser.objects.create_user('plain@ifinmail.test', GOOD)
        self.client.force_login(plain, backend=MODEL_BACKEND)
        session = self.client.session
        session['last_activity'] = time.time() - 3700
        session.save()
        self.client.get(reverse('accounts:login'))
        self.assertNotIn('_auth_user_id', self.client.session)


class SessionInventoryTests(MailTablesTestCase):
    def test_live_counts_attribute_sessions_to_users(self) -> None:
        from backend.apps.accounts.services.sessions import UserSessionService

        admin = MailUser.objects.create_user('root@ifinmail.test', GOOD, is_staff=True)
        self.client.force_login(admin, backend=MODEL_BACKEND)
        self.client.get(reverse('accounts:dashboard'))
        counts = UserSessionService.live_counts()
        self.assertGreaterEqual(counts.get('root@ifinmail.test', 0), 1)

    def test_users_page_lists_live_sessions(self) -> None:
        admin = MailUser.objects.create_user('root@ifinmail.test', GOOD, is_staff=True)
        self.client.force_login(admin, backend=MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()
        html = self.client.get(reverse('accounts:user_management')).content.decode()
        self.assertIn('root@ifinmail.test', html)


class PasswordResetAuditTests(MailTablesTestCase):
    def test_reset_request_and_completion_are_audited(self) -> None:
        from backend.services.models import AuditEvent

        MailUser.objects.create_user('admin@ifinmail.test', GOOD, is_staff=True)
        self.client.post(
            reverse('accounts:password_reset'), {'email': 'admin@ifinmail.test'}
        )
        self.assertTrue(
            AuditEvent.objects.filter(action='password_reset_requested').exists()
        )
