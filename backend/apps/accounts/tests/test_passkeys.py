"""Passkeys through the console: register, sign in without a password, second step, remove."""

from __future__ import annotations

import json
import uuid
from typing import Any

from django.test import override_settings
from django.urls import reverse

from backend.apps.accounts.models import MailUser, Passkey, TOTPDevice
from backend.apps.accounts.services import passkeys
from backend.apps.accounts.services.mfa import TOTPService
from backend.apps.accounts.services.webauthn import EDDSA, b64url_decode
from backend.apps.accounts.tests import test_assistant_views as base
from backend.apps.accounts.tests.virtual_authenticator import VirtualAuthenticator
from backend.apps.core.platform.models import AuditEvent

S = {'secure': True}  # passkeys need https; the test client says so


class PasskeyBase(base.AssistantBase):
    def post_json(self, name: str, body: dict[str, Any] | None = None, **kw: Any):
        return self.client.post(
            reverse(name), data=json.dumps(body or {}), content_type='application/json', **S, **kw
        )

    def register(
        self, authenticator: VirtualAuthenticator, name: str = 'Laptop', **create: Any
    ) -> Any:
        options = self.client.post(
            reverse('accounts:passkey_register_options'),
            {'name': name, 'confirm_password': base.GOOD},
            **S,
        ).json()
        assert options['ok'], options
        payload = authenticator.create(options['options'], **create)
        return self.post_json('accounts:passkey_register_verify', payload)


