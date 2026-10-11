"""The authoritative DNS server: zones, custom records, publishing and the pages."""

from __future__ import annotations

import os
import re
from pathlib import Path
from unittest.mock import patch

from django.urls import reverse

from backend.apps.accounts.models import MailUser
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.dns.models import CustomDNSRecord, DNSProviderConfig, DNSZone
from backend.apps.dns.services.records import CustomRecordService, RecordError
from backend.apps.dns.services.server import DNSServerConfig
from backend.apps.dns.services.zones import ZoneService, render_zone_file
from backend.apps.dns.types.zones import DelegationStatus, ZoneMode, ZoneRecord
from backend.apps.domains.models import Domain
from backend.apps.domains.services import DomainService
from backend.apps.domains.services.provisioning import ProvisioningService
from backend.apps.domains.types.provisioning import StepStatus

MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'
GOOD = 'Correct-Horse-9'


class _Base(MailTablesTestCase):
    env = {'SERVER_IP': '203.0.113.5', 'DNS_CONTAINER_RUNTIME': '/runtime'}

    def zone(self, name: str = 'ifinmail.test', mode: ZoneMode = ZoneMode.AUTHORITATIVE) -> str:
        self.make_domain(name)
        row = ZoneService.ensure(name)
        row.mode = mode.value
        row.save()
        return name

    def managed(self, zone: str) -> list[ZoneRecord]:
        return ZoneService.managed_records(zone)

    def add(self, zone: str, **kw: object) -> CustomDNSRecord:
        return CustomRecordService.add(zone, managed=self.managed(zone), **kw)  # type: ignore[arg-type]


class ManagedRecordTests(_Base):
    def test_the_mail_records_are_generated_for_a_zone(self) -> None:
        zone = self.zone()
        by = {(r.name, r.type): r for r in self.managed(zone)}
        self.assertEqual(by[('@', 'A')].value, '203.0.113.5')
        self.assertEqual(by[('@', 'MX')].value, 'mail.ifinmail.test')
        self.assertEqual(by[('@', 'MX')].priority, 10)
        self.assertTrue(
            any(r.type == 'TXT' and r.value.startswith('v=spf1') for r in self.managed(zone))
        )
        self.assertIn(('_dmarc', 'TXT'), by)
        self.assertIn(('_mta-sts', 'TXT'), by)
        self.assertIn(('autoconfig', 'CNAME'), by)
        self.assertIn(('_submission._tcp', 'SRV'), by)

    def test_mail_and_dav_clients_can_discover_every_service_from_the_domain(self) -> None:
        zone = self.zone()
        srv = {r.name: r.value for r in self.managed(zone) if r.type == 'SRV'}
        host = 'mail.ifinmail.test'
        self.assertEqual(srv['_submission._tcp'], f'1 587 {host}')
        self.assertEqual(srv['_imaps._tcp'], f'1 993 {host}')
        self.assertEqual(srv['_pop3s._tcp'], f'1 995 {host}')
        self.assertEqual(srv['_caldavs._tcp'], f'1 443 {host}')
        self.assertEqual(srv['_carddavs._tcp'], f'1 443 {host}')
        txt = {r.name: r.value for r in self.managed(zone) if r.type == 'TXT'}
        self.assertEqual(txt['_caldavs._tcp'], 'path=/dav/')
        self.assertEqual(txt['_carddavs._tcp'], 'path=/dav/')

    def test_the_server_is_its_own_nameserver_with_glue_inside_the_zone(self) -> None:
        zone = self.zone()
        ns = [r.value for r in self.managed(zone) if r.type == 'NS']
        self.assertEqual(ns, ['ns1.mail.ifinmail.test', 'ns2.mail.ifinmail.test'])
        glue = {r.name for r in self.managed(zone) if r.type == 'A'}
        self.assertTrue({'ns1.mail', 'ns2.mail'} <= glue)

    def test_a_domain_outside_the_nameserver_zone_gets_no_glue(self) -> None:
        zone = self.zone('other.example')
        self.assertFalse({'ns1.mail', 'ns2.mail'} & {r.name for r in self.managed(zone)})

    def test_caa_can_be_turned_off(self) -> None:
        zone = self.zone()
        self.assertTrue(any(r.type == 'CAA' for r in self.managed(zone)))
        from backend.apps.core.services import SystemSettings
        from backend.apps.core.types import SettingKey

        SystemSettings.set(SettingKey.DNS_CAA_ENABLED, False)
        self.assertFalse(any(r.type == 'CAA' for r in self.managed(zone)))

    def test_the_dkim_record_is_not_published_until_the_key_exists(self) -> None:
        zone = self.zone()
        self.assertFalse(any('_domainkey' in r.name for r in self.managed(zone)))

    def test_ipv6_adds_aaaa_records(self) -> None:
        zone = self.zone()
        with patch.dict(os.environ, {'SERVER_IPV6': '2001:db8::5'}):
            self.assertTrue(any(r.type == 'AAAA' and r.name == '@' for r in self.managed(zone)))


