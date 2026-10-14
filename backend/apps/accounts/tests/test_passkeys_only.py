"""Passkeys-only console sign-in: the password stops opening the console, with a way back."""

from __future__ import annotations

import re
from typing import Any

from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from backend.apps.accounts.models import MailUser, Passkey, PasskeyRecoveryCode, TOTPDevice
from backend.apps.accounts.services.passwordless import PasswordlessError, PasswordlessService
from backend.apps.accounts.services.webauthn import EDDSA
from backend.apps.accounts.tests import test_assistant_views as base
from backend.apps.accounts.tests.test_passkeys import PasskeyBase, S
from backend.apps.accounts.tests.virtual_authenticator import VirtualAuthenticator
from backend.apps.core.platform.models import AuditEvent

LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
CODE = re.compile(r'\b[a-z2-9]{4}(?:-[a-z2-9]{4}){3}\b')


class OnBase(PasskeyBase):
    """An administrator with two passkeys and passkeys-only turned on."""

    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.keys = [VirtualAuthenticator(EDDSA), VirtualAuthenticator(EDDSA)]
        for index, key in enumerate(self.keys):
            self.register(key, f'Key {index + 1}')

    def enable(self, **extra: str) -> Any:
        data = {'confirm_password': base.GOOD, 'understand': 'on', **extra}
        return self.client.post(reverse('accounts:passkeys_only_enable'), data, **S)

    def codes_in(self, response: Any) -> list[str]:
        return CODE.findall(response.content.decode())

    def password_login(self, password: str = base.GOOD) -> Any:
        return self.client.post(
            reverse('accounts:login'), {'email': self.admin.email, 'password': password}, **S
        )


class EligibilityTests(PasskeyBase):
    def test_needs_two_passkeys_or_one_that_syncs(self) -> None:
        service = PasswordlessService
        self.assertFalse(service.eligibility(self.admin).ok)  # none
        self.register(VirtualAuthenticator(EDDSA, synced=False), 'Device only')
        verdict = service.eligibility(self.admin)
        self.assertFalse(verdict.ok)
        self.assertIn('second passkey', verdict.reason)
        self.register(VirtualAuthenticator(EDDSA, synced=False), 'Another')
        self.assertTrue(service.eligibility(self.admin).ok)

    def test_one_synced_passkey_is_enough(self) -> None:
        self.register(VirtualAuthenticator(EDDSA, synced=True), 'Phone')
        self.assertTrue(PasswordlessService.eligibility(self.admin).ok)

    def test_it_cannot_be_enabled_without_enough_passkeys(self) -> None:
        self.register(VirtualAuthenticator(EDDSA, synced=False), 'Only one')
        with self.assertRaises(PasswordlessError):
            PasswordlessService.enable(self.admin)
        self.assertFalse(PasswordlessService.is_passwordless(self.admin))


class EnablingTests(OnBase):
    def test_needs_the_password_and_the_acknowledgement(self) -> None:
        refused = self.client.post(
            reverse('accounts:passkeys_only_enable'),
            {'confirm_password': 'nope', 'understand': 'on'},
            follow=True,
            **S,
        )
        self.assertContains(refused, 'not correct')
        self.assertFalse(PasswordlessService.is_passwordless(self.admin))
        unticked = self.client.post(
            reverse('accounts:passkeys_only_enable'),
            {'confirm_password': base.GOOD},
            follow=True,
            **S,
        )
        self.assertContains(unticked, 'Tick the box')
        self.assertFalse(PasswordlessService.is_passwordless(self.admin))

    def test_turning_it_on_shows_ten_codes_once_and_audits(self) -> None:
        response = self.enable()
        self.assertEqual(response.status_code, 200)
        codes = self.codes_in(response)
        self.assertEqual(len(set(codes)), 10)
        self.assertTrue(PasswordlessService.is_passwordless(self.admin))
        self.assertEqual(PasswordlessService.remaining_codes(self.admin), 10)
        self.assertTrue(AuditEvent.objects.filter(action='passkeys_only_enabled').exists())
        # shown once: the page afterwards has none, and only hashes are stored
        again = self.client.get(reverse('accounts:passkeys'), **S)
        self.assertEqual(self.codes_in(again), [])
        stored = ' '.join(PasskeyRecoveryCode.objects.values_list('code_hash', flat=True))
        for code in codes:
            self.assertNotIn(code.replace('-', ''), stored)


