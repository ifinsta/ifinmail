"""The console DNS page: rendering guarantees and the status endpoint contract.

Regression coverage for issues found while reviewing ``/dns/`` for production:
the SPF copy value was HTML-escaped for a JS context, the DKIM selector never
rendered, the page ran live DNS lookups on every request, a blank ``?domain=``
overrode the configured default, and the stats were placeholders.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.core.platform.services.tls import CertInfo, TLSService
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.dns.models import DNSZone
from backend.apps.domains.services.verification import DomainVerificationService
from backend.apps.domains.types.provisioning import CheckStatus, DNSCheck, VerificationResult

MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'
SERVER_IP = 'backend.apps.dns.views.web._get_server_ip'
SERVICE_IP = 'backend.apps.dns.services.DNSService.get_server_ip'
LOOKUP = 'backend.apps.domains.services.verification._lookup'


def _login(client) -> None:
    admin = MailUser.objects.create_user('root@ifinmail.test', 'Correct-Horse-9', is_staff=True)
    client.force_login(admin, backend=MODEL_BACKEND)
    session = client.session
    session['mfa_verified_at'] = timezone.now().isoformat()
    session.save()


class DnsPageTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        _login(self.client)

    def render_page(self):
        with patch(SERVER_IP, return_value='203.0.113.5'):
            return self.client.get(reverse('dns:config'))

    def test_page_requires_login(self) -> None:
        self.client.logout()
        response = self.client.get(reverse('dns:config'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response['Location'])

    def test_spf_copy_button_carries_the_plain_value(self) -> None:
        response = self.render_page()
        self.assertContains(response, 'data-value="v=spf1 mx -all"')
        # escapejs output (``v\u003Dspf1 ...``) reaches the clipboard verbatim.
        self.assertNotContains(response, '\\u003D')

    def test_dkim_selector_is_shown(self) -> None:
        response = self.render_page()
        self.assertContains(response, 'selector: default')

    def test_page_render_does_not_perform_live_dns_lookups(self) -> None:
        with patch(LOOKUP, side_effect=AssertionError('page render must not resolve DNS')):
            response = self.render_page()
        self.assertEqual(response.status_code, 200)

    def test_refresh_url_keeps_the_configured_domain(self) -> None:
        response = self.render_page()
        self.assertContains(response, 'data-url="/dns/status/?domain=ifinmail.test"')

    def test_refresh_url_omits_an_empty_domain_instead_of_sending_blank(self) -> None:
        with patch.dict(os.environ, {'DOMAIN': '', 'MAIL_DOMAIN': ''}):
            response = self.render_page()
        self.assertContains(response, 'data-url="/dns/status/"')

    def test_propagation_stat_is_derived_from_stored_verification(self) -> None:
        from backend.apps.domains.models import Domain

        Domain.objects.create(
            name='ifinmail.test',
            mx_verified=True,
            spf_verified=True,
            dmarc_verified=True,
            dkim_verified=False,
        )
        response = self.render_page()
        self.assertContains(response, '75%')
        self.assertContains(response, '3/4 checks verified')

    def test_propagation_stat_is_empty_without_domains(self) -> None:
        response = self.render_page()
        self.assertContains(response, 'No domains')

    def test_dnssec_stat_counts_hosted_zones(self) -> None:
        DNSZone.objects.create(zone='ifinmail.test', mode='authoritative', dnssec=True)
        DNSZone.objects.create(zone='legacy.test', mode='authoritative', dnssec=False)
        response = self.render_page()
        self.assertContains(response, '1/2 signed')
        self.assertContains(response, 'Issues')

    def test_dnssec_stat_is_empty_without_hosted_zones(self) -> None:
        response = self.render_page()
        self.assertContains(response, 'No hosted zones')

    def test_ssl_column_reports_missing_certificate_instead_of_placeholder(self) -> None:
        from backend.apps.domains.models import Domain

        Domain.objects.create(name='ifinmail.test')
        response = self.render_page()
        self.assertContains(response, 'No certificate')
        self.assertNotContains(response, 'See TLS health')

    def test_registry_rows_offer_verify_and_zone_actions(self) -> None:
        from backend.apps.domains.models import Domain

        Domain.objects.create(name='ifinmail.test')
        DNSZone.objects.create(zone='ifinmail.test', mode='authoritative')
        response = self.render_page()
        self.assertContains(response, f'data-url="{reverse("dns:verify_domain")}"')
        self.assertContains(response, f'href="{reverse("dns:zone", args=["ifinmail.test"])}"')


class DnsStatusEndpointTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        _login(self.client)

    def test_blank_domain_falls_back_to_the_configured_domain(self) -> None:
        with patch(LOOKUP, return_value=[]):
            response = self.client.get(reverse('dns:status'), {'domain': ''})
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['domain'], 'ifinmail.test')

    def test_no_domain_anywhere_is_a_clear_error_not_a_fake_check(self) -> None:
        with patch.dict(os.environ, {'DOMAIN': '', 'MAIL_DOMAIN': ''}):
            response = self.client.get(reverse('dns:status'))
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', data)

    def test_failures_do_not_leak_internal_details(self) -> None:
        with patch(
            'backend.apps.dns.viewsets.status.MonitoringService.check_dns',
            side_effect=RuntimeError('secret internal detail'),
        ):
            response = self.client.get(reverse('dns:status'))
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('secret internal detail', response.content.decode())

    def test_export_only_accepts_get(self) -> None:
        response = self.client.post(reverse('dns:export'))
        self.assertEqual(response.status_code, 405)


class DnsVerifyDomainEndpointTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        _login(self.client)

    def test_verifies_a_registered_domain_and_reports_the_outcome(self) -> None:
        from backend.apps.domains.models import Domain

        Domain.objects.create(name='ifinmail.test')
        result = VerificationResult(
            domain='ifinmail.test',
            mx=DNSCheck(CheckStatus.PASS, 'MX points at mail.ifinmail.test'),
            spf=DNSCheck(CheckStatus.PASS, 'SPF record found'),
            dkim=DNSCheck(CheckStatus.PASS, 'DKIM record matches the server key'),
            dmarc=DNSCheck(CheckStatus.PASS, 'DMARC record found'),
            accepts_mail=True,
        )
        with patch.object(DomainVerificationService, 'verify', return_value=result) as verify:
            response = self.client.post(reverse('dns:verify_domain'), {'domain': 'ifinmail.test'})
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['status'], 'ok')
        self.assertTrue(data['accepts_mail'])
        self.assertEqual(data['records']['mx']['status'], 'pass')
        verify.assert_called_once()

    def test_unknown_domain_is_a_404(self) -> None:
        response = self.client.post(reverse('dns:verify_domain'), {'domain': 'nope.test'})
        self.assertEqual(response.status_code, 404)

    def test_endpoint_requires_post_and_login(self) -> None:
        self.assertEqual(self.client.get(reverse('dns:verify_domain')).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(reverse('dns:verify_domain')).status_code, 302)


class DnsRegisterDefersVerificationTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        _login(self.client)

    def test_registration_does_not_wait_on_live_dns(self) -> None:
        with (
            patch(LOOKUP, side_effect=AssertionError('registration must not run live DNS')),
            patch(SERVICE_IP, return_value='203.0.113.5'),
        ):
            response = self.client.post(reverse('dns:register'), {'domain': 'newdomain.test'})
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['status'], 'ok')
        self.assertIsNone(data['verification'])
        self.assertNotIn('Verification', [step['name'] for step in data['steps']])


class TlsExpiryByDomainTests(SimpleTestCase):
    @staticmethod
    def _cert(days: int, sans: tuple[str, ...]) -> CertInfo:
        now = datetime.now(UTC)
        return CertInfo(
            name='mail.ifinmail.test',
            subject='mail.ifinmail.test',
            issuer='Test CA',
            sans=sans,
            not_before=now - timedelta(days=1),
            not_after=now + timedelta(days=days),
            fingerprint='aa' * 32,
            self_signed=False,
        )

    def test_covered_domain_reports_days_and_status(self) -> None:
        with patch.object(
            TLSService, 'active_certificate', return_value=self._cert(45, ('ifinmail.test',))
        ):
            result = TLSService.expiry_by_domain(['ifinmail.test'])
        info = result['ifinmail.test']
        self.assertTrue(info['covered'])
        self.assertIn(info['days'], (44, 45))
        self.assertEqual(info['status'], 'ok')

    def test_uncovered_domain_is_flagged(self) -> None:
        with patch.object(
            TLSService, 'active_certificate', return_value=self._cert(45, ('other.test',))
        ):
            result = TLSService.expiry_by_domain(['ifinmail.test'])
        self.assertFalse(result['ifinmail.test']['covered'])
        self.assertEqual(result['ifinmail.test']['status'], 'warn')

    def test_missing_certificate_is_unknown(self) -> None:
        with patch.object(TLSService, 'active_certificate', return_value=None):
            result = TLSService.expiry_by_domain(['ifinmail.test'])
        self.assertIsNone(result['ifinmail.test']['covered'])
        self.assertEqual(result['ifinmail.test']['status'], 'unknown')