class ZoneFileTests(_Base):
    def test_the_zone_file_has_origin_soa_and_fully_qualified_targets(self) -> None:
        text = render_zone_file('ifinmail.test', self.managed(self.zone()), 42)
        self.assertIn('$ORIGIN ifinmail.test.', text)
        self.assertRegex(
            text, r'@ IN SOA ns1\.mail\.ifinmail\.test\. hostmaster\.ifinmail\.test\. 42 '
        )
        self.assertIn('@ 3600 IN MX 10 mail.ifinmail.test.', text)
        self.assertIn('autoconfig 3600 IN CNAME mail.ifinmail.test.', text)

    def test_txt_values_are_quoted_escaped_and_split_at_255_bytes(self) -> None:
        records = [ZoneRecord('@', 'TXT', 'say "hi"\\x'), ZoneRecord('long', 'TXT', 'a' * 600)]
        text = render_zone_file('t.test', records, 1)
        self.assertIn(r'"say \"hi\"\\x"', text)
        long_line = next(line for line in text.splitlines() if line.startswith('long'))
        self.assertEqual(len(re.findall(r'"a+"', long_line)), 3)

    def test_srv_and_caa_render_with_their_fields(self) -> None:
        records = [
            ZoneRecord('_x._tcp', 'SRV', '5 5060 sip.t.test', priority=10),
            ZoneRecord('@', 'CAA', '0 issue letsencrypt.org'),
        ]
        text = render_zone_file('t.test', records, 1)
        self.assertIn('_x._tcp 3600 IN SRV 10 5 5060 sip.t.test.', text)
        self.assertIn('@ 3600 IN CAA 0 issue "letsencrypt.org"', text)


class CustomRecordTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.z = self.zone()

    def test_a_valid_record_is_stored_relative_to_the_zone(self) -> None:
        record = self.add(self.z, name='WWW.ifinmail.test.', rtype='a', value='192.0.2.9')
        self.assertEqual((record.name, record.rtype, record.value), ('www', 'A', '192.0.2.9'))

    def test_bad_data_is_rejected_with_a_readable_reason(self) -> None:
        bad = [
            dict(name='x', rtype='A', value='999.1.1.1'),
            dict(name='x', rtype='AAAA', value='192.0.2.1'),
            dict(name='x', rtype='MX', value='mail.example.org'),  # no priority
            dict(name='x', rtype='CNAME', value='not a host'),
            dict(name='x', rtype='SRV', value='bad', priority=1),
            dict(name='x', rtype='CAA', value='nonsense'),
            dict(name='bad name', rtype='A', value='192.0.2.1'),
            dict(name='x', rtype='A', value='192.0.2.1', ttl=5),
            dict(name='x', rtype='TXT', value='a' * 3000),
            dict(name='x', rtype='SOA', value='nope'),
        ]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(RecordError):
                self.add(self.z, **kwargs)

    def test_a_cname_must_be_alone_at_its_name(self) -> None:
        self.add(self.z, name='app', rtype='A', value='192.0.2.1')
        with self.assertRaises(RecordError):
            self.add(self.z, name='app', rtype='CNAME', value='x.example.org')
        self.add(self.z, name='blog', rtype='CNAME', value='x.example.org')
        with self.assertRaises(RecordError):
            self.add(self.z, name='blog', rtype='A', value='192.0.2.1')

    def test_a_cname_cannot_take_a_name_that_carries_managed_records(self) -> None:
        for name in ('mail', 'autoconfig', '_dmarc'):
            with self.subTest(name=name), self.assertRaises(RecordError):
                self.add(self.z, name=name, rtype='CNAME', value='x.example.org')

    def test_the_apex_cannot_be_a_cname_or_get_its_own_ns(self) -> None:
        with self.assertRaises(RecordError):
            self.add(self.z, name='@', rtype='CNAME', value='x.example.org')
        with self.assertRaises(RecordError):
            self.add(self.z, name='@', rtype='NS', value='ns.example.org')
        self.add(self.z, name='sub', rtype='NS', value='ns.example.org')  # delegation is fine

    def test_a_second_spf_or_dmarc_record_is_refused_but_other_txt_is_fine(self) -> None:
        with self.assertRaises(RecordError):
            self.add(self.z, name='@', rtype='TXT', value='v=spf1 include:x.example -all')
        with self.assertRaises(RecordError):
            self.add(self.z, name='_dmarc', rtype='TXT', value='v=DMARC1; p=none')
        self.add(self.z, name='@', rtype='TXT', value='google-site-verification=abc')

    def test_duplicates_are_refused(self) -> None:
        self.add(self.z, name='x', rtype='A', value='192.0.2.1')
        with self.assertRaises(RecordError):
            self.add(self.z, name='x', rtype='A', value='192.0.2.1')

    def test_wildcards_are_allowed_only_as_the_first_label(self) -> None:
        self.add(self.z, name='*.apps', rtype='A', value='192.0.2.1')
        with self.assertRaises(RecordError):
            self.add(self.z, name='a.*', rtype='A', value='192.0.2.1')

    def test_records_are_removed_with_their_zone(self) -> None:
        self.add(self.z, name='x', rtype='A', value='192.0.2.1')
        ZoneService.remove(self.z)
        self.assertEqual(CustomDNSRecord.objects.count(), 0)
        self.assertEqual(DNSZone.objects.count(), 0)


