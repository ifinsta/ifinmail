"""The exposure self-check, against small fake servers that behave well and badly."""

from __future__ import annotations

import http.client
import http.server
import socket
import struct
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.urls import reverse

from backend.apps.accounts.services import exposure
from backend.apps.accounts.tests import test_assistant_views as base
from backend.apps.core.platform.models import AuditEvent

LOCAL = '127.0.0.1'


def tcp_server(script: Callable[[socket.socket], None]) -> tuple[int, Callable[[], None]]:
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((LOCAL, 0))
    server.listen(8)
    server.settimeout(0.2)
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except (TimeoutError, OSError):
                continue
            try:
                script(conn)
            except OSError:
                pass
            finally:
                conn.close()

    threading.Thread(target=loop, daemon=True).start()
    return server.getsockname()[1], lambda: (stop.set(), server.close())


def smtp(
    *, vrfy: bool = False, auth: bool = False, relay: bool = False
) -> Callable[[socket.socket], None]:
    def script(conn: socket.socket) -> None:
        conn.sendall(b'220 mail.test ESMTP\r\n')
        conn.settimeout(2)
        while True:
            data = conn.recv(1024).decode().upper()
            if not data or data.startswith('QUIT'):
                return
            if data.startswith('EHLO'):
                lines = ['250-mail.test', '250-STARTTLS']
                if vrfy:
                    lines.append('250-VRFY')
                if auth:
                    lines.append('250-AUTH PLAIN LOGIN')
                lines.append('250 CHUNKING')
                conn.sendall(('\r\n'.join(lines) + '\r\n').encode())
            elif data.startswith('MAIL'):
                conn.sendall(b'250 2.1.0 Ok\r\n')
            elif data.startswith('RCPT'):
                conn.sendall(b'250 2.1.5 Ok\r\n' if relay else b'454 4.7.1 Relay access denied\r\n')
            else:
                conn.sendall(b'502 5.5.2 Error\r\n')

    return script


class MailProbeTests(SimpleTestCase):
    def run_smtp(self, **kw: bool) -> dict[str, str]:
        port, stop = tcp_server(smtp(**kw))
        self.addCleanup(stop)
        sub_port, sub_stop = tcp_server(smtp(auth=kw.get('auth', False)))
        self.addCleanup(sub_stop)
        with (
            patch.object(exposure, 'SMTP_PORT', port),
            patch.object(exposure, 'SUBMISSION_PORT', sub_port),
        ):
            return {c.key: c.status for c in exposure.check_smtp(LOCAL)}

    def test_a_well_configured_server_passes(self) -> None:
        self.assertEqual(self.run_smtp(), {'relay': 'ok', 'vrfy': 'ok', 'submission': 'ok'})

    def test_an_open_relay_is_an_error(self) -> None:
        self.assertEqual(self.run_smtp(relay=True)['relay'], 'error')

    def test_vrfy_is_a_warning(self) -> None:
        self.assertEqual(self.run_smtp(vrfy=True)['vrfy'], 'warning')

    def test_auth_before_tls_is_an_error(self) -> None:
        self.assertEqual(self.run_smtp(auth=True)['submission'], 'error')

    def test_imap_plaintext_login(self) -> None:
        for banner, expected in (
            (b'* OK [CAPABILITY IMAP4rev1 STARTTLS LOGINDISABLED] ready\r\n', 'ok'),
            (b'* OK [CAPABILITY IMAP4rev1 AUTH=PLAIN LOGIN] ready\r\n', 'error'),
        ):
            port, stop = tcp_server(lambda c, b=banner: c.sendall(b))
            self.addCleanup(stop)
            with patch.object(exposure, 'IMAP_PORT', port):
                self.assertEqual(exposure.check_imap(LOCAL)[0].status, expected)

    def test_a_port_that_does_not_answer_is_a_warning_not_a_pass(self) -> None:
        free = socket.socket()
        free.bind((LOCAL, 0))
        port = free.getsockname()[1]
        free.close()
        with patch.object(exposure, 'IMAP_PORT', port):
            self.assertEqual(exposure.check_imap(LOCAL)[0].status, 'warning')


