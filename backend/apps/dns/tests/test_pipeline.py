"""DNS record matching, credential storage and the console's DNS endpoints."""

from __future__ import annotations

import json
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse

from backend.apps.accounts.models import MailUser
from backend.apps.core.platform.services.runtime import read_runtime_file
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.dns.models import DNSProviderConfig
from backend.apps.dns.providers.base import DNSRecord, record_key
from backend.apps.dns.providers.cloudflare import CloudflareProvider
from backend.apps.dns.providers.digitalocean import DigitalOceanProvider
from backend.apps.dns.services import DNSService, decrypt_credentials, encrypt_credentials
from backend.apps.mail.services.postfix_runtime import PostfixRuntime

MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'
_LOOKUP = 'backend.apps.domains.services.verification._lookup'


class RecordKeyTests(SimpleTestCase):
    def test_txt_records_are_matched_by_their_purpose_not_just_their_name(self) -> None:
        spf = record_key('TXT', '@', '"v=spf1 mx -all"')
        google = record_key('TXT', '@', 'google-site-verification=abc')
        other_spf = record_key('TXT', '@', 'v=spf1 include:_spf.google.com ~all')
        self.assertEqual(spf, other_spf)  # same purpose: update in place
        self.assertNotEqual(spf, google)  # a different TXT is never overwritten
        self.assertNotEqual(record_key('TXT', '_dmarc', 'v=DMARC1; p=none'), spf)

    def test_other_types_match_by_type_and_name(self) -> None:
        self.assertEqual(record_key('A', 'mail', '1.1.1.1'), record_key('A', 'mail', '2.2.2.2'))
        self.assertNotEqual(record_key('A', 'mail', ''), record_key('A', 'www', ''))


class CloudflareDoesNotClobberOtherTxtRecords(SimpleTestCase):
    def test_spf_is_added_next_to_a_google_verification_record(self) -> None:
        calls: list[tuple[str, str]] = []
        provider = CloudflareProvider('token')

        def fake(method: str, path: str, **kwargs):
            calls.append((method, path))
            if path == '/zones':
                return {'result': [{'id': 'z1'}]}
            if method == 'GET':
                return {
                    'result': [
                        {
                            'id': 'g1',
                            'type': 'TXT',
                            'name': 'example.com',
                            'content': 'google-site-verification=abc',
                        },
                    ],
                    'result_info': {'total_count': 1},
                }
            return {'result': {}}

        with patch.object(provider, '_request', side_effect=fake):
            result = provider.configure_domain(
                'example.com', [DNSRecord('TXT', '@', 'v=spf1 mx -all')]
            )
        self.assertTrue(result.success)
        self.assertIn(('POST', '/zones/z1/dns_records'), calls)
        self.assertFalse([c for c in calls if c[0] == 'PUT'])  # nothing overwritten


class DigitalOceanHostnameTests(SimpleTestCase):
    def test_mx_and_cname_targets_are_fully_qualified(self) -> None:
        provider = DigitalOceanProvider('token')
        mx = provider._record_payload(
            DNSRecord('MX', '@', 'mail.example.com', priority=10), 'example.com'
        )
        cname = provider._record_payload(
            DNSRecord('CNAME', 'autoconfig', 'mail.example.com'), 'example.com'
        )
        txt = provider._record_payload(DNSRecord('TXT', '@', 'v=spf1 mx -all'), 'example.com')
        self.assertEqual(
            mx['data'], 'mail.example.com.'
        )  # undotted would become mail.example.com.example.com
        self.assertEqual(cname['data'], 'mail.example.com.')
        self.assertEqual(txt['data'], 'v=spf1 mx -all')