class RegistrationTests(PasskeyBase):
    def test_a_password_is_needed_to_start_and_nothing_is_stored_without_it(self) -> None:
        response = self.client.post(
            reverse('accounts:passkey_register_options'),
            {'name': 'x', 'confirm_password': 'wrong'},
            **S,
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Passkey.objects.exists())

    def test_the_options_ask_for_a_verified_discoverable_credential(self) -> None:
        options = self.client.post(
            reverse('accounts:passkey_register_options'),
            {'name': 'Work phone', 'confirm_password': base.GOOD},
            **S,
        ).json()['options']
        self.assertEqual(options['rp']['id'], 'testserver')
        self.assertEqual(options['attestation'], 'none')
        select = options['authenticatorSelection']
        self.assertEqual(
            (select['residentKey'], select['userVerification']), ('required', 'required')
        )
        self.assertEqual(b64url_decode(options['user']['id']).decode(), str(self.admin.pk))
        self.assertEqual(len(b64url_decode(options['challenge'])), 32)

    def test_registering_stores_only_public_material_and_is_audited(self) -> None:
        authenticator = VirtualAuthenticator(synced=True)
        response = self.register(authenticator, 'Phone')
        self.assertTrue(response.json()['ok'])
        row = Passkey.objects.get()
        self.assertEqual((row.user_id, row.name), (self.admin.pk, 'Phone'))
        self.assertEqual(b64url_decode(row.credential_id), authenticator.credential_id)
        self.assertEqual(b64url_decode(row.public_key), authenticator.cose_key())
        self.assertTrue(row.backup_eligible)
        event = AuditEvent.objects.get(action='passkey_registered')
        self.assertIn('Phone', event.detail)
        self.assertNotIn(row.public_key, event.detail)

    def test_a_challenge_can_be_answered_once(self) -> None:
        authenticator = VirtualAuthenticator()
        options = self.client.post(
            reverse('accounts:passkey_register_options'),
            {'name': 'x', 'confirm_password': base.GOOD},
            **S,
        ).json()['options']
        payload = authenticator.create(options)
        self.assertTrue(self.post_json('accounts:passkey_register_verify', payload).json()['ok'])
        again = self.post_json('accounts:passkey_register_verify', payload)
        self.assertEqual(again.status_code, 400)
        self.assertEqual(Passkey.objects.count(), 1)

    def test_a_response_for_another_site_is_refused_and_audited(self) -> None:
        response = self.register(VirtualAuthenticator(), origin='https://evil.example')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Passkey.objects.exists())
        self.assertTrue(AuditEvent.objects.filter(action='passkey_register_failed').exists())

    def test_the_same_passkey_cannot_be_added_twice(self) -> None:
        authenticator = VirtualAuthenticator()
        self.assertTrue(self.register(authenticator).json()['ok'])
        second = self.register(authenticator)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(Passkey.objects.count(), 1)

    def test_a_login_holds_a_bounded_number(self) -> None:
        for _ in range(passkeys.MAX_PER_USER):
            self.assertTrue(self.register(VirtualAuthenticator()).json()['ok'])
        refused = self.client.post(
            reverse('accounts:passkey_register_options'),
            {'name': 'x', 'confirm_password': base.GOOD},
            **S,
        )
        self.assertEqual(refused.status_code, 400)

    def test_an_ip_address_cannot_be_a_passkey_domain(self) -> None:
        with override_settings(ALLOWED_HOSTS=['*']):
            response = self.client.post(
                reverse('accounts:passkey_register_options'),
                {'name': 'x', 'confirm_password': base.GOOD},
                HTTP_HOST='203.0.113.5',
                **S,
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('domain name', response.json()['error'])

    def test_plain_http_is_refused(self) -> None:
        response = self.client.post(
            reverse('accounts:passkey_register_options'),
            {'name': 'x', 'confirm_password': base.GOOD},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('secure', response.json()['error'])

    def test_registering_does_not_mark_the_session_as_second_factor_proof(self) -> None:
        self.register(VirtualAuthenticator())
        self.assertNotEqual(self.client.session.get('mfa_method'), 'passkey')


class PasswordlessSignInTests(PasskeyBase):
    def setUp(self) -> None:
        super().setUp()
        self.authenticator = VirtualAuthenticator()
        self.register(self.authenticator)
        self.client.logout()

    def sign_in(self, **get: Any):
        options = self.post_json('accounts:passkey_login_options').json()['options']
        payload = self.authenticator.get(options, user_handle=str(self.admin.pk).encode(), **get)
        return self.post_json('accounts:passkey_login_verify', payload)

    def test_it_signs_in_without_a_password_and_counts_as_two_factors(self) -> None:
        response = self.sign_in()
        self.assertTrue(response.json()['ok'])
        self.assertEqual(self.client.session['_auth_user_id'], str(self.admin.pk))
        self.assertEqual(self.client.session['mfa_method'], 'passkey')
        self.assertTrue(self.client.session['mfa_verified_at'])
        self.assertEqual(self.client.get(reverse('accounts:dashboard')).status_code, 200)
        event = AuditEvent.objects.filter(action='login_success').latest('time')
        self.assertIn('method=passkey', event.detail)

    def test_the_session_key_is_cycled(self) -> None:
        before = self.client.session.session_key
        self.sign_in()
        self.assertNotEqual(self.client.session.session_key, before)

    def test_a_forged_signature_does_not_sign_anyone_in(self) -> None:
        response = self.sign_in(tamper_signature=True)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertTrue(AuditEvent.objects.filter(action='passkey_login_failed').exists())

    def test_a_replayed_response_does_not_work_twice(self) -> None:
        options = self.post_json('accounts:passkey_login_options').json()['options']
        payload = self.authenticator.get(options, user_handle=str(self.admin.pk).encode())
        self.assertTrue(self.post_json('accounts:passkey_login_verify', payload).json()['ok'])
        self.client.logout()
        self.assertEqual(self.post_json('accounts:passkey_login_verify', payload).status_code, 401)

    def test_a_cloned_authenticator_is_refused_and_flagged(self) -> None:
        self.assertTrue(self.sign_in().json()['ok'])
        self.client.logout()
        options = self.post_json('accounts:passkey_login_options').json()['options']
        clone = self.authenticator.get(options, counter=1)  # the counter went backwards
        self.assertEqual(self.post_json('accounts:passkey_login_verify', clone).status_code, 401)
        self.assertTrue(AuditEvent.objects.filter(action='passkey_clone_suspected').exists())

    def test_a_passkey_of_another_person_in_the_handle_is_refused(self) -> None:
        options = self.post_json('accounts:passkey_login_options').json()['options']
        payload = self.authenticator.get(options, user_handle=str(uuid.uuid4()).encode())
        self.assertEqual(self.post_json('accounts:passkey_login_verify', payload).status_code, 401)

    def test_an_unknown_passkey_gets_the_same_answer(self) -> None:
        options = self.post_json('accounts:passkey_login_options').json()['options']
        stranger = VirtualAuthenticator()
        payload = stranger.get(options)
        response = self.post_json('accounts:passkey_login_verify', payload)
        known = self.post_json('accounts:passkey_login_options').json()
        self.assertEqual(response.status_code, 401)
        self.assertTrue(known['ok'])
        self.assertIn('could not be used', response.json()['error'])

    def test_a_deactivated_login_cannot_sign_in(self) -> None:
        MailUser.objects.filter(pk=self.admin.pk).update(is_active=False)
        self.assertEqual(self.sign_in().status_code, 401)

    def test_an_ordinary_mailbox_has_no_console(self) -> None:
        MailUser.objects.filter(pk=self.admin.pk).update(is_staff=False, is_superuser=False)
        response = self.sign_in()
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_attempts_are_rate_limited(self) -> None:
        from django.core.cache import cache

        with override_settings(
            CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
        ):
            cache.clear()
            last = None
            for _ in range(25):
                last = self.post_json('accounts:passkey_login_options')
            assert last is not None
            self.assertEqual(last.status_code, 429)
            cache.clear()


class PasskeyIsASignInNotASecondStepTests(PasskeyBase):
    """A passkey replaces the email and password. It is never a step after them."""

    def setUp(self) -> None:
        super().setUp()
        self.authenticator = VirtualAuthenticator(EDDSA)
        self.register(self.authenticator, 'Security key')
        self.client.logout()

    def password_step(self) -> Any:
        return self.client.post(
            reverse('accounts:login'), {'email': self.admin.email, 'password': base.GOOD}, **S
        )

    def test_a_password_sign_in_is_not_followed_by_a_passkey_step(self) -> None:
        response = self.password_step()
        # No second step: the password alone signs a passkey holder in (an authenticator app, if
        # they had one, is the only thing that adds a step).
        self.assertNotEqual(response.url, reverse('accounts:mfa_verify'))
        self.assertIn('_auth_user_id', self.client.session)

    def test_the_second_step_page_has_no_passkey_button(self) -> None:
        TOTPDevice.objects.create(user=self.admin, secret_encrypted='x', verified=True)
        response = self.password_step()
        self.assertRedirects(
            response, reverse('accounts:mfa_verify'), fetch_redirect_response=False
        )
        page = self.client.get(reverse('accounts:mfa_verify'), **S)
        self.assertContains(page, 'Verify')
        self.assertNotContains(page, 'Use a passkey')
        self.assertNotContains(page, 'data-passkey-signin')

    def test_the_passkey_second_step_endpoints_are_gone(self) -> None:
        from django.urls import NoReverseMatch

        for name in ('mfa_passkey_options', 'mfa_passkey_verify'):
            with self.subTest(name=name), self.assertRaises(NoReverseMatch):
                reverse(f'accounts:{name}')

    def test_signing_in_with_the_passkey_needs_no_email_password_or_code(self) -> None:
        TOTPDevice.objects.create(user=self.admin, secret_encrypted='x', verified=True)
        options = self.post_json('accounts:passkey_login_options').json()['options']
        self.assertEqual(options.get('allowCredentials', []), [])  # usernameless
        response = self.post_json('accounts:passkey_login_verify', self.authenticator.get(options))
        self.assertTrue(response.json()['ok'])
        self.assertEqual(self.client.session['_auth_user_id'], str(self.admin.pk))
        self.assertTrue(self.client.session.get('mfa_verified_at'))  # no authenticator prompt
        console = self.client.get(reverse('accounts:dashboard'), **S)
        self.assertEqual(console.status_code, 200)

    def test_a_passkey_does_not_make_a_password_sign_in_two_factor(self) -> None:
        self.assertFalse(TOTPService.has_second_factor(self.admin))
        TOTPDevice.objects.create(user=self.admin, secret_encrypted='x', verified=True)
        self.assertTrue(TOTPService.has_second_factor(self.admin))

    def test_registering_a_passkey_does_not_unlock_the_current_session(self) -> None:
        self.client.logout()
        # a session that has only been through the password
        self.client.force_login(self.admin, backend='django.contrib.auth.backends.ModelBackend')
        self.register(VirtualAuthenticator(), 'Second key')
        self.assertFalse(self.client.session.get('mfa_verified_at'))


class PolicyAndManagementTests(PasskeyBase):
    def test_a_passkey_does_not_end_the_authenticator_prompt(self) -> None:
        # Under the required policy a password sign-in still needs an authenticator app: a
        # passkey is another way in, not a second step after the password.
        with override_settings(MFA_ENFORCEMENT='required'):
            self.assertTrue(TOTPService.prompt_due(self.admin))
            self.register(VirtualAuthenticator())
            self.assertTrue(TOTPService.prompt_due(self.admin))
            self.assertFalse(TOTPService.has_second_factor(self.admin))

    def test_signing_in_with_a_passkey_satisfies_the_required_policy(self) -> None:
        authenticator = VirtualAuthenticator(EDDSA)
        self.register(authenticator, 'Laptop')
        self.client.logout()
        with override_settings(MFA_ENFORCEMENT='required'):
            options = self.post_json('accounts:passkey_login_options').json()['options']
            self.post_json('accounts:passkey_login_verify', authenticator.get(options))
            self.assertEqual(self.client.get(reverse('accounts:dashboard'), **S).status_code, 200)

    def test_removing_one_needs_the_password_and_is_audited(self) -> None:
        self.register(VirtualAuthenticator(), 'Old laptop')
        row = Passkey.objects.get()
        refused = self.client.post(
            reverse('accounts:passkey_remove'),
            {'id': str(row.pk), 'confirm_password': 'nope'},
            follow=True,
            **S,
        )
        self.assertContains(refused, 'not correct')
        self.assertEqual(Passkey.objects.count(), 1)
        done = self.client.post(
            reverse('accounts:passkey_remove'),
            {'id': str(row.pk), 'confirm_password': base.GOOD},
            follow=True,
            **S,
        )
        self.assertContains(done, 'was removed')
        self.assertFalse(Passkey.objects.exists())
        self.assertTrue(AuditEvent.objects.filter(action='passkey_removed').exists())

    def test_nobody_can_remove_someone_elses(self) -> None:
        other = MailUser.objects.create_user('other@ifinmail.test', base.GOOD, is_staff=True)
        theirs = Passkey.objects.create(
            user=other, name='theirs', credential_id='abc', public_key='def'
        )
        self.client.post(
            reverse('accounts:passkey_remove'),
            {'id': str(theirs.pk), 'confirm_password': base.GOOD},
            **S,
        )
        self.assertTrue(Passkey.objects.filter(pk=theirs.pk).exists())

    def test_the_page_lists_them_and_the_login_page_offers_the_button(self) -> None:
        self.register(VirtualAuthenticator(), 'Work laptop')
        page = self.client.get(reverse('accounts:passkeys'), **S)
        self.assertContains(page, 'Work laptop')
        self.assertContains(page, 'Add a passkey')
        self.client.logout()
        login = self.client.get(reverse('accounts:login'), **S)
        self.assertContains(login, 'Sign in with a passkey')
        self.assertContains(login, 'ifinmail-passkeys.js')

    def test_it_is_in_the_settings_hub(self) -> None:
        self.assertIn(
            reverse('accounts:passkeys'),
            self.client.get(reverse('accounts:settings')).content.decode(),
        )

    def test_the_mfa_policy_page_stays_reachable_for_someone_who_has_to_enrol(self) -> None:
        with override_settings(MFA_ENFORCEMENT='required'):
            self.client.session.pop('mfa_verified_at', None)
            session = self.client.session
            session.pop('mfa_verified_at', None)
            session.save()
            self.assertEqual(self.client.get(reverse('accounts:passkeys'), **S).status_code, 200)
