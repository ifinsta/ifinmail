"""Scanner refusals (unknown Host, missing pages) are answers, not errors in the error log."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from django.core.exceptions import DisallowedHost
from django.http import Http404
from django.test import SimpleTestCase, override_settings
from django.urls import Resolver404

from backend.apps.core.telemetry.models import ErrorEvent, ErrorFingerprint
from backend.apps.core.telemetry.services.telemetry_service import TelemetryService
from backend.apps.core.telemetry.threats import digest
from backend.apps.core.tests.mail_base import MailTablesTestCase

SCRIPT = (
    Path(__file__).resolve().parents[5] / 'provisioning' / 'docker' / 'nginx' / 'allowed-hosts.sh'
)


class CaptureTests(MailTablesTestCase):
    def test_refusals_are_not_recorded(self) -> None:
        for exc in (DisallowedHost('Invalid HTTP_HOST header'), Http404('x'), Resolver404({})):
            result = TelemetryService.capture(exc)
            self.assertEqual(result['fingerprint'], '')
        self.assertEqual(ErrorEvent.objects.count(), 0)
        self.assertEqual(ErrorFingerprint.objects.count(), 0)

    def test_real_errors_still_are(self) -> None:
        result = TelemetryService.capture(ValueError('a real defect'))
        self.assertTrue(result['fingerprint'])
        self.assertEqual(ErrorEvent.objects.get().exc_type, 'ValueError')

    @override_settings(ALLOWED_HOSTS=['testserver'])
    def test_a_scanner_request_leaves_no_error_row(self) -> None:
        self.assertEqual(self.client.get('/', HTTP_HOST='www.random.org').status_code, 400)
        self.assertEqual(self.client.get('/no/such/page/').status_code, 404)
        self.assertEqual(ErrorEvent.objects.count(), 0)

    def test_compaction_clears_what_an_older_release_recorded(self) -> None:
        old = ErrorFingerprint.objects.create(hash='a' * 40, exc_type='DisallowedHost')
        ErrorEvent.objects.create(
            fingerprint=old, severity='ERROR', exc_type='DisallowedHost', message='x'
        )
        real = ErrorFingerprint.objects.create(hash='b' * 40, exc_type='ValueError')
        ErrorEvent.objects.create(
            fingerprint=real, severity='ERROR', exc_type='ValueError', message='y'
        )
        digest.compact(datetime.now(UTC))
        self.assertEqual(
            list(ErrorEvent.objects.values_list('exc_type', flat=True)), ['ValueError']
        )


class AllowedHostsScriptTests(SimpleTestCase):
    def run_script(self, **env: str) -> str:
        done = subprocess.run(
            ['sh', str(SCRIPT)],
            env={'PATH': '/usr/bin:/bin', **env},
            capture_output=True,
            text=True,
            check=True,
        )
        return done.stdout

    def test_it_lists_the_consoles_hosts_the_mail_host_and_the_server(self) -> None:
        out = self.run_script(
            ALLOWED_HOSTS='ifinsta.online,mail.ifinsta.online,api,localhost,127.0.0.1',
            MAIL_HOSTNAME='mail.ifinsta.online',
            SERVER_IP='203.0.113.5',
        )
        self.assertIn('default 0;', out)
        for host in ('ifinsta.online', 'mail.ifinsta.online', 'api', '203.0.113.5', '127.0.0.1'):
            self.assertIn(f'    {host} 1;', out)
        self.assertNotIn('autodiscover', out)  # setup names are let through by path instead
        self.assertEqual(out.count('mail.ifinsta.online 1;'), 1)  # nginx rejects a repeated key

    def test_a_wildcard_or_an_empty_list_fails_open(self) -> None:
        for allowed in ('*', ''):
            out = self.run_script(ALLOWED_HOSTS=allowed, MAIL_HOSTNAME='m.test')
            self.assertIn('default 1;', out)
            self.assertNotIn('default 0;', out)

    def test_odd_entries_are_ignored_not_trusted(self) -> None:
        out = self.run_script(ALLOWED_HOSTS='a.test,bad;host,x{y},.wild.test,A.TEST')
        self.assertIn('    a.test 1;', out)
        self.assertIn('    .wild.test 1;', out)
        self.assertNotIn('bad', out)
        self.assertNotIn('{y', out)
        self.assertEqual(out.count('a.test 1;'), 1)