class PortAndDnsTests(SimpleTestCase):
    def test_an_open_internal_port_is_an_error_and_closed_ones_pass(self) -> None:
        port, stop = tcp_server(lambda c: None)
        self.addCleanup(stop)
        with patch.object(exposure, 'MUST_BE_CLOSED', {port: 'a database'}):
            check = exposure.check_ports(LOCAL)[0]
        self.assertEqual(check.status, 'error')
        self.assertIn(f'{port} (a database)', check.detail)
        free = socket.socket()
        free.bind((LOCAL, 0))
        closed = free.getsockname()[1]
        free.close()
        with patch.object(exposure, 'MUST_BE_CLOSED', {closed: 'a database'}):
            self.assertEqual(exposure.check_ports(LOCAL)[0].status, 'ok')

    def dns_server(self, flags: int, answers: int) -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((LOCAL, 0))
        sock.settimeout(0.2)
        stop = threading.Event()

        def loop() -> None:
            while not stop.is_set():
                try:
                    data, addr = sock.recvfrom(512)
                except (TimeoutError, OSError):
                    continue
                reply = data[:2] + struct.pack('>HHHHH', flags, 1, answers, 0, 0) + data[12:]
                sock.sendto(reply, addr)

        threading.Thread(target=loop, daemon=True).start()
        self.addCleanup(lambda: (stop.set(), sock.close()))
        return sock.getsockname()[1]

    def test_recursion_for_strangers_is_an_error(self) -> None:
        port = self.dns_server(0x8180, 1)  # response, RD+RA, NOERROR, one answer
        with patch.object(exposure, 'DNS_PORT', port):
            self.assertEqual(exposure.check_dns(LOCAL)[0].status, 'error')

    def test_refused_or_silent_is_fine(self) -> None:
        port = self.dns_server(0x8105, 0)  # REFUSED
        with patch.object(exposure, 'DNS_PORT', port):
            self.assertEqual(exposure.check_dns(LOCAL)[0].status, 'ok')
        with patch.object(exposure, 'DNS_PORT', 9):  # nothing there
            self.assertEqual(exposure.check_dns(LOCAL)[0].status, 'ok')


class _Site(http.server.BaseHTTPRequestHandler):
    leak: set[str] = set()
    headers_out: dict[str, str] = {}
    server_name = 'nginx'

    def do_GET(self) -> None:  # noqa: N802
        if self.path in self.leak:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'DB_PASSWORD=hunter2')
            return
        self.send_response(404)
        for k, v in self.headers_out.items():
            self.send_header(k, v)
        self.end_headers()

    def log_message(self, *a: object) -> None:
        pass

    def version_string(self) -> str:
        return self.server_name


