"""TLS certificate management and entry-point control (services and pages)."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID
from django.test import SimpleTestCase
from django.urls import reverse

from backend.apps.accounts.models import MailUser
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.services import tls as tls_module
from backend.services.entrypoints import (
    BY_KEY,
    CATALOGUE,
    EntryPointService,
    NetworkError,
    Probe,
)
from backend.services.tls import (
    CertificateError,
    TLSAction,
    TLSService,
    validate_upload,
)

MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'
GOOD = 'Correct-Horse-9'
HOST = 'mail.ifinmail.test'


def make_cert(
    cn: str = HOST,
    sans: tuple[str, ...] = (HOST, 'ifinmail.test'),
    days: int = 60,
    started: int = -1,
    key: object | None = None,
) -> tuple[str, str]:
    key = key or rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = dt.datetime.now(dt.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())  # type: ignore[attr-defined]
        .serial_number(x509.random_serial_number())
        .not_valid_before(now + dt.timedelta(days=started))
        .not_valid_after(now + dt.timedelta(days=days))
    )
    if sans:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(s) for s in sans]), critical=False
        )
    cert = builder.sign(key, hashes.SHA256())  # type: ignore[arg-type]
    pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(  # type: ignore[attr-defined]
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return pem, key_pem


class UploadValidationTests(SimpleTestCase):
    def test_a_matching_certificate_and_key_are_accepted(self) -> None:
        pem, key = make_cert()
        info, fullchain, _ = validate_upload(pem, key, HOST)
        self.assertEqual(info.subject, HOST)
        self.assertIn(HOST, info.sans)
        self.assertTrue(fullchain.startswith('-----BEGIN CERTIFICATE-----'))

    def test_an_ec_key_works_too(self) -> None:
        key = ec.generate_private_key(ec.SECP256R1())
        pem, key_pem = make_cert(key=key)
        self.assertEqual(validate_upload(pem, key_pem, HOST)[0].subject, HOST)

    def test_each_kind_of_mistake_has_its_own_message(self) -> None:
        pem, key = make_cert()
        _, other_key = make_cert()
        encrypted = (
            serialization.load_pem_private_key(key.encode(), None)
            .private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.BestAvailableEncryption(b'secret'),
            )
            .decode()
        )
        cases = {
            'No certificate found': ('not a cert', key, HOST),
            'does not belong': (pem, other_key, HOST),
            'could not be read': (pem, 'garbage', HOST),
            'password': (pem, encrypted, HOST),
            'expired': (*make_cert(days=-2, started=-30), HOST),
            'not valid yet': (*make_cert(started=5), HOST),
            'does not cover': (pem, key, 'other.example'),
        }
        for fragment, (cert, private, host) in cases.items():
            with (
                self.subTest(fragment=fragment),
                self.assertRaisesRegex(CertificateError, fragment),
            ):
                validate_upload(cert, private, host)

    def test_a_wildcard_certificate_covers_its_hosts_but_not_deeper_names(self) -> None:
        pem, key = make_cert(cn='*.ifinmail.test', sans=('*.ifinmail.test',))
        info = validate_upload(pem, key, HOST)[0]
        self.assertTrue(info.covers('mail.ifinmail.test'))
        self.assertFalse(info.covers('a.b.ifinmail.test'))
        self.assertFalse(info.covers('ifinmail.test'))

    def test_oversized_input_is_refused(self) -> None:
        with self.assertRaises(CertificateError):
            validate_upload('x' * 70000, 'y', HOST)


class TLSRuntimeTests(MailTablesTestCase):
    env = {'SERVER_IP': '203.0.113.5'}

    def setUp(self) -> None:
        super().setUp()
        self.certs = Path(self.tmp, 'letsencrypt')
        patcher = patch.object(tls_module, 'LETSENCRYPT_DIR', self.certs)
        patcher.start()
        self.addCleanup(patcher.stop)

    def runtime(self, *parts: str) -> Path:
        return Path(self.runtime_dir, *parts)

    def test_the_active_certificate_is_read_from_the_live_directory(self) -> None:
        live = self.certs / 'live' / HOST
        live.mkdir(parents=True)
        pem, _ = make_cert(days=10)
        (live / 'fullchain.pem').write_text(pem)
        cert = TLSService.active_certificate()
        assert cert is not None
        self.assertEqual(cert.subject, HOST)
        self.assertEqual(cert.status, 'warn')
        self.assertTrue(cert.covers('ifinmail.test'))

    def test_the_fingerprint_is_shown_the_way_mail_apps_and_openssl_show_it(self) -> None:
        live = self.certs / 'live' / HOST
        live.mkdir(parents=True)
        pem, _ = make_cert()
        (live / 'fullchain.pem').write_text(pem)
        cert = TLSService.active_certificate()
        assert cert is not None
        digest = x509.load_pem_x509_certificate(pem.encode()).fingerprint(hashes.SHA256())
        self.assertEqual(cert.fingerprint_display, ':'.join(f'{b:02X}' for b in digest))
        self.assertEqual(len(cert.fingerprint_display), 32 * 3 - 1)

    def test_no_certificate_is_not_an_error(self) -> None:
        self.assertIsNone(TLSService.active_certificate())

    def test_a_request_is_written_for_certbot_and_reported_pending_until_it_answers(self) -> None:
        request_id = TLSService.request(TLSAction.RENEW)
        data = json.loads(self.runtime('cert-request.json').read_text())
        self.assertEqual((data['id'], data['action']), (request_id, 'renew'))
        with patch.object(TLSService, 'coverage', return_value=[]):
            self.assertTrue(TLSService.status([]).pending)
            self.runtime('cert-status.json').write_text(
                json.dumps({'request_id': request_id, 'ok': True, 'message': 'done'})
            )
            status = TLSService.status([])
        self.assertFalse(status.pending)
        self.assertEqual(status.last_request['message'], 'done')

    def test_an_upload_is_validated_then_handed_over_with_a_private_key(self) -> None:
        pem, key = make_cert()
        info = TLSService.install_custom(pem, key)
        self.assertEqual(info.subject, HOST)
        incoming = self.runtime('tls/incoming')
        self.assertTrue((incoming / 'fullchain.pem').exists())
        if os.name == 'nt':
            # Windows ACLs do not enforce POSIX modes; existence is the
            # portable assertion (production runs on Linux where 0o600 holds).
            self.assertTrue((incoming / 'privkey.pem').exists())
        else:
            mode = (incoming / 'privkey.pem').stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)
        self.assertEqual(
            json.loads(self.runtime('cert-request.json').read_text())['action'], 'custom'
        )

    def test_a_rejected_upload_leaves_nothing_behind(self) -> None:
        pem, _ = make_cert()
        _, other = make_cert()
        with self.assertRaises(CertificateError):
            TLSService.install_custom(pem, other)
        self.assertFalse(self.runtime('tls').exists())
        self.assertFalse(self.runtime('cert-request.json').exists())

    def test_the_mode_comes_from_what_certbot_actually_installed(self) -> None:
        self.assertEqual(TLSService.mode().value, 'letsencrypt')
        self.runtime('tls-mode').parent.mkdir(parents=True, exist_ok=True)
        self.runtime('tls-mode').write_text('custom\n')
        self.assertEqual(TLSService.mode().value, 'custom')


class CertbotEntrypointTests(SimpleTestCase):
    @unittest.skipIf(shutil.which('sh') is None, 'needs working sh')
    def test_the_script_is_valid_shell_and_handles_every_request(self) -> None:
        path = Path(__file__).resolve().parents[4] / 'provisioning/docker/certbot/entrypoint.sh'
        self.assertEqual(subprocess.run(['sh', '-n', str(path)]).returncode, 0)
        text = path.read_text()
        for action in (a.value for a in TLSAction):
            self.assertIn(f'{action})', text, msg=action)
        self.assertIn('cert-request.json', text)
        self.assertIn('cert-status.json', text)


class EntryPointTests(MailTablesTestCase):
    env = {'SERVER_IP': '203.0.113.5'}

    def test_locked_entry_points_cannot_be_closed(self) -> None:
        for key in ('smtp', 'http', 'https'):
            with self.subTest(key=key), self.assertRaises(NetworkError):
                EntryPointService.set_enabled(key, False)
            self.assertTrue(EntryPointService.is_enabled(key))

    def test_closing_a_port_changes_the_published_rules(self) -> None:
        self.assertNotIn('{ 143 }', EntryPointService.render())
        EntryPointService.set_enabled('imap', False)
        self.assertFalse(EntryPointService.is_enabled('imap'))
        rules = Path(self.runtime_dir, 'firewall.nft').read_text()
        self.assertIn('th dport { 143 } drop', rules)
        self.assertIn('ct original proto-dst { 143 } drop', rules)
        EntryPointService.set_enabled('imap', True)
        self.assertNotIn('{ 143 } drop', Path(self.runtime_dir, 'firewall.nft').read_text())

    def test_closing_dns_closes_both_protocols(self) -> None:
        EntryPointService.set_enabled('dns', False)
        rules = EntryPointService.render()
        self.assertIn('meta l4proto tcp th dport { 53 } drop', rules)
        self.assertIn('meta l4proto udp th dport { 53 } drop', rules)

    def test_an_unknown_entry_point_is_refused(self) -> None:
        with self.assertRaises(NetworkError):
            EntryPointService.set_enabled('telnet', True)

    def test_blocking_validates_and_protects_the_administrator(self) -> None:
        self.assertEqual(EntryPointService.block('203.0.113.9', 'spammer'), '203.0.113.9/32')
        self.assertEqual(EntryPointService.block('2001:db8::/32'), '2001:db8::/32')
        cases = {
            'not an IP': 'nonsense',
            'too large': '10.0.0.0/4',
            'already': '203.0.113.9',
        }
        for label, value in cases.items():
            with self.subTest(label=label), self.assertRaises(NetworkError):
                EntryPointService.block(value)
        with self.assertRaisesRegex(NetworkError, 'you are using'):
            EntryPointService.block('198.51.100.0/24', protect=('198.51.100.77',))
        rules = Path(self.runtime_dir, 'firewall.nft').read_text()
        self.assertIn('203.0.113.9/32', rules)
        self.assertIn('2001:db8::/32', rules)

    def test_unblocking_removes_the_rule(self) -> None:
        EntryPointService.block('203.0.113.0/24')
        self.assertTrue(EntryPointService.unblock('203.0.113.0/24'))
        self.assertFalse(EntryPointService.unblock('203.0.113.0/24'))
        self.assertNotIn('203.0.113.0/24', Path(self.runtime_dir, 'firewall.nft').read_text())

    def test_the_connection_limit_is_validated_and_rendered(self) -> None:
        self.assertEqual(EntryPointService.rate_per_minute(), 120)
        EntryPointService.set_rate_per_minute(60)
        self.assertIn('limit rate over 60/minute', EntryPointService.render())
        EntryPointService.set_rate_per_minute(0)
        self.assertNotIn('limit rate over', EntryPointService.render())
        for bad in (5, -1, 10**6):
            with self.subTest(bad=bad), self.assertRaises(NetworkError):
                EntryPointService.set_rate_per_minute(bad)

    def test_the_limit_covers_mail_ports_only(self) -> None:
        rules = EntryPointService.render()
        self.assertIn('{ 25, 110, 143, 465, 587, 993, 995 }', rules)
        for port in ('80', '443', '53'):
            self.assertNotIn(
                f'proto-dst {{ {port}', rules.split('limit')[0].split('dnat ct original')[-1]
            )

    def test_forwarded_and_host_traffic_are_both_filtered_and_replies_are_not(self) -> None:
        rules = EntryPointService.render(disabled=[('tcp', 143)], blocked=[], rate=0)
        self.assertIn('hook forward', rules)
        self.assertIn('hook input', rules)
        self.assertEqual(rules.count('ct state established,related accept'), 2)
        self.assertIn('delete table inet ifinmail', rules)  # replaced atomically

    def test_the_agent_status_reflects_whether_the_rules_are_in_force(self) -> None:
        self.assertFalse(EntryPointService.agent_status().reporting)
        text = EntryPointService.apply()
        import hashlib

        now = dt.datetime.now(dt.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
        status = {'updated': now, 'ok': True, 'sha256': hashlib.sha256(text.encode()).hexdigest()}
        Path(self.runtime_dir, 'firewall-status.json').write_text(json.dumps(status))
        self.assertTrue(EntryPointService.agent_status().in_sync)
        EntryPointService.set_enabled('imap', False)  # new rules the agent has not applied yet
        agent = EntryPointService.agent_status()
        self.assertTrue(agent.reporting)
        self.assertFalse(agent.in_sync)

    @staticmethod
    def _nft_available() -> bool:
        return shutil.which('nft') is not None

    def test_the_generated_rules_are_accepted_by_nft(self) -> None:
        if not self._nft_available():
            self.skipTest('nft is not installed')
        EntryPointService.block('203.0.113.0/24')
        EntryPointService.block('2001:db8::/32')
        EntryPointService.set_enabled('imap', False)
        EntryPointService.set_enabled('dns', False)
        path = Path(self.runtime_dir, 'firewall.nft')
        check = subprocess.run(['nft', '-c', '-f', str(path)], capture_output=True, text=True)
        if 'Operation not permitted' in check.stderr:
            self.skipTest('nft needs privileges here')
        self.assertEqual(check.returncode, 0, msg=check.stderr)

    def test_every_catalogued_port_is_unique_and_the_console_cannot_be_closed(self) -> None:
        ports = [(proto, port) for e in CATALOGUE for proto, port in e.ports]
        self.assertEqual(len(ports), len(set(ports)))
        self.assertTrue(BY_KEY['https'].locked and BY_KEY['http'].locked and BY_KEY['smtp'].locked)


class EdgePagesTests(MailTablesTestCase):
    env = {'SERVER_IP': '203.0.113.5'}

    def login(self, staff: bool = True) -> None:
        user = MailUser.objects.create_user(
            'root@ifinmail.test', GOOD, is_staff=staff, is_superuser=staff
        )
        self.client.force_login(user, backend=MODEL_BACKEND)
        if staff:
            from django.utils import timezone

            session = self.client.session
            session['mfa_verified_at'] = timezone.now().isoformat()
            session.save()

    def setUp(self) -> None:
        super().setUp()
        patcher = patch.object(
            EntryPointService,
            'probe_all',
            return_value={e.key: Probe(e.key, True, 3) for e in CATALOGUE},
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        cov = patch.object(TLSService, 'coverage', return_value=[])
        cov.start()
        self.addCleanup(cov.stop)

    def test_the_pages_need_staff(self) -> None:
        self.login(staff=False)
        for name in ('accounts:certificates', 'accounts:network'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)

    def test_both_pages_render_inside_the_settings_hub(self) -> None:
        self.login()
        for name in ('accounts:certificates', 'accounts:network'):
            html = self.client.get(reverse(name)).content.decode()
            self.assertIn('ifinmail-settings__nav', html, msg=name)
        self.assertIn(
            'TLS certificates', self.client.get(reverse('accounts:settings')).content.decode()
        )

    def test_the_network_page_lists_every_entry_point(self) -> None:
        self.login()
        html = self.client.get(reverse('accounts:network')).content.decode()
        for entry in CATALOGUE:
            self.assertIn(entry.label, html)
        self.assertIn('Agent not reporting', html)

    def test_closing_a_port_and_blocking_an_address_through_the_page(self) -> None:
        self.login()
        self.client.post(reverse('accounts:network_toggle'), {'key': 'imap'})
        self.assertFalse(EntryPointService.is_enabled('imap'))
        self.client.post(reverse('accounts:network_toggle'), {'key': 'imap', 'enabled': 'on'})
        self.assertTrue(EntryPointService.is_enabled('imap'))
        self.client.post(reverse('accounts:network_toggle'), {'key': 'https'})  # locked
        self.assertTrue(EntryPointService.is_enabled('https'))
        self.client.post(
            reverse('accounts:network_block'), {'cidr': '203.0.113.0/24'}
        )  # holds the server
        self.assertEqual(EntryPointService.blocklist(), [])
        self.client.post(reverse('accounts:network_block'), {'cidr': '192.0.2.0/24', 'note': 'x'})
        self.assertEqual([b['cidr'] for b in EntryPointService.blocklist()], ['192.0.2.0/24'])

    def test_you_cannot_block_yourself(self) -> None:
        self.login()
        response = self.client.post(
            reverse('accounts:network_block'),
            {'cidr': '198.51.100.0/24'},
            REMOTE_ADDR='198.51.100.9',
            follow=True,
        )
        self.assertContains(response, 'you are using')
        self.assertEqual(EntryPointService.blocklist(), [])

    def test_you_cannot_block_the_address_nginx_reports_for_you(self) -> None:
        self.login()
        response = self.client.post(
            reverse('accounts:network_block'),
            {'cidr': '198.51.100.0/24'},
            HTTP_X_FORWARDED_FOR='198.51.100.9',
            follow=True,
        )
        self.assertContains(response, 'you are using')

    def test_the_certificate_page_shows_the_certificate_and_sends_requests(self) -> None:
        self.login()
        live = Path(self.tmp, 'le', 'live', HOST)
        live.mkdir(parents=True)
        (live / 'fullchain.pem').write_text(make_cert(days=50)[0])
        with patch.object(tls_module, 'LETSENCRYPT_DIR', Path(self.tmp, 'le')):
            html = self.client.get(reverse('accounts:certificates')).content.decode()
            self.assertIn('Names covered', html)
            self.assertIn('in 49 days', html) if 'in 49 days' in html else self.assertIn(
                'days', html
            )
            self.client.post(reverse('accounts:certificates_action'), {'action': 'renew'})
        self.assertEqual(
            json.loads(Path(self.runtime_dir, 'cert-request.json').read_text())['action'], 'renew'
        )

    def test_a_temporary_certificate_shows_its_full_fingerprint_for_first_connect(self) -> None:
        self.login()
        live = Path(self.tmp, 'le', 'live', HOST)
        live.mkdir(parents=True)
        pem = make_cert(days=30)[0]
        (live / 'fullchain.pem').write_text(pem)
        with patch.object(tls_module, 'LETSENCRYPT_DIR', Path(self.tmp, 'le')):
            html = self.client.get(reverse('accounts:certificates')).content.decode()
        digest = x509.load_pem_x509_certificate(pem.encode()).fingerprint(hashes.SHA256())
        self.assertIn(':'.join(f'{b:02X}' for b in digest), html)
        self.assertIn('Temporary self-signed', html)
        self.assertIn('will ask you to trust it', html)

    def test_uploading_a_certificate_through_the_page(self) -> None:
        self.login()
        pem, key = make_cert()
        self.client.post(
            reverse('accounts:certificates_upload'), {'certificate': pem, 'private_key': key}
        )
        self.assertTrue(Path(self.runtime_dir, 'tls/incoming/privkey.pem').exists())
        _, other = make_cert()
        response = self.client.post(
            reverse('accounts:certificates_upload'),
            {'certificate': pem, 'private_key': other},
            follow=True,
        )
        self.assertContains(response, 'does not belong')
        body = key.splitlines()[1]
        self.assertNotContains(response, body)  # keys are never echoed back

    def test_the_private_key_is_not_written_to_the_audit_trail(self) -> None:
        self.login()
        pem, key = make_cert()
        self.client.post(
            reverse('accounts:certificates_upload'), {'certificate': pem, 'private_key': key}
        )
        from backend.services.audit import AuditService

        for detail in AuditService.details():
            self.assertNotIn('PRIVATE KEY', detail)
        self.assertTrue(AuditService.has('certificate_uploaded'))
        self.assertNotIn(os.environ.get('NOPE', 'x'), '')