class PublishTests(_Base):
    def runtime(self, *parts: str) -> Path:
        return Path(self.runtime_dir, *parts)

    def test_publish_writes_zone_files_and_the_knot_configuration(self) -> None:
        zone = self.zone()
        result = ZoneService.publish()
        self.assertEqual(result.zones, [zone])
        self.assertIn(
            '$ORIGIN ifinmail.test.', self.runtime('dns/zones/ifinmail.test.zone').read_text()
        )
        conf = self.runtime('dns/knot.generated.conf').read_text()
        self.assertIn('domain: ifinmail.test', conf)
        self.assertIn('file: /runtime/dns/zones/ifinmail.test.zone', conf)

    def test_the_serial_moves_only_when_the_content_changes(self) -> None:
        zone = self.zone()
        ZoneService.publish()
        first = DNSZone.objects.get(zone=zone).serial
        self.assertEqual(ZoneService.publish().changed, [])
        self.assertEqual(DNSZone.objects.get(zone=zone).serial, first)
        self.add(zone, name='new', rtype='A', value='192.0.2.1')
        self.assertEqual(ZoneService.publish().changed, [zone])
        self.assertGreater(DNSZone.objects.get(zone=zone).serial, first)

    def test_a_zone_that_is_hosted_elsewhere_is_not_published_and_its_file_is_removed(self) -> None:
        zone = self.zone()
        ZoneService.publish()
        path = self.runtime('dns/zones/ifinmail.test.zone')
        self.assertTrue(path.exists())
        result = ZoneService.set_mode(zone, ZoneMode.EXTERNAL)
        self.assertEqual(result.mode, ZoneMode.EXTERNAL.value)
        self.assertFalse(path.exists())
        self.assertNotIn('ifinmail.test', self.runtime('dns/knot.generated.conf').read_text())

    def test_secondaries_get_an_acl_and_notify(self) -> None:
        self.zone()
        DNSServerConfig.set_secondaries(['198.51.100.7', '2001:db8::7'])
        ZoneService.publish()
        conf = self.runtime('dns/knot.generated.conf').read_text()
        self.assertIn('action: transfer', conf)
        self.assertIn('198.51.100.7', conf)
        self.assertIn('notify: [sec0, sec1]', conf)
        with self.assertRaises(ValueError):
            DNSServerConfig.set_secondaries(['nope'])

    def test_the_ds_records_written_by_the_dns_container_are_parsed(self) -> None:
        zone = self.zone()
        ds = self.runtime('dns/ds/ifinmail.test.ds')
        ds.parent.mkdir(parents=True)
        ds.write_text(
            'ifinmail.test. DS 10490 13 2 '
            '34689C9CFD84F8AE19EBE598E1044F4D5D4ABD88A4BD84D7A1937D22920A739B\n'
            'ifinmail.test. DS 10490 13 4 c96af244869d1016cb8fd6da3f1163f4\n'
        )
        found = ZoneService.ds_records(zone)
        self.assertEqual(
            [(d.key_tag, d.algorithm, d.digest_type) for d in found],
            [(10490, 13, 2), (10490, 13, 4)],
        )
        self.assertEqual(found[0].text().split()[3], found[0].digest)

    def test_a_connected_provider_means_new_domains_stay_external(self) -> None:
        DNSProviderConfig.objects.create(provider='cloudflare', credentials={})
        self.make_domain('p.example')
        self.assertEqual(ZoneService.ensure('p.example').mode, ZoneMode.EXTERNAL.value)

    def test_the_dns_server_can_be_turned_off(self) -> None:
        with patch.dict(os.environ, {'DNS_SERVER_ENABLED': '0'}):
            self.make_domain('off.example')
            self.assertEqual(ZoneService.ensure('off.example').mode, ZoneMode.EXTERNAL.value)
            with self.assertRaises(ValueError):
                ZoneService.set_mode('off.example', ZoneMode.AUTHORITATIVE)


class ProvisioningIntegrationTests(_Base):
    def test_adding_a_domain_publishes_its_zone_and_asks_for_the_nameservers(self) -> None:
        with patch('backend.apps.domains.services.provisioning.DomainVerificationService.verify'):
            result = ProvisioningService.add_domain('new.example', verify=False)
        step = next(s for s in result.steps if s.name == 'DNS records')
        self.assertEqual(step.status, StepStatus.MANUAL)
        self.assertIn('ns1.mail.ifinmail.test', step.detail)
        self.assertEqual(result.nameservers, ['ns1.mail.ifinmail.test', 'ns2.mail.ifinmail.test'])
        self.assertTrue(Path(self.runtime_dir, 'dns/zones/new.example.zone').exists())

    def test_deleting_a_domain_removes_its_zone(self) -> None:
        with patch('backend.apps.domains.services.provisioning.DomainVerificationService.verify'):
            ProvisioningService.add_domain('gone.example', verify=False)
        DomainService.delete_domain('gone.example')
        self.assertFalse(DNSZone.objects.filter(zone='gone.example').exists())
        self.assertFalse(Path(self.runtime_dir, 'dns/zones/gone.example.zone').exists())

    def test_the_periodic_job_republishes(self) -> None:
        from backend.apps.dns.tasks import publish_zones

        self.zone()
        self.assertEqual(publish_zones(), ['ifinmail.test'])


