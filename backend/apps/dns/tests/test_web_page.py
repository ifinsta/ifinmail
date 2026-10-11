"""The console DNS page: rendering guarantees and the status endpoint contract.

Regression coverage for issues found while reviewing ``/dns/`` for production:
the SPF copy value was HTML-escaped for a JS context, the DKIM selector never
rendered, the page ran live DNS lookups on every request, and a blank
``?domain=`` overrode the configured default on the status endpoint.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.core.tests.mail_base import MailTablesTestCase

MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'
SERVER_IP = 'backend.apps.dns.views.web._get_server_ip'
LOOKUP = 'backend.apps.domains.services.verification._lookup'


class DnsPageTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        admin = MailUser.objects.create_user('root@ifinmail.test', 'Correct-Horse-9', is_staff=True)
        self.client.force_login(admin, backend=MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

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


class DnsStatusEndpointTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        admin = MailUser.objects.create_user('root@ifinmail.test', 'Correct-Horse-9', is_staff=True)
        self.client.force_login(admin, backend=MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

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

    def test_export_only_accepts_get(self) -> None:
        response = self.client.post(reverse('dns:export'))
        self.assertEqual(response.status_code, 405)
