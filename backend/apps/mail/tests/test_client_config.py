"""Per-domain client autoconfiguration and the MTA-STS policy."""

from __future__ import annotations

from backend.apps.core.tests.mail_base import MailTablesTestCase


class ClientConfigTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.make_domain('ifinmail.test')
        self.make_domain('other.test')

    def get(self, path: str, host: str | None = None, **query: str):
        headers = {'HTTP_X_ORIGINAL_HOST': host} if host else {}
        return self.client.get(path, data=query or None, **headers)

    def test_mta_sts_policy_is_served_for_each_hosted_domain(self) -> None:
        for domain in ('ifinmail.test', 'other.test'):
            response = self.get('/.well-known/mta-sts.txt', host=f'mta-sts.{domain}')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'text/plain; charset=utf-8')
            body = response.content.decode()
            self.assertEqual(
                body,
                'version: STSv1\r\nmode: testing\r\nmx: mail.ifinmail.test\r\nmax_age: 86400\r\n',
            )

    def test_mta_sts_is_not_served_for_other_hosts_or_unknown_domains(self) -> None:
        self.assertEqual(
            self.get('/.well-known/mta-sts.txt', host='mail.ifinmail.test').status_code, 404
        )
        self.assertEqual(
            self.get('/.well-known/mta-sts.txt', host='mta-sts.nope.test').status_code, 404
        )
        self.assertEqual(self.get('/.well-known/mta-sts.txt').status_code, 404)

    def test_enforce_mode_lengthens_max_age(self) -> None:
        from backend.apps.core.services import SystemSettings
        from backend.apps.core.types import SettingKey

        SystemSettings.set(SettingKey.MTA_STS_MODE, 'enforce')
        body = self.get('/.well-known/mta-sts.txt', host='mta-sts.other.test').content.decode()
        self.assertIn('mode: enforce', body)
        self.assertIn('max_age: 604800', body)

    def test_thunderbird_config_names_the_requested_domain(self) -> None:
        response = self.get('/mail/config-v1.1.xml', host='autoconfig.other.test')
        body = response.content.decode()
        self.assertIn('<domain>other.test</domain>', body)
        self.assertIn('<hostname>mail.ifinmail.test</hostname>', body)
        self.assertIn('<port>993</port>', body)
        by_email = self.get('/mail/config-v1.1.xml', emailaddress='me@other.test')
        self.assertIn('<domain>other.test</domain>', by_email.content.decode())

    def test_unknown_domains_get_a_404_not_the_primary_domains_settings(self) -> None:
        self.assertEqual(
            self.get('/mail/config-v1.1.xml', host='autoconfig.nope.test').status_code, 404
        )
        self.assertEqual(
            self.get('/mail/config-v1.1.xml', emailaddress='me@nope.test').status_code, 404
        )

    def test_autodiscover_uses_the_posted_address_as_the_login(self) -> None:
        xml = (
            '<Autodiscover xmlns="http://schemas.microsoft.com/exchange/autodiscover/outlook/requestschema/2006">'
            '<Request><EMailAddress>me@other.test</EMailAddress></Request></Autodiscover>'
        )
        response = self.client.post(
            '/autodiscover/autodiscover.xml', data=xml, content_type='text/xml'
        )
        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body.count('<LoginName>me@other.test</LoginName>'), 2)

    def test_autodiscover_rejects_unhosted_domains_and_escapes_input(self) -> None:
        bad = '<Request><EMailAddress>me@nope.test</EMailAddress></Request>'
        self.assertEqual(
            self.client.post(
                '/autodiscover/autodiscover.xml', data=bad, content_type='text/xml'
            ).status_code,
            404,
        )
        evil = '<Request><EMailAddress>a&lt;b@other.test</EMailAddress></Request>'
        response = self.client.post(
            '/autodiscover/autodiscover.xml', data=evil, content_type='text/xml'
        )
        self.assertNotIn('a<b', response.content.decode())