class PasswordNoLongerOpensTheConsoleTests(OnBase):
    def setUp(self) -> None:
        super().setUp()
        self.enable()
        self.client.logout()

    def test_a_correct_password_is_refused_like_a_wrong_one(self) -> None:
        right = self.password_login()
        wrong = self.password_login('definitely-not-it')
        self.assertEqual(right.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        extract = lambda r: re.search(r'ifinmail-login-error">([^<]+)<', r.content.decode())  # noqa: E731
        self.assertEqual(extract(right).group(1), extract(wrong).group(1))
        self.assertTrue(AuditEvent.objects.filter(action='login_password_refused').exists())

    def test_the_passkey_still_signs_in(self) -> None:
        options = self.post_json('accounts:passkey_login_options').json()['options']
        response = self.post_json('accounts:passkey_login_verify', self.keys[0].get(options))
        self.assertTrue(response.json()['ok'])
        self.assertEqual(self.client.session['_auth_user_id'], str(self.admin.pk))

    def test_a_passkey_sign_in_is_still_not_asked_for_an_authenticator_code(self) -> None:
        TOTPDevice.objects.create(user=self.admin, secret_encrypted='x', verified=True)
        options = self.post_json('accounts:passkey_login_options').json()['options']
        self.post_json('accounts:passkey_login_verify', self.keys[1].get(options))
        self.assertEqual(self.client.get(reverse('accounts:dashboard'), **S).status_code, 200)

    def test_the_mailbox_password_itself_is_untouched(self) -> None:
        self.assertTrue(MailUser.objects.get(pk=self.admin.pk).check_password(base.GOOD))

    def test_the_sign_in_page_points_to_the_passkey_and_the_recovery_form(self) -> None:
        page = self.client.get(reverse('accounts:login'), **S)
        self.assertContains(page, reverse('accounts:recovery_login'))


@override_settings(CACHES=LOCMEM)
class RecoveryCodeTests(OnBase):
    def setUp(self) -> None:
        super().setUp()
        self.codes = self.codes_in(self.enable())
        self.client.logout()

    def recover(self, code: str, email: str | None = None) -> Any:
        return self.client.post(
            reverse('accounts:recovery_login'),
            {'email': email or self.admin.email, 'code': code},
            **S,
        )

    def test_a_code_signs_in_once(self) -> None:
        response = self.recover(self.codes[0])
        self.assertRedirects(response, reverse('accounts:passkeys'), fetch_redirect_response=False)
        self.assertEqual(self.client.session['_auth_user_id'], str(self.admin.pk))
        self.assertEqual(PasswordlessService.remaining_codes(self.admin), 9)
        self.assertTrue(AuditEvent.objects.filter(action='login_recovery_code').exists())
        self.client.logout()
        again = self.recover(self.codes[0])
        self.assertEqual(again.status_code, 200)  # the form again, with the error
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_the_page_after_a_recovery_sign_in_says_what_to_do(self) -> None:
        self.recover(self.codes[1])
        page = self.client.get(reverse('accounts:passkeys'), **S)
        self.assertContains(page, 'signed in with a recovery code')

    def test_case_spacing_and_missing_dashes_are_forgiven(self) -> None:
        sloppy = self.codes[2].upper().replace('-', ' ')
        self.assertEqual(self.recover(sloppy).status_code, 302)

    def test_the_answer_is_the_same_for_an_unknown_address_and_a_wrong_code(self) -> None:
        unknown = self.recover(self.codes[3], 'nobody@ifinmail.test')
        wrong = self.recover('aaaa-bbbb-cccc-dddd')
        grab = lambda r: re.search(r'ifinmail-login-error">([^<]+)<', r.content.decode()).group(1)  # noqa: E731
        self.assertEqual(grab(unknown), grab(wrong))

    def test_someone_without_passkeys_only_cannot_use_it_even_with_a_valid_looking_code(
        self,
    ) -> None:
        other = MailUser.objects.create_user('plain@ifinmail.test', base.GOOD, is_staff=True)
        response = self.recover(self.codes[4], other.email)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_a_code_belongs_to_one_login(self) -> None:
        other = MailUser.objects.create_user('other@ifinmail.test', base.GOOD, is_staff=True)
        response = self.recover(self.codes[5], other.email)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PasswordlessService.remaining_codes(self.admin), 10)

    def test_guessing_is_rate_limited(self) -> None:
        for _ in range(8):
            self.recover('aaaa-bbbb-cccc-dddd')
        blocked = self.recover(self.codes[6])
        self.assertContains(blocked, 'Too many attempts')
        self.assertNotIn('_auth_user_id', self.client.session)


