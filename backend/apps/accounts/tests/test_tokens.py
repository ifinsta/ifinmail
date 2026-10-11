"""Scoped API tokens: lifecycle, scope intersection, endpoint matrix, UI flow."""

from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.roles import RoleService
from backend.apps.accounts.services.tokens import (
    TokenError,
    TokenService,
    format_token,
    split_token,
)
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.domains.models import Domain

GOOD = 'Correct-Horse-9'
MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'


def _verified_session(client) -> None:
    session = client.session
    session['mfa_verified_at'] = timezone.now().isoformat()
    session.save()


class TokenFormatTests(MailTablesTestCase):
    def test_round_trip_and_malformed_rejected(self) -> None:
        self.assertEqual(split_token('ifm.abc123def456.' + 's' * 43), ('abc123def456', 's' * 43))
        for bad in ('', 'Bearer x', 'ifm.onlyone', 'xxx.a.b', 'ifm..secret', 'ifm.a.'):
            self.assertIsNone(split_token(bad))

    def test_format_helper(self) -> None:
        self.assertEqual(format_token('prefix', 'secret'), 'ifm.prefix.secret')


class TokenServiceTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        RoleService.ensure_seed()
        MailUser.objects.create_user(
            'root@ifinmail.test', GOOD, is_staff=True, is_superuser=True
        )
        self.user = MailUser.objects.create_user('api@ifinmail.test', GOOD, is_staff=True)

    def test_create_verify_rotate_revoke(self) -> None:
        row, plain = TokenService.create(
            self.user, 'monitor', ['console.access', 'dns.manage'], expires_in_days=90
        )
        self.assertNotIn(plain, row.token_hash)
        self.assertEqual(set(row.scopes), {'console.access', 'dns.manage'})
        verified = TokenService.verify(plain)
        self.assertIsNotNone(verified)
        assert verified is not None
        self.assertEqual(verified.user.email, 'api@ifinmail.test')
        self.assertIsNotNone(verified.row.last_used_at)
        # Rotation kills the old secret, keeps the prefix.
        _, rotated = TokenService.rotate(self.user, str(row.id))
        self.assertIsNone(TokenService.verify(plain))
        self.assertIsNotNone(TokenService.verify(rotated))
        self.assertTrue(TokenService.revoke(self.user, str(row.id)))
        self.assertIsNone(TokenService.verify(rotated))
        self.assertFalse(TokenService.revoke(self.user, str(row.id)))

    def test_scopes_cannot_exceed_owner_permissions(self) -> None:
        RoleService.assign(self.user, 'support')
        row, _ = TokenService.create(
            self.user, 'narrow', ['console.access', 'dns.manage', 'audit.view'],
            expires_in_days=30,
        )
        self.assertEqual(set(row.scopes), {'console.access', 'audit.view'})
        with self.assertRaises(TokenError):
            TokenService.create(self.user, 'empty', ['dns.manage'], expires_in_days=30)

    def test_expired_and_disabled_owners_fail_closed(self) -> None:
        row, plain = TokenService.create(
            self.user, 'short', ['console.access'], expires_in_days=30
        )
        row.expires_at = timezone.now() - timedelta(seconds=1)
        row.save(update_fields=['expires_at'])
        self.assertIsNone(TokenService.verify(plain))
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        row.expires_at = timezone.now() + timedelta(days=1)
        row.save(update_fields=['expires_at'])
        self.assertIsNone(TokenService.verify(plain))

    def test_validation_errors(self) -> None:
        with self.assertRaises(TokenError):
            TokenService.create(self.user, '', ['console.access'], expires_in_days=30)
        with self.assertRaises(TokenError):
            TokenService.create(self.user, 'x', [], expires_in_days=30)
        with self.assertRaises(TokenError):
            TokenService.create(self.user, 'x', ['nope'], expires_in_days=30)
        with self.assertRaises(TokenError):
            TokenService.create(self.user, 'x', ['console.access'], expires_in_days=400)


class TokenEndpointTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        RoleService.ensure_seed()
        Domain.objects.create(name='ifinmail.test')
        self.user = MailUser.objects.create_user('api@ifinmail.test', GOOD, is_staff=True)
        _, self.plain = TokenService.create(
            self.user, 'reader', ['console.access', 'dns.manage'], expires_in_days=30
        )

    def _get(self, path: str, token: str | None):
        headers = {} if token is None else {'HTTP_AUTHORIZATION': f'Bearer {token}'}
        return self.client.get(path, **headers)

    def test_anonymous_and_malformed_are_401(self) -> None:
        self.assertEqual(self._get('/api/status', None).status_code, 401)
        self.assertEqual(self._get('/api/status', 'junk').status_code, 401)
        self.assertEqual(self._get('/api/status', 'ifm.nope.secret').status_code, 401)

    def test_scoped_calls_succeed_and_cross_scope_is_403(self) -> None:
        response = self._get('/api/status', self.plain)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertEqual(self._get('/api/domains', self.plain).status_code, 200)
        _, narrow = TokenService.create(
            self.user, 'narrow', ['console.access'], expires_in_days=30
        )
        self.assertEqual(self._get('/api/domains', narrow).status_code, 403)

    def test_role_narrowing_shrinks_live_tokens(self) -> None:
        # Token holds dns.manage, but the owner's role loses it mid-flight.
        other = MailUser.objects.create_user(
            'root@ifinmail.test', GOOD, is_staff=True, is_superuser=True
        )
        RoleService.assign(self.user, 'support')
        self.assertEqual(self._get('/api/domains', self.plain).status_code, 403)
        self.assertEqual(self._get('/api/status', self.plain).status_code, 200)
        self.assertTrue(other.is_superuser)  # holder of last resort untouched

    def test_domains_payload_has_no_secrets(self) -> None:
        body = self._get('/api/domains', self.plain).json()
        self.assertEqual(
            set(body[0]),
            {'name', 'verified', 'mx_verified', 'spf_verified', 'dkim_verified',
             'dmarc_verified'},
        )
        self.assertEqual(body[0]['name'], 'ifinmail.test')

    def test_openapi_contract_exists_docs_ui_does_not(self) -> None:
        self.assertEqual(self.client.get('/api/openapi.json').status_code, 200)
        self.assertEqual(self.client.get('/api/docs').status_code, 404)


class TokenProfileFlowTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        RoleService.ensure_seed()
        Domain.objects.create(name='ifinmail.test')
        self.admin = MailUser.objects.create_user(
            'root@ifinmail.test', GOOD, is_staff=True, is_superuser=True
        )
        self.client.force_login(self.admin, backend=MODEL_BACKEND)
        _verified_session(self.client)

    def _profile(self, local: str):
        from backend.apps.mail.services import MailboxService

        mailbox, _ = MailboxService.create('ifinmail.test', local, GOOD, is_admin=True)
        return mailbox

    def test_create_shows_secret_once_then_lists(self) -> None:
        mailbox = self._profile('alice')
        url = reverse('accounts:mailbox_profile', kwargs={'mailbox_id': mailbox.id})
        response = self.client.post(
            reverse('accounts:mailbox_token_create', kwargs={'mailbox_id': mailbox.id}),
            {
                'address': 'alice@ifinmail.test',
                'name': 'monitor',
                'scopes': ['console.access'],
                'expires_in_days': '90',
            },
        )
        self.assertRedirects(response, url, fetch_redirect_response=False)
        html = self.client.get(url).content.decode()
        self.assertIn('id="api-token-value"', html)
        self.assertIn('ifm.', html)
        refreshed = self.client.get(url).content.decode()
        self.assertNotIn('id="api-token-value"', refreshed)
        self.assertIn('monitor', refreshed)

    def test_rotate_and_revoke_from_profile(self) -> None:
        from backend.services.models import AuditEvent

        mailbox = self._profile('alice')
        url = reverse('accounts:mailbox_profile', kwargs={'mailbox_id': mailbox.id})
        self.client.post(
            reverse('accounts:mailbox_token_create', kwargs={'mailbox_id': mailbox.id}),
            {
                'address': 'alice@ifinmail.test',
                'name': 'monitor',
                'scopes': ['console.access'],
                'expires_in_days': '90',
            },
        )
        from backend.apps.accounts.models import APIToken

        row = APIToken.objects.get(user__email='alice@ifinmail.test')
        action_url = reverse(
            'accounts:mailbox_token_action', kwargs={'mailbox_id': mailbox.id}
        )
        self.client.post(
            action_url,
            {'address': 'alice@ifinmail.test', 'token_id': str(row.id), 'action': 'rotate'},
        )
        html = self.client.get(url).content.decode()
        self.assertIn('id="api-token-value"', html)
        self.client.post(
            action_url,
            {'address': 'alice@ifinmail.test', 'token_id': str(row.id), 'action': 'revoke'},
            follow=True,
        )
        self.assertFalse(APIToken.objects.filter(pk=row.id).exists())
        for action in ('api_token_created', 'api_token_rotated', 'api_token_revoked'):
            self.assertTrue(AuditEvent.objects.filter(action=action).exists())

    def test_non_staff_profile_cannot_mint_tokens(self) -> None:
        from backend.apps.mail.services import MailboxService

        mailbox, _ = MailboxService.create('ifinmail.test', 'bob', GOOD)
        html = self.client.get(
            reverse('accounts:mailbox_profile', kwargs={'mailbox_id': mailbox.id})
        ).content.decode()
        self.assertIn('holds no permissions', html)
        response = self.client.post(
            reverse('accounts:mailbox_token_create', kwargs={'mailbox_id': mailbox.id}),
            {
                'address': 'bob@ifinmail.test',
                'name': 'x',
                'scopes': ['console.access'],
                'expires_in_days': '30',
            },
            follow=True,
        )
        self.assertContains(response, 'None of those scopes are held by this login.')