class WebProbeTests(SimpleTestCase):
    def setUp(self) -> None:
        self.httpd = http.server.ThreadingHTTPServer((LOCAL, 0), _Site)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(self.httpd.server_close)
        _Site.leak = set()
        _Site.headers_out = {}
        _Site.server_name = 'nginx'
        patcher = patch.object(
            exposure.http.client,
            'HTTPSConnection',
            lambda ip, port, timeout=5, context=None: http.client.HTTPConnection(
                ip, self.httpd.server_port, timeout=timeout
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_nothing_served_passes(self) -> None:
        check = exposure.check_paths(LOCAL, ['mail.test'])[0]
        self.assertEqual(check.status, 'ok')
        self.assertIn(str(len(exposure.SENSITIVE_PATHS)), check.detail)

    def test_a_served_secret_is_an_error_naming_it(self) -> None:
        _Site.leak = {'/.env', '/backup.sql'}
        check = exposure.check_paths(LOCAL, ['mail.test'])[0]
        self.assertEqual(check.status, 'error')
        self.assertIn('mail.test/.env (200)', check.detail)
        self.assertIn('2 of', check.detail)

    def test_headers(self) -> None:
        good = {
            'Strict-Transport-Security': 'max-age=1',
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'self'",
            'Referrer-Policy': 'same-origin',
        }
        _Site.headers_out = good
        self.assertEqual(exposure.check_headers(LOCAL, 'mail.test')[0].status, 'ok')
        _Site.headers_out = {}
        weak = exposure.check_headers(LOCAL, 'mail.test')[0]
        self.assertEqual(weak.status, 'warning')
        self.assertIn('missing', weak.detail)
        _Site.headers_out = good
        _Site.server_name = 'nginx/1.27.5'
        self.assertIn('version', exposure.check_headers(LOCAL, 'mail.test')[0].detail)


class TlsTests(SimpleTestCase):
    def tls(self, not_after: datetime, version: str = 'TLSv1.3') -> exposure.Check:
        sock = MagicMock()
        sock.getpeercert.return_value = {'notAfter': not_after.strftime('%b %d %H:%M:%S %Y GMT')}
        sock.version.return_value = version
        wrapped = MagicMock()
        wrapped.__enter__.return_value = sock
        context = MagicMock()
        context.wrap_socket.return_value = wrapped
        raw = MagicMock()
        raw.__enter__.return_value = raw
        with (
            patch.object(exposure.socket, 'create_connection', return_value=raw),
            patch.object(exposure.ssl, 'create_default_context', return_value=context),
        ):
            return exposure.check_tls('203.0.113.5', 'mail.test')[0]

    def test_months_left_is_fine_and_days_left_is_a_warning(self) -> None:
        self.assertEqual(self.tls(datetime.now(UTC) + timedelta(days=60)).status, 'ok')
        self.assertEqual(self.tls(datetime.now(UTC) + timedelta(days=5)).status, 'warning')
        self.assertEqual(self.tls(datetime.now(UTC) - timedelta(days=1)).status, 'error')

    def test_an_old_protocol_is_a_warning(self) -> None:
        self.assertEqual(
            self.tls(datetime.now(UTC) + timedelta(days=60), 'TLSv1.1').status, 'warning'
        )


class SummaryAndPageTests(base.AssistantBase):
    def result(self, *statuses: str, age_days: int = 0) -> dict:
        at = datetime.now(UTC) - timedelta(days=age_days)
        return {
            'at': at.isoformat(),
            'checks': [
                {'key': f'k{i}', 'group': 'web', 'title': f'Check {i}', 'status': s, 'detail': 'd'}
                for i, s in enumerate(statuses)
            ],
        }

    def test_the_summary(self) -> None:
        self.assertEqual(exposure.summarise(None)['state'], 'never')
        self.assertEqual(exposure.summarise(self.result('ok', 'ok'))['state'], 'ok')
        self.assertEqual(exposure.summarise(self.result('ok', 'warning'))['state'], 'warning')
        self.assertEqual(exposure.summarise(self.result('ok', 'error'))['state'], 'error')
        stale = exposure.summarise(self.result('ok', age_days=20))
        self.assertTrue(stale['stale'])
        self.assertEqual(stale['state'], 'warning')

    def test_the_task_stores_a_result_and_audits_it(self) -> None:
        from backend.apps.core.tasks import exposure_check

        fake = self.result('ok', 'error')
        with patch.object(exposure, 'run', return_value=fake):
            out = exposure_check()
        self.assertEqual(out['state'], 'error')
        self.assertEqual(exposure.last()['checks'][1]['status'], 'error')
        event = AuditEvent.objects.get(action='exposure_check')
        self.assertEqual(event.severity, 'warning')

    def test_system_health_and_the_network_page_show_it(self) -> None:
        from backend.apps.accounts.services import system_health

        exposure.store(self.result('ok', 'error'))
        check = system_health._exposure()
        self.assertEqual(check.state, 'error')
        page = self.client.get(reverse('accounts:network'))
        self.assertContains(page, 'Exposure check')
        self.assertContains(page, 'Fix this')
        exposure.store(self.result('ok', 'ok'))
        self.assertEqual(system_health._exposure().state, 'ok')

    def test_run_now_starts_the_check_and_is_guarded(self) -> None:
        from django.core.cache import cache

        cache.delete('exposure:running')
        with patch('backend.apps.core.tasks.exposure_check.delay') as delay:
            response = self.client.post(reverse('accounts:network_exposure_run'), follow=True)
        self.assertContains(response, 'The exposure check is running')
        delay.assert_called_once()
        self.assertTrue(AuditEvent.objects.filter(action='exposure_check_requested').exists())
        self.login('support@ifinmail.test', role='support')
        self.assertEqual(
            self.client.post(reverse('accounts:network_exposure_run')).status_code, 403
        )

    def test_it_only_ever_targets_this_servers_own_names(self) -> None:
        with patch.dict(
            'os.environ', {'MAIL_HOSTNAME': 'mail.ifinmail.test', 'SERVER_IP': '203.0.113.5'}
        ):
            self.assertEqual(exposure.target_ip(), '203.0.113.5')
            self.assertEqual(exposure.own_names()[0], 'mail.ifinmail.test')
        self.assertTrue(
            all(
                name.endswith('ifinmail.test')
                or name.split('.', 1)[0] in ('autodiscover', 'autoconfig', 'mta-sts')
                for name in exposure.own_names()
            )
            or not exposure.own_names()
        )
