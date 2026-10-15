"""The integration API (/api/v1): credentials, versioning, mail and domain routes, console page.

Everything here goes through the real URL space with a real key, so a break in any layer
(authentication, scopes, the router, the service, the audit trail) fails one of these.
"""

from __future__ import annotations

import base64
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import APIToken, MailUser
from backend.apps.accounts.services.roles import RoleService
from backend.apps.accounts.services.tokens import (
    TokenError,
    TokenService,
    address_allowed,
    key_id,
    normalize_networks,
    parse_key,
)
from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.domains.models import Domain
from backend.apps.mail.services import MailboxService

GOOD = 'Correct-Horse-9'
MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'
LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
LOOKUP = 'backend.apps.domains.services.verification._lookup'
SERVER_IP = 'backend.apps.dns.services.DNSService.get_server_ip'

ALL = ['console.access', 'mail.manage', 'dns.manage', 'audit.view']


def basic(key: str, secret: str) -> str:
    return 'Basic ' + base64.b64encode(f'{key}:{secret}'.encode()).decode()


@override_settings(CACHES=LOCMEM)
class ApiBase(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        from django.core.cache import cache

        cache.clear()
        RoleService.ensure_seed()
        Domain.objects.create(name='ifinmail.test')
        self.owner = MailUser.objects.create_user(
            'root@ifinmail.test', GOOD, is_staff=True, is_superuser=True
        )
        self.row, self.token = TokenService.create(
            self.owner, 'integration', ALL, expires_in_days=30
        )
        self.secret = self.token.split('.', 2)[2]
        self.key = key_id(self.row.prefix)

    # -- helpers -------------------------------------------------------------------------
    def call(
        self,
        method: str,
        path: str,
        *,
        key: str | None = None,
        secret: str | None = None,
        body: dict | None = None,
        extra: dict | None = None,
    ):
        headers = dict(extra or {})
        if key is not None:
            headers['HTTP_AUTHORIZATION'] = basic(key, secret or '')
        kwargs = {'content_type': 'application/json'} if body is not None else {}
        import json

        data = json.dumps(body) if body is not None else None
        fn = getattr(self.client, method)
        return fn(path, data=data, **kwargs, **headers) if data is not None else fn(path, **headers)

    def get(self, path: str, **kw):
        return self.call(
            'get', path, key=kw.pop('key', self.key), secret=kw.pop('secret', self.secret), **kw
        )

    def post(self, path: str, body: dict, **kw):
        return self.call(
            'post',
            path,
            key=kw.pop('key', self.key),
            secret=kw.pop('secret', self.secret),
            body=body,
            **kw,
        )

    def patch(self, path: str, body: dict, **kw):
        return self.call(
            'patch',
            path,
            key=kw.pop('key', self.key),
            secret=kw.pop('secret', self.secret),
            body=body,
            **kw,
        )

    def delete(self, path: str, **kw):
        return self.call(
            'delete', path, key=kw.pop('key', self.key), secret=kw.pop('secret', self.secret), **kw
        )


class CredentialFormatTests(ApiBase):
    def test_key_and_secret_are_recognisable(self) -> None:
        self.assertTrue(self.key.startswith('ifm_'))
        self.assertTrue(self.secret.startswith('ifs_'))
        self.assertEqual(len(self.secret), 4 + 43)
        self.assertNotIn(self.secret, self.row.token_hash)  # only a hash is stored

    def test_parse_key_accepts_the_marker_or_the_bare_prefix(self) -> None:
        self.assertEqual(parse_key(self.key), self.row.prefix)
        self.assertEqual(parse_key(self.row.prefix), self.row.prefix)
        for bad in ('', 'ifm_', 'ifm_a b', 'x' * 30, 'ifm_../etc'):
            self.assertIsNone(parse_key(bad))

    def test_network_lists_are_validated_and_canonical(self) -> None:
        self.assertEqual(
            normalize_networks(['203.0.113.7', '10.0.0.0/8']), ['203.0.113.7/32', '10.0.0.0/8']
        )
        with self.assertRaises(TokenError):
            normalize_networks(['not-an-ip'])
        with self.assertRaises(TokenError):
            normalize_networks([f'10.0.{i}.0/24' for i in range(30)])
        self.assertTrue(address_allowed([], '198.51.100.1'))
        self.assertTrue(address_allowed(['203.0.113.0/24'], '203.0.113.9'))
        self.assertFalse(address_allowed(['203.0.113.0/24'], '198.51.100.1'))
        self.assertFalse(address_allowed(['203.0.113.0/24'], 'garbage'))


class AuthenticationTests(ApiBase):
    def test_basic_and_bearer_both_work_and_carry_the_standard_headers(self) -> None:
        by_basic = self.get('/api/v1/status')
        self.assertEqual(by_basic.status_code, 200)
        self.assertEqual(by_basic['X-API-Version'], '1')
        self.assertEqual(by_basic['Cache-Control'], 'no-store')
        self.assertIn('X-RateLimit-Limit', by_basic)
        by_bearer = self.client.get('/api/v1/status', HTTP_AUTHORIZATION=f'Bearer {self.token}')
        self.assertEqual(by_bearer.status_code, 200)

    def test_a_bare_prefix_is_accepted_as_the_username(self) -> None:
        response = self.get('/api/v1/status', key=self.row.prefix)
        self.assertEqual(response.status_code, 200)

    def test_every_failure_is_the_same_401_with_a_challenge(self) -> None:
        cases = [
            self.call('get', '/api/v1/status'),
            self.get('/api/v1/status', secret='ifs_wrong'),
            self.get('/api/v1/status', key='ifm_doesnotexist'),
            self.get('/api/v1/status', key='', secret=self.secret),
        ]
        bodies = set()
        for response in cases:
            self.assertEqual(response.status_code, 401)
            self.assertIn('Basic', response['WWW-Authenticate'])
            self.assertIn('Bearer', response['WWW-Authenticate'])
            bodies.add(response.content)
        self.assertEqual(len(bodies), 1, 'the response must not reveal why it failed')

    def test_expired_disabled_owner_and_revoked_fail_closed(self) -> None:
        self.row.expires_at = timezone.now() - timedelta(seconds=1)
        self.row.save(update_fields=['expires_at'])
        self.assertEqual(self.get('/api/v1/status').status_code, 401)
        self.row.expires_at = timezone.now() + timedelta(days=1)
        self.row.save(update_fields=['expires_at'])
        self.assertEqual(self.get('/api/v1/status').status_code, 200)
        self.owner.is_active = False
        self.owner.save(update_fields=['is_active'])
        self.assertEqual(self.get('/api/v1/status').status_code, 401)
        self.owner.is_active = True
        self.owner.save(update_fields=['is_active'])
        TokenService.revoke(self.owner, str(self.row.id))
        self.assertEqual(self.get('/api/v1/status').status_code, 401)

    def test_failures_are_audited_once_per_address_and_reason(self) -> None:
        for _ in range(4):
            self.get('/api/v1/status', secret='ifs_wrong')
        self.get('/api/v1/status', key='ifm_nope')
        from backend.apps.core.platform.models import AuditEvent

        events = list(AuditEvent.objects.filter(action='api_auth_failed'))
        reasons = sorted(e.detail.split(' ')[0] for e in events)
        self.assertEqual(reasons, ['bad_secret', 'unknown_key'])
        unknown = next(e for e in events if e.detail.startswith('unknown_key'))
        self.assertEqual(unknown.user, 'api:unknown')  # attacker-supplied text is never echoed

    def test_a_cookie_session_is_not_an_api_credential(self) -> None:
        self.client.force_login(self.owner, backend=MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()
        self.assertEqual(self.client.get('/api/v1/status').status_code, 401)


class RotationTests(ApiBase):
    def test_overlap_keeps_the_old_secret_alive_until_it_ends(self) -> None:
        row, fresh = TokenService.rotate(self.owner, str(self.row.id), grace_hours=2), None
        new_secret = row[1].split('.', 2)[2]
        self.assertEqual(self.get('/api/v1/status', secret=new_secret).status_code, 200)
        self.assertEqual(self.get('/api/v1/status', secret=self.secret).status_code, 200)
        APIToken.objects.filter(pk=self.row.pk).update(
            previous_expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(self.get('/api/v1/status', secret=self.secret).status_code, 401)
        self.assertEqual(self.get('/api/v1/status', secret=new_secret).status_code, 200)
        self.assertIsNone(fresh)

    def test_rotation_without_overlap_cuts_the_old_secret_at_once(self) -> None:
        _, token = TokenService.rotate(self.owner, str(self.row.id))
        self.assertEqual(self.get('/api/v1/status', secret=self.secret).status_code, 401)
        self.assertEqual(self.get('/api/v1/status', secret=token.split('.', 2)[2]).status_code, 200)

    def test_overlap_never_outlives_the_key_and_is_bounded(self) -> None:
        soon = timezone.now() + timedelta(hours=1)
        APIToken.objects.filter(pk=self.row.pk).update(expires_at=soon)
        row, _ = TokenService.rotate(self.owner, str(self.row.id), grace_hours=48)
        self.assertEqual(row.previous_expires_at, soon)
        with self.assertRaises(TokenError):
            TokenService.rotate(self.owner, str(self.row.id), grace_hours=1000)


class NetworkAndRateTests(ApiBase):
    def _restricted(self, **kwargs):
        row, token = TokenService.create(
            self.owner, 'locked', ['console.access'], expires_in_days=30, **kwargs
        )
        return key_id(row.prefix), token.split('.', 2)[2]

    def test_allowed_networks_use_the_address_the_proxy_saw(self) -> None:
        key, secret = self._restricted(allowed_networks=['203.0.113.0/24'])
        ok = self.get(
            '/api/v1/status',
            key=key,
            secret=secret,
            extra={'REMOTE_ADDR': '10.0.0.2', 'HTTP_X_FORWARDED_FOR': '203.0.113.7'},
        )
        self.assertEqual(ok.status_code, 200)
        elsewhere = self.get(
            '/api/v1/status',
            key=key,
            secret=secret,
            extra={'REMOTE_ADDR': '10.0.0.2', 'HTTP_X_FORWARDED_FOR': '198.51.100.1'},
        )
        self.assertEqual(elsewhere.status_code, 401)

    def test_a_forged_forwarded_for_prefix_does_not_widen_access(self) -> None:
        key, secret = self._restricted(allowed_networks=['203.0.113.0/24'])
        forged = self.get(
            '/api/v1/status',
            key=key,
            secret=secret,
            extra={'HTTP_X_FORWARDED_FOR': '203.0.113.7, 198.51.100.1'},
        )
        self.assertEqual(forged.status_code, 401)  # the proxy appended the real peer last

    def test_rate_limit_answers_429_with_retry_after(self) -> None:
        key, secret = self._restricted(rate_limit_per_minute=2)
        self.assertEqual(self.get('/api/v1/status', key=key, secret=secret).status_code, 200)
        second = self.get('/api/v1/status', key=key, secret=secret)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second['X-RateLimit-Remaining'], '0')
        third = self.get('/api/v1/status', key=key, secret=secret)
        self.assertEqual(third.status_code, 429)
        self.assertIn('Retry-After', third)
        self.assertEqual(third['X-RateLimit-Limit'], '2')

    def test_one_keys_budget_is_not_anothers(self) -> None:
        key, secret = self._restricted(rate_limit_per_minute=1)
        self.get('/api/v1/status', key=key, secret=secret)
        self.assertEqual(self.get('/api/v1/status', key=key, secret=secret).status_code, 429)
        self.assertEqual(self.get('/api/v1/status').status_code, 200)

    def test_bad_limits_are_refused(self) -> None:
        for bad in (0, 100000):
            with self.assertRaises(TokenError):
                TokenService.create(
                    self.owner,
                    'x',
                    ['console.access'],
                    expires_in_days=30,
                    rate_limit_per_minute=bad,
                )


class VersioningTests(ApiBase):
    def test_index_lists_versions_without_credentials(self) -> None:
        body = self.client.get('/api/').json()
        self.assertEqual(body['current'], 'v1')
        self.assertEqual(body['versions'][0]['url'], '/api/v1/')
        self.assertEqual(body['versions'][0]['openapi'], '/api/v1/openapi.json')

    def test_unversioned_paths_redirect_with_method_and_query_kept(self) -> None:
        response = self.client.get('/api/mailboxes?limit=5')
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response['Location'], '/api/v1/mailboxes?limit=5')
        self.assertEqual(response['Deprecation'], 'true')
        self.assertIn('successor-version', response['Link'])
        self.assertEqual(self.client.post('/api/mailboxes').status_code, 308)

    def test_an_unknown_version_is_a_404_not_a_redirect(self) -> None:
        self.assertEqual(self.client.get('/api/v2/status').status_code, 404)

    def test_the_contract_is_public_and_describes_both_schemes(self) -> None:
        spec = self.client.get('/api/v1/openapi.json').json()
        self.assertEqual(spec['info']['version'], '1.0.0')
        schemes = spec['components']['securitySchemes']
        self.assertTrue(any(s.get('scheme') == 'basic' for s in schemes.values()))
        self.assertTrue(any(s.get('scheme') == 'bearer' for s in schemes.values()))
        for path in ('/api/v1/mailboxes', '/api/v1/aliases', '/api/v1/domains', '/api/v1/status'):
            self.assertIn(path, spec['paths'])

    def test_no_operation_is_reachable_anonymously_except_liveness(self) -> None:
        spec = self.client.get('/api/v1/openapi.json').json()
        checked = 0
        for path, operations in spec['paths'].items():
            for method in operations:
                url = path.replace('{address}', 'x@ifinmail.test').replace(
                    '{name}', 'ifinmail.test'
                )
                url = url.replace('{alias_id}', 'x').replace('{fingerprint}', 'abc')
                response = getattr(self.client, method)(url)
                if path == '/api/v1/health':
                    self.assertIn(response.status_code, (200, 503))
                    continue
                self.assertEqual(response.status_code, 401, f'{method.upper()} {url}')
                checked += 1
        self.assertGreaterEqual(checked, 18)


class ScopeTests(ApiBase):
    def test_a_key_without_the_scope_is_refused(self) -> None:
        row, token = TokenService.create(
            self.owner, 'narrow', ['console.access'], expires_in_days=30
        )
        kw = {'key': key_id(row.prefix), 'secret': token.split('.', 2)[2]}
        self.assertEqual(self.get('/api/v1/mailboxes', **kw).status_code, 403)
        self.assertEqual(self.get('/api/v1/aliases', **kw).status_code, 403)
        self.assertEqual(self.get('/api/v1/domains', **kw).status_code, 403)
        self.assertEqual(self.get('/api/v1/status', **kw).status_code, 200)

    def test_narrowing_the_owners_role_narrows_the_key(self) -> None:
        helper = MailUser.objects.create_user('helper@ifinmail.test', GOOD, is_staff=True)
        RoleService.assign(helper, 'administrator')
        row, token = TokenService.create(helper, 'h', ['mail.manage'], expires_in_days=30)
        kw = {'key': key_id(row.prefix), 'secret': token.split('.', 2)[2]}
        self.assertEqual(self.get('/api/v1/mailboxes', **kw).status_code, 200)
        RoleService.assign(helper, 'support')
        self.assertEqual(self.get('/api/v1/mailboxes', **kw).status_code, 403)


class MailboxApiTests(ApiBase):
    def test_create_get_update_delete(self) -> None:
        created = self.post(
            '/api/v1/mailboxes',
            {'address': 'Alice@IfinMail.test', 'password': GOOD, 'quota_bytes': 2048},
        )
        self.assertEqual(created.status_code, 201, created.content)
        body = created.json()
        self.assertEqual(body['address'], 'alice@ifinmail.test')
        self.assertEqual(body['quota_bytes'], 2048)
        self.assertFalse(body['console_access'])
        self.assertNotIn('password', created.content.decode())
        self.assertEqual(self.get('/api/v1/mailboxes/alice@ifinmail.test').status_code, 200)

        changed = self.patch(
            '/api/v1/mailboxes/alice@ifinmail.test',
            {'quota_bytes': 4096, 'is_active': False, 'password': 'Another-Horse-9'},
        )
        self.assertEqual(changed.status_code, 200, changed.content)
        self.assertEqual(changed.json()['quota_bytes'], 4096)
        self.assertFalse(changed.json()['is_active'])
        user = MailUser.objects.get(email='alice@ifinmail.test')
        self.assertTrue(user.check_password('Another-Horse-9'))

        gone = self.delete('/api/v1/mailboxes/alice@ifinmail.test')
        self.assertEqual(gone.status_code, 204)
        self.assertEqual(self.get('/api/v1/mailboxes/alice@ifinmail.test').status_code, 404)
        self.assertFalse(MailUser.objects.filter(email='alice@ifinmail.test').exists())

    def test_errors_map_to_useful_statuses(self) -> None:
        self.post('/api/v1/mailboxes', {'address': 'bob@ifinmail.test', 'password': GOOD})
        self.assertEqual(
            self.post(
                '/api/v1/mailboxes', {'address': 'bob@ifinmail.test', 'password': GOOD}
            ).status_code,
            409,
        )
        weak = self.post('/api/v1/mailboxes', {'address': 'c@ifinmail.test', 'password': 'short'})
        self.assertEqual(weak.status_code, 422)
        self.assertIn('detail', weak.json())
        elsewhere = self.post('/api/v1/mailboxes', {'address': 'c@nowhere.test', 'password': GOOD})
        self.assertEqual(elsewhere.status_code, 422)
        self.assertEqual(
            self.patch('/api/v1/mailboxes/ghost@ifinmail.test', {'quota_bytes': 1}).status_code, 404
        )
        self.assertEqual(self.post('/api/v1/mailboxes', {'password': GOOD}).status_code, 422)

    def test_a_key_cannot_create_or_touch_a_login_with_console_access(self) -> None:
        # is_admin is not part of the contract; extra fields are ignored, never honoured.
        made = self.post(
            '/api/v1/mailboxes',
            {
                'address': 'sneaky@ifinmail.test',
                'password': GOOD,
                'is_admin': True,
                'is_staff': True,
                'is_superuser': True,
            },
        )
        self.assertEqual(made.status_code, 201)
        self.assertFalse(MailUser.objects.get(email='sneaky@ifinmail.test').is_staff)

        MailboxService.create('ifinmail.test', 'boss', GOOD, is_admin=True)
        for response in (
            self.patch('/api/v1/mailboxes/boss@ifinmail.test', {'password': 'Takeover-Horse-9'}),
            self.patch('/api/v1/mailboxes/boss@ifinmail.test', {'is_active': False}),
            self.delete('/api/v1/mailboxes/boss@ifinmail.test'),
        ):
            self.assertEqual(response.status_code, 403, response.content)
        boss = MailUser.objects.get(email='boss@ifinmail.test')
        self.assertTrue(boss.check_password(GOOD))
        self.assertTrue(boss.is_active)
        # The owner's own login is protected the same way.
        self.assertEqual(self.delete('/api/v1/mailboxes/root@ifinmail.test').status_code, 404)

    def test_listing_is_paginated_and_filterable(self) -> None:
        Domain.objects.create(name='other.test')
        for i in range(5):
            MailboxService.create('ifinmail.test', f'user{i}', GOOD)
        MailboxService.create('other.test', 'solo', GOOD)
        page = self.get('/api/v1/mailboxes?limit=2&offset=1').json()
        self.assertEqual(page['count'], 6)
        self.assertEqual(len(page['items']), 2)
        only = self.get('/api/v1/mailboxes?domain=OTHER.test').json()
        self.assertEqual([m['address'] for m in only['items']], ['solo@other.test'])
        too_big = self.get('/api/v1/mailboxes?limit=100000')
        self.assertIn(too_big.status_code, (200, 422))
        if too_big.status_code == 200:
            self.assertLessEqual(len(too_big.json()['items']), 200)

    def test_every_change_is_audited_with_the_key_and_its_owner(self) -> None:
        self.post('/api/v1/mailboxes', {'address': 'dave@ifinmail.test', 'password': GOOD})
        from backend.apps.core.platform.models import AuditEvent

        event = AuditEvent.objects.get(action='api_mailbox_created')
        self.assertIn(self.key, event.user)
        self.assertIn('root@ifinmail.test', event.user)
        self.assertEqual(event.detail, 'dave@ifinmail.test')
        self.assertTrue(AuditService.has('api_mailbox_created'))


class AliasApiTests(ApiBase):
    def test_create_list_delete(self) -> None:
        MailboxService.create('ifinmail.test', 'sales', GOOD)
        created = self.post(
            '/api/v1/aliases',
            {'source': 'info@ifinmail.test', 'destination': 'sales@ifinmail.test'},
        )
        self.assertEqual(created.status_code, 201, created.content)
        alias_id = created.json()['id']
        listed = self.get('/api/v1/aliases').json()
        self.assertEqual(listed['count'], 1)
        self.assertEqual(listed['items'][0]['destination'], 'sales@ifinmail.test')
        self.assertEqual(self.delete(f'/api/v1/aliases/{alias_id}').status_code, 204)
        self.assertEqual(self.delete(f'/api/v1/aliases/{alias_id}').status_code, 404)

    def test_loops_and_mailbox_collisions_are_refused(self) -> None:
        MailboxService.create('ifinmail.test', 'sales', GOOD)
        clash = self.post(
            '/api/v1/aliases', {'source': 'sales@ifinmail.test', 'destination': 'x@ifinmail.test'}
        )
        self.assertIn(clash.status_code, (409, 422))
        self.post(
            '/api/v1/aliases', {'source': 'a@ifinmail.test', 'destination': 'b@ifinmail.test'}
        )
        loop = self.post(
            '/api/v1/aliases', {'source': 'b@ifinmail.test', 'destination': 'a@ifinmail.test'}
        )
        self.assertIn(loop.status_code, (409, 422))


class DomainApiTests(ApiBase):
    def test_list_detail_and_the_legacy_shape(self) -> None:
        listed = self.get('/api/v1/domains').json()
        self.assertEqual(
            set(listed[0]),
            {'name', 'verified', 'mx_verified', 'spf_verified', 'dkim_verified', 'dmarc_verified'},
        )
        detail = self.get('/api/v1/domains/ifinmail.test').json()
        self.assertEqual(detail['name'], 'ifinmail.test')
        self.assertIn('dkim_selectors', detail)
        self.assertEqual(self.get('/api/v1/domains/ghost.test').status_code, 404)

    def test_add_is_idempotent_and_validated(self) -> None:
        with patch(LOOKUP, return_value=[]), patch(SERVER_IP, return_value='203.0.113.5'):
            first = self.post('/api/v1/domains', {'name': 'New-Domain.example'})
            again = self.post('/api/v1/domains', {'name': 'new-domain.example'})
            bad = self.post('/api/v1/domains', {'name': 'not a domain'})
        self.assertEqual(first.status_code, 201, first.content)
        self.assertTrue(first.json()['created'])
        self.assertEqual(first.json()['domain'], 'new-domain.example')
        self.assertTrue(any(s['name'] == 'DKIM key' for s in first.json()['steps']))
        self.assertEqual(again.status_code, 200)
        self.assertFalse(again.json()['created'])
        self.assertEqual(bad.status_code, 422)

    def test_verify_and_unknown_domain(self) -> None:
        with patch(LOOKUP, return_value=[]):
            ok = self.post('/api/v1/domains/ifinmail.test/verify', {})
            missing = self.post('/api/v1/domains/ghost.test/verify', {})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(set(ok.json()['checks']), {'mx', 'spf', 'dkim', 'dmarc'})
        self.assertEqual(missing.status_code, 404)

    def test_removing_a_domain_is_not_offered(self) -> None:
        self.assertEqual(self.delete('/api/v1/domains/ifinmail.test').status_code, 405)


class ConsolePageTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        RoleService.ensure_seed()
        Domain.objects.create(name='ifinmail.test')
        self.admin = MailUser.objects.create_user(
            'root@ifinmail.test', GOOD, is_staff=True, is_superuser=True
        )
        self.client.force_login(self.admin, backend=MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def create(self, **over):
        data = {
            'name': 'Billing',
            'scopes': ['mail.manage'],
            'expires_in_days': '30',
            'networks': '203.0.113.0/24\n198.51.100.7',
            'rate_limit_per_minute': '90',
            'confirm_password': GOOD,
        }
        data.update(over)
        return self.client.post(reverse('accounts:api_key_create'), data)

    def test_the_secret_is_shown_once_and_the_key_works(self) -> None:
        self.assertRedirects(
            self.create(), reverse('accounts:api_keys'), fetch_redirect_response=False
        )
        page = self.client.get(reverse('accounts:api_keys')).content.decode()
        self.assertIn('id="api-key-secret"', page)
        row = APIToken.objects.get(name='Billing')
        self.assertEqual(row.allowed_networks, ['203.0.113.0/24', '198.51.100.7/32'])
        self.assertEqual(row.rate_limit_per_minute, 90)
        self.assertIn(f'ifm_{row.prefix}', page)
        again = self.client.get(reverse('accounts:api_keys')).content.decode()
        self.assertNotIn('id="api-key-secret"', again)
        self.assertIn('Billing', again)

    def test_a_wrong_password_creates_nothing(self) -> None:
        response = self.create(confirm_password='nope', name='Nope')
        self.assertEqual(response.status_code, 302)
        self.assertFalse(APIToken.objects.filter(name='Nope').exists())

    def test_bad_networks_are_reported(self) -> None:
        response = self.client.post(
            reverse('accounts:api_key_create'),
            {
                'name': 'X',
                'scopes': ['mail.manage'],
                'expires_in_days': '30',
                'networks': 'not-an-address',
                'confirm_password': GOOD,
            },
            follow=True,
        )
        self.assertContains(response, 'is not an IP address or CIDR range')

    def test_rotate_with_overlap_and_revoke_are_audited(self) -> None:
        self.create()
        row = APIToken.objects.get(name='Billing')
        action = reverse('accounts:api_key_action')
        self.client.post(
            action,
            {
                'token_id': str(row.id),
                'action': 'rotate',
                'grace_hours': '6',
                'confirm_password': GOOD,
            },
        )
        row.refresh_from_db()
        self.assertIsNotNone(row.previous_expires_at)
        self.client.post(action, {'token_id': str(row.id), 'action': 'revoke'})
        self.assertFalse(APIToken.objects.filter(pk=row.pk).exists())
        for name in ('api_key_created', 'api_key_rotated', 'api_key_revoked'):
            self.assertTrue(AuditService.has(name), name)

    def test_only_people_who_manage_users_may_open_it(self) -> None:
        helper = MailUser.objects.create_user('help@ifinmail.test', GOOD, is_staff=True)
        RoleService.assign(helper, 'support')
        self.client.force_login(helper, backend=MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()
        self.assertIn(self.client.get(reverse('accounts:api_keys')).status_code, (302, 403))
        self.assertIn(self.create(name='Hijack').status_code, (302, 403))
        self.assertFalse(APIToken.objects.filter(name='Hijack').exists())

    def test_the_page_is_in_the_settings_hub(self) -> None:
        hub = self.client.get(reverse('accounts:settings')).content.decode()
        self.assertIn(reverse('accounts:api_keys'), hub)


class HealthApiTests(ApiBase):
    def test_liveness_is_anonymous_and_matches_the_probe(self) -> None:
        versioned = self.client.get('/api/v1/health')
        probe = self.client.get('/health/')
        self.assertEqual(versioned.status_code, 200)
        self.assertEqual(versioned.json(), {'status': 'ok', 'database': 'ok'})
        self.assertEqual(probe.json(), versioned.json())
        self.assertEqual(versioned['X-API-Version'], '1')

    def test_the_detailed_reports_need_a_key_with_audit_view(self) -> None:
        for path in ('/api/v1/health/full', '/api/v1/health/dns', '/api/v1/health/deliverability'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)
        narrow_row, narrow = TokenService.create(
            self.owner, 'narrow', ['console.access'], expires_in_days=30
        )
        kw = {'key': key_id(narrow_row.prefix), 'secret': narrow.split('.', 2)[2]}
        self.assertEqual(self.get('/api/v1/health/full', **kw).status_code, 403)

    def test_full_report_is_typed(self) -> None:
        body = self.get('/api/v1/health/full').json()
        self.assertEqual(set(body), {'status', 'timestamp', 'checks', 'telemetry'})
        self.assertIn('database', body['checks'])
        self.assertEqual(set(body['telemetry']), {'open_critical_24h', 'total_24h', 'top'})

    def test_dns_and_deliverability_reports_are_typed(self) -> None:
        passing = {k: {'status': 'pass', 'detail': 'ok'} for k in ('mx', 'spf', 'dkim', 'dmarc')}
        with patch(
            'backend.apps.core.platform.services.monitoring.MonitoringService.check_dns',
            return_value=passing,
        ):
            dns = self.get('/api/v1/health/dns').json()
            status = self.get('/api/v1/dns/status?domain=ifinmail.test').json()
        self.assertEqual(dns['status'], 'ok')
        self.assertEqual(set(dns['domains']['ifinmail.test']), {'mx', 'spf', 'dkim', 'dmarc'})
        self.assertEqual(status['domain'], 'ifinmail.test')
        self.assertEqual(status['records']['mx'], {'status': 'pass', 'detail': 'ok'})
        result = {
            'timestamp': '2026-10-13T00:00:00+00:00',
            'domain': 'ifinmail.test',
            'server_ip': '203.0.113.5',
            'mail_hostname': 'mail.ifinmail.test',
            'status': 'warn',
            'dns_propagation': {
                'status': 'pass',
                'detail': 'ok',
                'fix': None,
                'records': {
                    'a': {'type': 'A', 'name': 'x', 'status': 'pass', 'detail': 'Resolves'}
                },
            },
            'blacklists': {
                'status': 'warn',
                'detail': 'could not check',
                'fix': 'later',
                'listings': {'zen.example': {'listed': None, 'detail': 'refused'}},
            },
            'reverse_dns': {'status': 'fail', 'detail': 'No PTR', 'fix': 'ask your provider'},
            'port25': {'status': 'pass', 'detail': 'open'},
            'tls': {'status': 'pass', 'detail': 'valid'},
        }
        with patch(
            'backend.apps.core.platform.services.deliverability.DeliverabilityService.run_all_checks',
            return_value=result,
        ):
            body = self.get('/api/v1/health/deliverability?domain=ifinmail.test').json()
        self.assertEqual(body['blacklists']['listings']['zen.example']['listed'], None)
        self.assertEqual(body['reverse_dns']['fix'], 'ask your provider')
        self.assertEqual(body['port25']['fix'], None)

    def test_old_unversioned_health_paths_redirect_to_the_versioned_ones(self) -> None:
        for old, new in (
            ('/health/full/', '/api/v1/health/full'),
            ('/health/dns/', '/api/v1/health/dns'),
            (
                '/health/deliverability/?domain=a.test',
                '/api/v1/health/deliverability?domain=a.test',
            ),
        ):
            with self.subTest(old=old):
                response = self.client.get(old)
                self.assertEqual(response.status_code, 308)
                self.assertEqual(response['Location'], new)
                self.assertEqual(response['Deprecation'], 'true')


class TelemetryApiTests(ApiBase):
    def test_reads_need_audit_view_and_are_typed(self) -> None:
        from backend.apps.core.telemetry.services.telemetry_service import TelemetryService

        TelemetryService.capture(ValueError('boom for the api test'))
        errors = self.get('/api/v1/telemetry/errors?q=boom').json()
        self.assertEqual(set(errors), {'results', 'page', 'num_pages', 'total'})
        self.assertGreaterEqual(errors['total'], 1)
        self.assertEqual(
            set(errors['results'][0]),
            {
                'id',
                'time',
                'severity',
                'action',
                'detail',
                'service',
                'user',
                'correlation_id',
                'fingerprint',
                'source',
            },
        )
        self.assertEqual(
            set(self.get('/api/v1/telemetry/stats').json()),
            {'open_critical_24h', 'total_24h', 'top'},
        )
        self.assertIn('results', self.get('/api/v1/telemetry/fingerprints').json())
        row, token = TokenService.create(self.owner, 'n', ['console.access'], expires_in_days=30)
        kw = {'key': key_id(row.prefix), 'secret': token.split('.', 2)[2]}
        self.assertEqual(self.get('/api/v1/telemetry/errors', **kw).status_code, 403)

    def test_acknowledging_needs_a_write_scope_and_is_audited(self) -> None:
        from backend.apps.core.telemetry.models import ErrorFingerprint
        from backend.apps.core.telemetry.services.telemetry_service import TelemetryService

        TelemetryService.capture(ValueError('ack me'))
        fingerprint = ErrorFingerprint.objects.order_by('-count').first()
        assert fingerprint is not None
        url = f'/api/v1/telemetry/fingerprints/{fingerprint.hash}/ack'
        readonly_row, readonly = TokenService.create(
            self.owner, 'ro', ['audit.view'], expires_in_days=30
        )
        kw = {'key': key_id(readonly_row.prefix), 'secret': readonly.split('.', 2)[2]}
        self.assertEqual(self.post(url, {'status': 'ACKED'}, **kw).status_code, 403)
        writer_row, writer = TokenService.create(
            self.owner, 'rw', ['system.manage'], expires_in_days=30
        )
        w = {'key': key_id(writer_row.prefix), 'secret': writer.split('.', 2)[2]}
        self.assertEqual(self.post(url, {'status': 'nonsense'}, **w).status_code, 422)
        missing = self.post('/api/v1/telemetry/fingerprints/nope/ack', {'status': 'ACKED'}, **w)
        self.assertEqual(missing.status_code, 404)
        done = self.post(url, {'status': 'acked'}, **w)
        self.assertEqual(done.status_code, 200, done.content)
        self.assertEqual(done.json(), {'success': True})
        self.assertTrue(AuditService.has('api_error_acknowledged'))

    def test_old_unversioned_telemetry_paths_redirect(self) -> None:
        for name in ('errors', 'stats', 'fingerprints'):
            with self.subTest(name=name):
                response = self.client.get(f'/telemetry/{name}/')
                self.assertEqual(response.status_code, 308)
                self.assertEqual(response['Location'], f'/api/v1/telemetry/{name}')


class ContractTests(ApiBase):
    """The contract is complete, typed, and says what the server enforces."""

    def operations(self):
        from backend.apps.accounts.api import api
        from backend.apps.accounts.viewsets.contract import operations

        return api, operations(api)

    def test_every_operation_is_described_and_scoped(self) -> None:
        _, ops = self.operations()
        self.assertGreaterEqual(len(ops), 22)
        for op in ops:
            with self.subTest(op=f'{op.method} {op.path}'):
                self.assertTrue(op.summary, 'every operation needs a summary')
                if op.anonymous:
                    self.assertEqual((op.method, op.path), ('GET', '/health'))
                    continue
                self.assertIsNotNone(op.scope, 'every keyed operation declares its scope')
                for status in (401, 403, 429):
                    self.assertIn(status, op.statuses)
                self.assertTrue(any(s < 300 for s in op.statuses))

    def test_the_document_states_the_scope_the_server_enforces(self) -> None:
        spec = self.client.get('/api/v1/openapi.json').json()
        _, ops = self.operations()
        for op in ops:
            if op.scope is None:
                continue
            with self.subTest(op=f'{op.method} {op.path}'):
                document = spec['paths'][f'/api/v1{op.path}'][op.method.lower()]
                self.assertEqual(document['x-required-scope'], op.scope)

    def test_a_key_without_the_documented_scope_is_refused_everywhere(self) -> None:
        row, token = TokenService.create(
            self.owner, 'status-only', ['console.access'], expires_in_days=30
        )
        kw = {'key': key_id(row.prefix), 'secret': token.split('.', 2)[2]}
        _, ops = self.operations()
        # Valid bodies, so the answer is about the scope and not about the payload.
        bodies = {
            ('POST', '/mailboxes'): {'address': 'a@ifinmail.test'},
            ('POST', '/aliases'): {'source': 'a@ifinmail.test', 'destination': 'b@ifinmail.test'},
            ('POST', '/domains'): {'name': 'example.com'},
            ('POST', '/inboxes'): {},
            ('POST', '/webhooks'): {'name': 'w', 'url': 'https://h.example.com/', 'events': ['message.bounced']},
            ('PATCH', '/mailboxes/{address}'): {'quota_bytes': 1},
            ('POST', '/telemetry/fingerprints/{fingerprint}/ack'): {'status': 'ACKED'},
            ('POST', '/messages'): {
                'from': 'a@ifinmail.test',
                'to': ['b@example.org'],
                'subject': 's',
                'text': 't',
            },
        }
        refused = 0
        for op in ops:
            if op.anonymous or op.scope == 'console.access':
                continue
            url = '/api/v1' + (
                op.path.replace('{address}', 'a@ifinmail.test')
                .replace('{name}', 'ifinmail.test')
                .replace('{alias_id}', 'x')
                .replace('{fingerprint}', 'abc')
                .replace('{uid}', '1')
                .replace('{approval_id}', '00000000-0000-0000-0000-000000000000')
            )
            body = bodies.get((op.method, op.path), {} if op.method in ('POST', 'PATCH') else None)
            response = self.call(op.method.lower(), url, body=body, **kw)
            with self.subTest(op=f'{op.method} {op.path}'):
                self.assertEqual(response.status_code, 403, response.content)
            refused += 1
        self.assertGreaterEqual(refused, 18)

    def test_handlers_are_fully_annotated(self) -> None:
        import inspect

        from backend.apps.accounts.api import api
        from backend.apps.accounts.viewsets.auth import ApiRequest

        checked = 0
        for _prefix, router in api._routers:
            for path, view in router.path_operations.items():
                for operation in view.operations:
                    function = operation.view_func
                    signature = inspect.signature(function, follow_wrapped=True)
                    with self.subTest(handler=f'{path} {function.__name__}'):
                        self.assertIsNot(
                            signature.return_annotation, inspect.Signature.empty, 'return type'
                        )
                        for name, parameter in signature.parameters.items():
                            self.assertIsNot(
                                parameter.annotation, inspect.Parameter.empty, f'parameter {name}'
                            )
                        first = next(iter(signature.parameters.values()))
                        self.assertIs(first.annotation, ApiRequest)
                    checked += 1
        self.assertGreaterEqual(checked, 22)

    def test_no_schema_is_untyped(self) -> None:
        spec = self.client.get('/api/v1/openapi.json').json()

        def typed(schema: dict) -> bool:
            keys = ('type', '$ref', 'anyOf', 'oneOf', 'allOf', 'enum', 'const')
            return any(k in schema for k in keys)

        for name, schema in spec['components']['schemas'].items():
            for field, definition in (schema.get('properties') or {}).items():
                with self.subTest(schema=name, field=field):
                    self.assertTrue(typed(definition), definition)
        for url, item in spec['paths'].items():
            for method, document in item.items():
                for status, response in document['responses'].items():
                    content = (response.get('content') or {}).get('application/json')
                    if content is not None:
                        with self.subTest(op=f'{method} {url} {status}'):
                            self.assertTrue(typed(content['schema']), content)
        ids = [d['operationId'] for item in spec['paths'].values() for d in item.values()]
        self.assertEqual(len(ids), len(set(ids)), 'operation ids are unique')

    def test_errors_share_one_documented_shape(self) -> None:
        spec = self.client.get('/api/v1/openapi.json').json()
        self.assertEqual(
            spec['components']['schemas']['ErrorV1']['required'],
            ['detail'],
        )
        document = spec['paths']['/api/v1/mailboxes']['post']['responses']
        for status in ('401', '403', '409', '422', '429'):
            self.assertEqual(
                document[status]['content']['application/json']['schema']['$ref'],
                '#/components/schemas/ErrorV1',
            )


class VersionedSurfaceTests(ApiBase):
    """Every JSON endpoint is a v1 operation, or is listed with the reason it is not."""

    def json_routes(self) -> list[tuple[str, str]]:
        import inspect

        from django.urls import get_resolver
        from django.urls.resolvers import URLResolver

        def walk(patterns, prefix=''):
            for pattern in patterns:
                route = prefix + str(pattern.pattern)
                if isinstance(pattern, URLResolver):
                    yield from walk(pattern.url_patterns, route)
                else:
                    yield route, pattern.callback

        found = []
        for route, callback in walk(get_resolver().url_patterns):
            function = callback
            while hasattr(function, '__wrapped__'):
                function = function.__wrapped__
            try:
                source = inspect.getsource(function)
            except (OSError, TypeError):
                continue
            if 'JsonResponse' in source:
                found.append((route, f'{function.__module__}.{function.__name__}'))
        return found

    def test_every_json_endpoint_is_versioned_or_explained(self) -> None:
        from backend.config.api_versions import (
            CONSOLE,
            CONSOLE_PREFIXES,
            INFRASTRUCTURE,
        )

        routes = self.json_routes()
        self.assertGreaterEqual(len(routes), 10, 'the scan itself must find the endpoints')
        stray = []
        for route, view in routes:
            if route == 'api/':
                continue  # the version index
            if route in INFRASTRUCTURE or route in CONSOLE:
                continue
            if route.startswith(CONSOLE_PREFIXES):
                continue
            stray.append(f'{route} ({view})')
        self.assertEqual(
            stray, [], 'a JSON endpoint outside /api/vN must be listed in api_versions.py'
        )

    def test_the_registry_matches_the_mounted_versions(self) -> None:
        from backend.config.api_versions import CURRENT, LEGACY_MACHINE_PATHS, VERSIONS

        labels = [v.version for v in VERSIONS]
        self.assertIn(CURRENT, labels)
        index = self.client.get('/api/').json()
        self.assertEqual([v['version'] for v in index['versions']], labels)
        for v in VERSIONS:
            with self.subTest(version=v.version):
                self.assertTrue(v.api.version.startswith(v.version.removeprefix('v') + '.'))
                spec = self.client.get(f'/api/{v.version}/openapi.json')
                self.assertEqual(spec.status_code, 200)
                self.assertEqual(spec.json()['info']['version'], v.api.version)
        spec = self.client.get(f'/api/{CURRENT}/openapi.json').json()
        for target in LEGACY_MACHINE_PATHS.values():
            self.assertIn(f'/api/{CURRENT}/{target}', spec['paths'])

    def test_unknown_route_is_not_swallowed_by_the_legacy_redirect(self) -> None:
        self.assertEqual(self.client.get('/api/v9/status').status_code, 404)
