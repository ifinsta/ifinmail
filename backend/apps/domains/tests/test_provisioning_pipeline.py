"""DKIM, DNS verification and the add-domain pipeline."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.apps.core.services import SystemSettings
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.core.types import SettingKey
from backend.apps.domains.models import DKIMKey, Domain
from backend.apps.domains.services.dkim import DKIMService
from backend.apps.domains.services.provisioning import (
    DomainProvisioningError,
    ProvisioningService,
    normalise_domain,
)
from backend.apps.domains.services.verification import DomainVerificationService
from backend.apps.domains.types.provisioning import CheckStatus
from backend.apps.mail.models import Alias, Mailbox
from backend.services.certificates import CertificateService
from backend.services.runtime import read_runtime_file

_LOOKUP = 'backend.apps.domains.services.verification._lookup'


class DKIMTests(MailTablesTestCase):
    def test_generate_stores_key_and_writes_a_file_rspamd_can_read(self) -> None:
        domain = self.make_domain()
        key, created = DKIMService.ensure(domain)
        self.assertTrue(created)
        path = DKIMService.key_path('ifinmail.test', 'default')
        self.assertTrue(path.is_file())
        if os.name != 'nt':
            # Windows ACLs do not enforce POSIX modes (production is Linux).
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        self.assertEqual(path.read_text(), key.private_key)
        self.assertTrue(path.name.startswith('ifinmail.test.default'))  # rspamd $domain.$selector

    def test_published_value_matches_the_private_key(self) -> None:
        key, _ = DKIMService.ensure(self.make_domain())
        value = DKIMService.public_txt_value(key.public_key)
        self.assertTrue(value.startswith('v=DKIM1; k=rsa; p='))
        der = base64.b64decode(value.split('p=', 1)[1])
        public = serialization.load_der_public_key(der)
        private = serialization.load_pem_private_key(key.private_key.encode(), password=None)
        self.assertEqual(public.public_numbers(), private.public_key().public_numbers())
        self.assertEqual(public.key_size, 2048)

    @unittest.skipIf(shutil.which('openssl') is None, 'needs openssl')
    def test_openssl_accepts_the_key_pair(self) -> None:
        key, _ = DKIMService.ensure(self.make_domain())
        path = DKIMService.key_path('ifinmail.test', 'default')
        result = subprocess.run(
            ['openssl', 'rsa', '-in', str(path), '-check', '-noout'],
            capture_output=True,
            text=True,
        )
        self.assertIn('RSA key ok', result.stdout)

    def test_ensure_is_idempotent_and_repairs_a_missing_file(self) -> None:
        domain = self.make_domain()
        first, _ = DKIMService.ensure(domain)
        second, created = DKIMService.ensure(domain)
        self.assertFalse(created)
        self.assertEqual(first.pk, second.pk)
        DKIMService.key_path('ifinmail.test', 'default').unlink()
        DKIMService.ensure(domain)
        self.assertTrue(DKIMService.key_path('ifinmail.test', 'default').is_file())

    def test_each_domain_gets_its_own_key(self) -> None:
        a, _ = DKIMService.ensure(self.make_domain('a.test'))
        b, _ = DKIMService.ensure(self.make_domain('b.test'))
        self.assertNotEqual(a.public_key, b.public_key)
        self.assertEqual(DKIMKey.objects.count(), 2)

    def test_key_generated_by_provision_sh_is_adopted_not_replaced(self) -> None:
        domain = self.make_domain()
        os.makedirs(self.dkim_dir)
        legacy = DKIMService.legacy_key_path('ifinmail.test', 'default')
        # Generate the legacy key in-process (no openssl binary needed).
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        legacy.write_text(
            private.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ).decode()
        )
        legacy_pem = legacy.read_text()
        key, created = DKIMService.ensure(domain)
        self.assertTrue(created)
        self.assertEqual(key.private_key, legacy_pem)
        self.assertTrue(DKIMService.key_path('ifinmail.test', 'default').is_file())

    def test_sync_files_restores_keys_on_a_fresh_volume(self) -> None:
        DKIMService.ensure(self.make_domain())
        DKIMService.key_path('ifinmail.test', 'default').unlink()
        self.assertEqual(DKIMService.sync_files(), 1)
        self.assertEqual(DKIMService.sync_files(), 0)


class VerificationTests(MailTablesTestCase):
    def _dns(self, **records: list[str] | None):
        def fake(name: str, rdtype: str):
            if rdtype == 'MX':
                return records.get('mx', [])
            if name.startswith('_dmarc.'):
                return records.get('dmarc', [])
            if '_domainkey' in name:
                return records.get('dkim', [])
            return records.get('spf', [])

        return patch(_LOOKUP, side_effect=fake)

    def test_correct_dns_passes_every_check_and_accepts_mail(self) -> None:
        domain = self.make_domain()
        key, _ = DKIMService.ensure(domain)
        with self._dns(
            mx=['10 mail.ifinmail.test'],
            spf=['v=spf1 mx -all'],
            dkim=[DKIMService.public_txt_value(key.public_key)],
            dmarc=['v=DMARC1; p=quarantine'],
        ):
            result = DomainVerificationService.verify(domain)
        domain.refresh_from_db()
        self.assertTrue(result.accepts_mail)
        self.assertTrue(
            all(
                [
                    domain.verified,
                    domain.mx_verified,
                    domain.spf_verified,
                    domain.dkim_verified,
                    domain.dmarc_verified,
                ]
            )
        )

    def test_mx_pointing_elsewhere_does_not_accept_mail(self) -> None:
        domain = self.make_domain()
        with self._dns(mx=['10 mx.other.example']):
            result = DomainVerificationService.verify(domain)
        domain.refresh_from_db()
        self.assertEqual(result.mx.status, CheckStatus.FAIL)
        self.assertFalse(domain.verified)
        self.assertFalse(domain.mx_verified)

    def test_dkim_mismatch_is_reported(self) -> None:
        domain = self.make_domain()
        DKIMService.ensure(domain)
        with self._dns(dkim=['v=DKIM1; k=rsa; p=AAAA']):
            result = DomainVerificationService.verify(domain)
        self.assertEqual(result.dkim.status, CheckStatus.FAIL)
        self.assertIn('does not match', result.dkim.detail)

    def test_spf_must_authorise_this_server(self) -> None:
        with self._dns(spf=['v=spf1 -all']):
            self.assertEqual(
                DomainVerificationService.check_spf('ifinmail.test').status, CheckStatus.FAIL
            )
        with self._dns(spf=['v=spf1 ip4:203.0.113.5 -all']):
            self.assertEqual(
                DomainVerificationService.check_spf('ifinmail.test').status, CheckStatus.PASS
            )

    def test_a_dns_outage_never_changes_stored_state_or_stops_mail(self) -> None:
        domain = self.make_domain(verified=True)
        Domain.objects.filter(pk=domain.pk).update(mx_verified=True)
        domain.refresh_from_db()
        with patch(_LOOKUP, return_value=None):
            result = DomainVerificationService.verify(domain)
        domain.refresh_from_db()
        self.assertEqual(result.mx.status, CheckStatus.ERROR)
        self.assertTrue(domain.verified)
        self.assertTrue(domain.mx_verified)

    def test_an_already_accepted_domain_is_never_switched_off_by_a_failed_check(self) -> None:
        domain = self.make_domain(verified=True)
        with self._dns(mx=['10 mx.other.example']):
            DomainVerificationService.verify(domain)
        domain.refresh_from_db()
        self.assertTrue(domain.verified)  # mail keeps flowing; only the MX flag turns red
        self.assertFalse(domain.mx_verified)

    def test_verify_all_records_the_time(self) -> None:
        self.make_domain()
        with patch(_LOOKUP, return_value=[]):
            DomainVerificationService.verify_all()
        self.assertTrue(SystemSettings.get(SettingKey.LAST_VERIFY_AT))


class ProvisioningTests(MailTablesTestCase):
    def _add(self, name: str = 'ifinmail.test', **kwargs):
        with (
            patch(_LOOKUP, return_value=[]),
            patch('backend.apps.dns.services.DNSService.get_server_ip', return_value='203.0.113.5'),
        ):
            return ProvisioningService.add_domain(name, **kwargs)

    def test_domain_name_is_validated_and_normalised(self) -> None:
        self.assertEqual(normalise_domain(' HTTPS://Mail.Example.COM. '), 'mail.example.com')
        for bad in ('', 'localhost', 'a b.com', '-x.com', 'x.c', 'a..com'):
            with self.assertRaises(DomainProvisioningError):
                normalise_domain(bad)

    def test_new_domain_gets_dkim_aliases_certificate_hosts_and_a_record_set(self) -> None:
        result = self._add()
        self.assertTrue(result.created)
        self.assertTrue(result.ok)
        steps = {s.name: s.status for s in result.steps}
        self.assertEqual(steps['DKIM key'], 'ok')
        self.assertEqual(steps['DNS records'], 'manual')  # no provider connected
        domain = Domain.objects.get(name='ifinmail.test')
        self.assertIsNotNone(DKIMService.get_active(domain))
        self.assertEqual(
            set(Alias.objects.values_list('source', 'destination')),
            {
                ('postmaster@ifinmail.test', 'admin@ifinmail.test'),
                ('abuse@ifinmail.test', 'admin@ifinmail.test'),
            },
        )
        hosts = read_runtime_file('cert-hosts.txt').split()
        self.assertEqual(
            hosts,
            [
                'mail.ifinmail.test',
                'autoconfig.ifinmail.test',
                'autodiscover.ifinmail.test',
                'ifinmail.test',
                'mta-sts.ifinmail.test',
            ],
        )
        names = {(r['type'], r['name']) for r in result.dns_records}
        self.assertIn(('CNAME', 'autoconfig'), names)
        self.assertIn(('TXT', 'default._domainkey'), names)

    def test_published_dkim_record_is_the_real_key_never_a_placeholder(self) -> None:
        result = self._add()
        dkim = next(r for r in result.dns_records if r['name'] == 'default._domainkey')
        self.assertNotIn('<add-dkim-key>', dkim['value'])
        domain = Domain.objects.get(name='ifinmail.test')
        self.assertEqual(dkim['value'], DKIMService.txt_value_for(domain.name))

    def test_running_it_twice_changes_nothing(self) -> None:
        self._add()
        key_before = DKIMKey.objects.get().public_key
        second = self._add()
        self.assertFalse(second.created)
        self.assertEqual(DKIMKey.objects.count(), 1)
        self.assertEqual(DKIMKey.objects.get().public_key, key_before)
        self.assertEqual(Alias.objects.count(), 2)

    def test_second_domain_is_independent_and_signed(self) -> None:
        self._add('ifinmail.test')
        self._add('other.test')
        self.assertEqual(DKIMKey.objects.count(), 2)
        self.assertTrue(DKIMService.key_path('other.test', 'default').is_file())
        hosts = read_runtime_file('cert-hosts.txt')
        self.assertIn('mta-sts.other.test', hosts)
        self.assertIn('mta-sts.ifinmail.test', hosts)

    def test_dns_records_are_pushed_when_a_provider_is_connected(self) -> None:
        from backend.apps.dns.services import DNSService

        DNSService.update_or_create_config('cloudflare', {'api_token': 'tok'})
        with patch(
            'backend.apps.dns.providers.cloudflare.CloudflareProvider.configure_domain'
        ) as push:
            push.return_value.success = True
            push.return_value.message = 'Created/updated 10 records'
            result = self._add()
        pushed = push.call_args.args[1]
        self.assertEqual(len(pushed), 10)
        self.assertFalse(DNSService.has_placeholder(pushed))
        self.assertEqual(next(s for s in result.steps if s.name == 'DNS records').status, 'ok')

    def test_a_failing_step_is_reported_but_the_others_still_run(self) -> None:
        with patch(
            'backend.apps.domains.services.dkim.DKIMService.ensure',
            side_effect=OSError('disk full'),
        ):
            result = self._add()
        steps = {s.name: s for s in result.steps}
        self.assertEqual(steps['DKIM key'].status, 'error')
        self.assertIn('disk full', steps['DKIM key'].detail)
        self.assertEqual(steps['Certificates'].status, 'ok')
        self.assertFalse(result.ok)

    def test_postmaster_aliases_are_skipped_without_an_admin_address(self) -> None:
        with patch.dict(os.environ, {'ADMIN_EMAIL': ''}):
            result = self._add()
        self.assertEqual(Alias.objects.count(), 0)
        self.assertEqual(
            next(s for s in result.steps if s.name == 'postmaster/abuse').status, 'warn'
        )

    def test_existing_postmaster_mailbox_is_not_shadowed_by_an_alias(self) -> None:
        domain = self.make_domain()
        Mailbox.objects.create(domain=domain, local_part='postmaster')
        self._add()
        self.assertFalse(Alias.objects.filter(source='postmaster@ifinmail.test').exists())
        self.assertTrue(Alias.objects.filter(source='abuse@ifinmail.test').exists())

    def test_new_domain_does_not_accept_mail_until_dns_points_here(self) -> None:
        self._add()
        self.assertFalse(Domain.objects.get(name='ifinmail.test').verified)

    def test_remove_domain_refuses_while_mailboxes_exist(self) -> None:
        self._add()
        Mailbox.objects.create(domain=Domain.objects.get(), local_part='a')
        with self.assertRaises(DomainProvisioningError):
            ProvisioningService.remove_domain('ifinmail.test')
        Mailbox.objects.all().delete()
        self.assertTrue(ProvisioningService.remove_domain('ifinmail.test'))
        self.assertEqual(Domain.objects.count(), 0)
        self.assertEqual(DKIMKey.objects.count(), 0)  # cascades

    def test_certificate_host_list_covers_every_domain(self) -> None:
        self.assertEqual(
            CertificateService.hosts_for(['b.test', 'a.test'])[0], 'mail.ifinmail.test'
        )
        hosts = CertificateService.hosts_for(['a.test'])
        self.assertEqual(
            hosts[1:], ['a.test', 'autoconfig.a.test', 'autodiscover.a.test', 'mta-sts.a.test']
        )