class GuardsAndWayBackTests(OnBase):
    def setUp(self) -> None:
        super().setUp()
        self.enable()

    def remove(self, key_index: int) -> Any:
        row = Passkey.objects.order_by('created_at')[key_index]
        return self.client.post(
            reverse('accounts:passkey_remove'),
            {'id': str(row.pk), 'confirm_password': base.GOOD},
            follow=True,
            **S,
        )

    def test_the_passkeys_that_make_it_safe_cannot_be_removed(self) -> None:
        page = self.remove(0)
        self.assertContains(page, 'would leave too few')
        self.assertEqual(Passkey.objects.count(), 2)

    def test_an_extra_passkey_can_be_removed(self) -> None:
        self.register(VirtualAuthenticator(EDDSA), 'Spare')
        self.remove(2)
        self.assertEqual(Passkey.objects.count(), 2)

    def test_new_codes_replace_the_old_ones(self) -> None:
        old = PasskeyRecoveryCode.objects.first()
        response = self.client.post(
            reverse('accounts:passkeys_only_new_codes'), {'confirm_password': base.GOOD}, **S
        )
        self.assertEqual(len(self.codes_in(response)), 10)
        self.assertFalse(PasskeyRecoveryCode.objects.filter(pk=old.pk).exists())

    def test_turning_it_off_needs_the_password_and_removes_the_codes(self) -> None:
        refused = self.client.post(
            reverse('accounts:passkeys_only_disable'), {'confirm_password': 'no'}, **S
        )
        self.assertEqual(refused.status_code, 302)
        self.assertTrue(PasswordlessService.is_passwordless(self.admin))
        self.client.post(
            reverse('accounts:passkeys_only_disable'), {'confirm_password': base.GOOD}, **S
        )
        self.assertFalse(PasswordlessService.is_passwordless(self.admin))
        self.assertEqual(PasskeyRecoveryCode.objects.count(), 0)
        self.client.logout()
        self.assertEqual(self.password_login().status_code, 302)  # the password works again

    def test_the_server_shell_can_switch_it_off(self) -> None:
        call_command('allow_password_login', self.admin.email)
        self.assertFalse(PasswordlessService.is_passwordless(self.admin))
        self.assertTrue(AuditEvent.objects.filter(action='passkeys_only_reset_cli').exists())

    def test_the_status_shown_on_a_profile_says_so(self) -> None:
        from backend.apps.accounts.services.mfa import TOTPService

        self.assertTrue(TOTPService.status_for(self.admin)['passkeys_only'])

    @override_settings(MFA_ENFORCEMENT='required')
    def test_the_required_policy_is_still_met_by_signing_in_with_a_passkey(self) -> None:
        self.client.logout()
        options = self.post_json('accounts:passkey_login_options').json()['options']
        self.post_json('accounts:passkey_login_verify', self.keys[0].get(options))
        self.assertEqual(self.client.get(reverse('accounts:dashboard'), **S).status_code, 200)