class DNSPagesTests(_Base):
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
        self.z = self.zone()
        patcher = patch(
            'backend.apps.dns.views.server.DelegationService.check',
            return_value=DelegationStatus(
                zone=self.z, serving=True, delegated=False, expected_ns=('ns1.mail.ifinmail.test',)
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        alive = patch('backend.apps.dns.views.server.dns_server_alive', return_value=(True, ''))
        alive.start()
        self.addCleanup(alive.stop)

    def test_the_pages_need_a_staff_login(self) -> None:
        self.login(staff=False)
        for url in (reverse('dns:server'), reverse('dns:zone', kwargs={'zone': self.z})):
            self.assertEqual(self.client.get(url).status_code, 302)

    def test_the_server_page_lists_the_zones_and_nameservers(self) -> None:
        self.login()
        html = self.client.get(reverse('dns:server')).content.decode()
        self.assertIn('ifinmail.test', html)
        self.assertIn('ns1.mail.ifinmail.test', html)
        self.assertIn('Answering queries', html)
        self.assertIn('ifinmail-settings__nav', html)  # inside the Settings hub

    def test_the_zone_page_shows_records_delegation_help_and_glue(self) -> None:
        self.login()
        html = self.client.get(reverse('dns:zone', kwargs={'zone': self.z})).content.decode()
        self.assertIn('Managed', html)
        self.assertIn('set the nameservers of this domain to', html)
        self.assertIn('203.0.113.5', html)  # glue address

    def test_an_unknown_zone_is_a_404(self) -> None:
        self.login()
        self.assertEqual(
            self.client.get(reverse('dns:zone', kwargs={'zone': 'nope.example'})).status_code, 404
        )

    def test_adding_and_removing_a_record_through_the_page(self) -> None:
        self.login()
        add = self.client.post(
            reverse('dns:record_add'),
            {'zone': self.z, 'name': 'www', 'rtype': 'A', 'value': '192.0.2.9', 'ttl': '300'},
        )
        self.assertEqual(add.status_code, 302)
        record = CustomDNSRecord.objects.get(zone=self.z)
        self.assertEqual(record.ttl, 300)
        self.assertIn(
            'www 300 IN A 192.0.2.9',
            Path(self.runtime_dir, 'dns/zones/ifinmail.test.zone').read_text(),
        )
        self.client.post(
            reverse('dns:record_delete'), {'zone': self.z, 'record_id': str(record.id)}
        )
        self.assertEqual(CustomDNSRecord.objects.count(), 0)
        self.assertNotIn(
            '192.0.2.9', Path(self.runtime_dir, 'dns/zones/ifinmail.test.zone').read_text()
        )

    def test_an_invalid_record_shows_an_error_and_changes_nothing(self) -> None:
        self.login()
        response = self.client.post(
            reverse('dns:record_add'),
            {'zone': self.z, 'name': 'mail', 'rtype': 'CNAME', 'value': 'x.example.org'},
            follow=True,
        )
        self.assertContains(response, 'CNAME')
        self.assertEqual(CustomDNSRecord.objects.count(), 0)

    def test_switching_a_zone_between_this_server_and_external(self) -> None:
        self.login()
        self.client.post(reverse('dns:zone_mode'), {'zone': self.z, 'mode': 'external'})
        self.assertEqual(DNSZone.objects.get(zone=self.z).mode, 'external')
        html = self.client.get(reverse('dns:zone', kwargs={'zone': self.z})).content.decode()
        self.assertIn('hosted elsewhere', html)
        self.client.post(reverse('dns:zone_mode'), {'zone': self.z, 'mode': 'authoritative'})
        self.assertEqual(DNSZone.objects.get(zone=self.z).mode, 'authoritative')

    def test_secondary_addresses_are_validated(self) -> None:
        self.login()
        self.client.post(reverse('dns:secondaries'), {'addresses': '198.51.100.7\n198.51.100.8'})
        self.assertEqual(DNSServerConfig.secondaries(), ['198.51.100.7', '198.51.100.8'])
        self.client.post(reverse('dns:secondaries'), {'addresses': 'not-an-ip'})
        self.assertEqual(DNSServerConfig.secondaries(), ['198.51.100.7', '198.51.100.8'])

    def test_changes_are_audited(self) -> None:
        self.login()
        self.client.post(
            reverse('dns:record_add'),
            {'zone': self.z, 'name': 'a', 'rtype': 'A', 'value': '192.0.2.1'},
        )
        from backend.services.audit import AuditService

        self.assertTrue(AuditService.has('dns_record_added'))

    def test_the_domain_exists_check_uses_real_domains(self) -> None:
        self.assertEqual(Domain.objects.filter(name=self.z).count(), 1)