class CredentialStorageTests(MailTablesTestCase):
    def test_provider_tokens_are_encrypted_at_rest(self) -> None:
        DNSService.update_or_create_config('cloudflare', {'api_token': 'super-secret-token'})
        stored = DNSProviderConfig.objects.get(provider='cloudflare').credentials
        self.assertTrue(stored.startswith('fernet:'))
        self.assertNotIn('super-secret-token', stored)
        provider = DNSService.get_provider('cloudflare')
        self.assertEqual(provider.api_token, 'super-secret-token')

    def test_tampered_or_foreign_ciphertext_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            decrypt_credentials('fernet:not-valid')

    def test_older_signed_credentials_are_still_readable(self) -> None:
        from django.core import signing

        DNSProviderConfig.objects.create(
            provider='porkbun', credentials=signing.dumps({'api_key': 'k', 'secret_key': 's'})
        )
        self.assertEqual(DNSService.get_provider('porkbun').api_key, 'k')

    def test_roundtrip(self) -> None:
        self.assertEqual(decrypt_credentials(encrypt_credentials({'a': 1})), {'a': 1})


class DnsEndpointTests(MailTablesTestCase):
    env = {'MAIL_SMART_HOST': 'relay.example.net'}

    def setUp(self) -> None:
        super().setUp()
        admin = MailUser.objects.create_user('root@ifinmail.test', 'Correct-Horse-9', is_staff=True)
        self.client.force_login(admin, backend=MODEL_BACKEND)
        from django.utils import timezone

        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def test_registering_a_domain_runs_the_whole_pipeline_and_reports_each_step(self) -> None:
        with (
            patch(_LOOKUP, return_value=[]),
            patch('backend.apps.dns.services.DNSService.get_server_ip', return_value='203.0.113.5'),
        ):
            response = self.client.post(reverse('dns:register'), {'domain': 'newdomain.test'})
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['status'], 'ok')
        steps = {s['name']: s['status'] for s in data['steps']}
        self.assertEqual(steps['DKIM key'], 'ok')
        self.assertEqual(steps['DNS records'], 'manual')
        dkim = next(r for r in data['records'] if '_domainkey' in r['name'])
        self.assertNotIn('<add-dkim-key>', dkim['value'])

    def test_register_rejects_a_bad_name_without_creating_anything(self) -> None:
        response = self.client.post(reverse('dns:register'), {'domain': 'not a domain'})
        self.assertEqual(response.status_code, 400)

    def test_smart_host_toggle_changes_what_postfix_is_told_and_persists(self) -> None:
        response = self.client.post(reverse('dns:toggle_relay'))
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'ok')
        self.assertFalse(data['enabled'])  # env enabled it; the toggle flipped it off
        self.assertIn('relayhost = \n', read_runtime_file('postfix-overrides.conf'))
        self.assertFalse(PostfixRuntime.state().smart_host_enabled)
        data = json.loads(self.client.post(reverse('dns:toggle_relay')).content)
        self.assertTrue(data['enabled'])
        self.assertIn(
            'relayhost = [relay.example.net]:587', read_runtime_file('postfix-overrides.conf')
        )

    def test_proxy_toggle_without_a_configured_host_is_an_error_not_a_fake_success(self) -> None:
        response = self.client.post(reverse('dns:toggle_proxy'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('MAIL_SMTP_PROXY', json.loads(response.content)['error'])

    def test_hop_count_is_validated_and_published(self) -> None:
        self.assertEqual(
            self.client.post(reverse('dns:set_hop_count'), {'value': '99'}).status_code, 400
        )
        self.assertEqual(
            self.client.post(reverse('dns:set_hop_count'), {'value': 'x'}).status_code, 400
        )
        response = self.client.post(reverse('dns:set_hop_count'), {'value': '17'})
        self.assertEqual(json.loads(response.content)['value'], 17)
        self.assertIn('hopcount_limit = 17', read_runtime_file('postfix-overrides.conf'))

    def test_dns_status_stores_the_result_on_the_domain(self) -> None:
        from backend.apps.domains.models import Domain

        Domain.objects.create(name='ifinmail.test')

        def fake(name: str, rdtype: str):
            return ['10 mail.ifinmail.test'] if rdtype == 'MX' else []

        with patch(_LOOKUP, side_effect=fake):
            data = json.loads(
                self.client.get(reverse('dns:status'), {'domain': 'ifinmail.test'}).content
            )
        self.assertEqual(data['records']['mx']['status'], 'pass')
        domain = Domain.objects.get(name='ifinmail.test')
        self.assertTrue(domain.mx_verified)
        self.assertTrue(domain.verified)  # Postfix only accepts mail for verified domains
