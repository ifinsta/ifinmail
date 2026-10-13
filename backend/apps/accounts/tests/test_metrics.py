"""GET /api/metrics: Prometheus text, token-scoped, nothing sensitive."""

from __future__ import annotations

from django.core.cache import cache
from django.test import override_settings

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.roles import RoleService
from backend.apps.accounts.services.tokens import TokenService
from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.domains.models import Domain

GOOD = 'Correct-Horse-9'
LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


@override_settings(CACHES=LOCMEM)
class MetricsTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        RoleService.ensure_seed()
        Domain.objects.create(name='ifinmail.test')
        self.user = MailUser.objects.create_user('api@ifinmail.test', GOOD, is_staff=True)
        _, self.plain = TokenService.create(
            self.user, 'scraper', ['audit.view'], expires_in_days=30
        )

    def _get(self, token: str | None):
        headers = {} if token is None else {'HTTP_AUTHORIZATION': f'Bearer {token}'}
        return self.client.get('/api/v1/metrics', **headers)

    def test_requires_a_token_with_the_audit_scope(self) -> None:
        self.assertEqual(self._get(None).status_code, 401)
        _, narrow = TokenService.create(self.user, 'n', ['console.access'], expires_in_days=30)
        self.assertEqual(self._get(narrow).status_code, 403)

    def test_exposes_health_chain_and_counts_in_prometheus_format(self) -> None:
        AuditService.record(action='test_event', user='x', detail='y')
        response = self._get(self.plain)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('text/plain; version=0.0.4'))
        body = response.content.decode()
        for series in (
            'ifinmail_up 1',
            'ifinmail_audit_chain_ok 1',
            'ifinmail_domains 1',
            'ifinmail_mailboxes ',
            '# TYPE ifinmail_health_check_status gauge',
            'ifinmail_health_check_status{check="',
            'ifinmail_health_checked_timestamp_seconds ',
        ):
            self.assertIn(series, body)
        self.assertRegex(body, r'ifinmail_audit_events [1-9]')
        # Every non-comment line is "name{labels} number".
        for line in body.splitlines():
            if line and not line.startswith('#'):
                self.assertRegex(line, r'^[a-z_]+(\{[^}]*\})? -?\d+(\.\d+)?$')

    def test_reports_a_broken_chain(self) -> None:
        from backend.apps.core.platform.models import AuditEvent

        AuditService.record(action='a', user='x')
        AuditService.record(action='b', user='x')
        AuditEvent.objects.filter(seq=1).update(detail='forged')
        cache.clear()
        self.assertIn('ifinmail_audit_chain_ok 0', self._get(self.plain).content.decode())

    def test_leaks_no_addresses_or_secrets(self) -> None:
        body = self._get(self.plain).content.decode()
        # check names such as 'installer-password' are fine; values and identities are not
        for forbidden in ('@', 'ifm.', GOOD, self.plain, 'api@ifinmail.test'):
            self.assertNotIn(forbidden, body)
