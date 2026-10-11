"""Static guards for provisioning bugs that only show up when the real services run.

Each assertion below corresponds to a failure found by running Dovecot, Rspamd,
Postfix, nginx and PostgreSQL against the provisioning files; they cannot be hit
by Django's own tests, so the files are checked directly.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[4]
DOCKER = ROOT / 'provisioning' / 'docker'


def _read(*parts: str) -> str:
    return (DOCKER.joinpath(*parts)).read_text()


class DovecotContractTests(SimpleTestCase):
    def test_authentication_is_actually_included(self) -> None:
        """auth-sql.conf.ext does not match dovecot.conf's conf.d/*.conf glob, so without an
        explicit include Dovecot starts with no passdb and nobody can sign in."""
        main = _read('dovecot', 'dovecot.conf')
        self.assertIn('!include conf.d/*.conf', main)
        auth = _read('dovecot', 'conf.d', '10-auth.conf')
        self.assertRegex(auth, r'(?m)^!include auth-sql\.conf\.ext')
        self.assertTrue((DOCKER / 'dovecot' / 'conf.d' / 'auth-sql.conf.ext').is_file())

    def test_quota_plugin_and_per_mailbox_limit_are_wired(self) -> None:
        self.assertRegex(
            _read('dovecot', 'conf.d', '10-mail.conf'), r'mail_plugins = \$mail_plugins quota'
        )
        self.assertIn('imap_quota', _read('dovecot', 'conf.d', '90-sieve.conf'))
        sql = _read('dovecot', 'dovecot-sql.conf.ext')
        self.assertIn('userdb_quota_rule', sql)  # passdb-time userdb
        self.assertIn('AS quota_rule', sql)  # userdb lookups (LMTP delivery)
        self.assertIn('quota_bytes', sql)
        self.assertIn('quota = maildir:User quota', _read('dovecot', 'conf.d', '90-quota.conf'))


class RspamdContractTests(SimpleTestCase):
    def test_every_domain_is_signed_from_its_own_key_file(self) -> None:
        conf = _read('rspamd', 'local.d', 'dkim_signing.conf')
        self.assertIn('path = "/etc/dkim/$domain.$selector.key";', conf)
        # rspamd treats the global path/selector as a *fallback*: without this it logs
        # "dkim unconfigured and fallback disabled" and signs nothing.
        self.assertRegex(conf, r'(?m)^try_fallback = true;')
        self.assertNotIn('domain {', conf)

    def test_the_key_directory_is_writable_by_the_api_and_read_only_for_rspamd(self) -> None:
        compose = _read('docker-compose.yml')
        self.assertRegex(compose, r'\./dkim:/etc/dkim:ro')  # rspamd
        self.assertGreaterEqual(len(re.findall(r'\./dkim:/etc/dkim\s', compose)), 2)  # api + worker

    def test_the_app_writes_the_file_name_rspamd_looks_for(self) -> None:
        from backend.apps.domains.services.dkim import DKIMService

        self.assertEqual(
            DKIMService.key_path('example.com', 'default').name, 'example.com.default.key'
        )


class DatabaseContractTests(SimpleTestCase):
    def test_dovecot_may_read_the_tables_its_queries_join(self) -> None:
        sql = _read('dovecot', 'dovecot-sql.conf.ext')
        init = _read('init-db.sh')
        for table in re.findall(r'(?:FROM|JOIN)\s+(\w+)', sql):
            self.assertIn(f'GRANT SELECT ON {table} TO dovecot;', init, msg=table)

    def test_postfix_only_accepts_mail_for_verified_domains_so_something_must_set_the_flag(
        self,
    ) -> None:
        self.assertIn('verified = TRUE', _read('postfix', 'pgsql', 'virtual_domains.cf'))
        from backend.apps.domains.services import verification

        self.assertIn("fields['verified'] = True", Path(verification.__file__).read_text())

    def test_aliases_are_looked_up_by_full_address(self) -> None:
        self.assertIn("source = '%s'", _read('postfix', 'pgsql', 'virtual_aliases.cf'))


class ContainerContractTests(SimpleTestCase):
    def test_compose_runs_the_background_jobs_and_shares_the_runtime_volume(self) -> None:
        compose = _read('docker-compose.yml')
        for service in ('  worker:', '  beat:'):
            self.assertIn(service, compose)
        self.assertIn('celery", "-A", "backend.config.celery", "worker"', compose)
        self.assertIn('celery", "-A", "backend.config.celery", "beat"', compose)
        self.assertIn('runtime_data:/var/lib/ifinmail/runtime:ro', compose)  # postfix reads
        self.assertIn('runtime_data:/runtime ', compose)  # certbot reads and reports back (rw)
        self.assertNotIn('runtime_data:/runtime:ro', compose)
        self.assertNotIn('profiles:', compose.split('  certbot:')[1].split('  # ---')[0])

    def test_certbot_entrypoint_runs_one_off_commands(self) -> None:
        """obtain-ssl.sh does `compose run certbot certonly ...`; an entrypoint that ignores its
        arguments would loop forever instead of issuing the certificate."""
        entry = _read('certbot', 'entrypoint.sh')
        self.assertRegex(entry, r'if \[ "\$#" -gt 0 \]; then\s+exec certbot "\$@"')

    def test_nginx_never_lets_clients_choose_the_host_django_sees(self) -> None:
        conf = _read('nginx', 'conf.d', 'ifinmail.conf')
        self.assertEqual(conf.count('proxy_set_header Host __SSL_CERT_HOSTNAME__;'), 2)
        self.assertEqual(conf.count('proxy_set_header X-Original-Host $host;'), 2)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", conf)

    def test_api_image_can_write_the_shared_directories(self) -> None:
        dockerfile = _read('Dockerfile')
        self.assertIn('/var/lib/ifinmail/runtime', dockerfile)
        self.assertIn('/etc/dkim', dockerfile)

    def test_entrypoint_provisions_existing_domains_on_every_start(self) -> None:
        self.assertIn('manage.py provision_domains', _read('entrypoint.sh'))


@pytest.mark.skipif(
    subprocess.run(['which', 'bash'], capture_output=True).returncode != 0, reason='needs bash'
)
class ShellSyntaxTests(SimpleTestCase):
    def test_every_provisioning_script_parses(self) -> None:
        scripts = [
            *(ROOT / 'provisioning' / 'scripts').glob('*.sh'),
            DOCKER / 'postfix' / 'sync-overrides.sh',
            DOCKER / 'postfix' / 'entrypoint.sh',
            DOCKER / 'certbot' / 'entrypoint.sh',
            DOCKER / 'entrypoint.sh',
        ]
        for script in scripts:
            shell = (
                'sh' if script.name in ('entrypoint.sh',) and 'certbot' in str(script) else 'bash'
            )
            result = subprocess.run([shell, '-n', str(script)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, msg=f'{script}: {result.stderr}')


class AuthoritativeServerContractTests(SimpleTestCase):
    """DNS, TLS and the firewall are separate containers the console only talks to through files."""

    def _compose(self) -> dict:
        import yaml

        return yaml.safe_load(_read('docker-compose.yml'))

    def test_the_dns_container_serves_port_53_on_both_protocols_and_keeps_its_keys(self) -> None:
        compose = self._compose()
        dns = compose['services']['dns']
        self.assertEqual(
            sorted(dns['ports']),
            ['${DNS_BIND_IP:-0.0.0.0}:53:53/tcp', '${DNS_BIND_IP:-0.0.0.0}:53:53/udp'],
        )
        self.assertIn('dns_data:/var/lib/knot', dns['volumes'])  # DNSSEC keys survive a rebuild
        self.assertIn('runtime_data:/runtime', dns['volumes'])
        self.assertIn('dns_data', compose['volumes'])

    def test_the_console_and_worker_know_the_server_address_and_nameservers(self) -> None:
        compose = self._compose()
        for service in ('api', 'worker'):
            env = compose['services'][service]['environment']
            for name in ('SERVER_IP', 'DNS_NS_HOSTS', 'DNS_SERVER_HOST', 'DNS_SERVER_ENABLED'):
                self.assertIn(name, env, msg=f'{service}: {name}')

    def test_the_firewall_agent_runs_on_the_host_network_with_only_net_admin(self) -> None:
        firewall = self._compose()['services']['firewall']
        self.assertEqual(firewall['network_mode'], 'host')
        self.assertEqual(firewall['cap_add'], ['NET_ADMIN'])
        self.assertNotIn('privileged', firewall)
        self.assertNotIn('ports', firewall)

    def test_knot_signs_zones_with_dnssec_limits_responses_and_hides_its_version(self) -> None:
        conf = _read('dns', 'knot.conf')
        for line in (
            'dnssec-signing: on',
            'dnssec-policy: ifinmail',
            'zonefile-load: difference-no-serial',
            'global-module: mod-rrl/default',
            'nsec3: on',
            'include: /runtime/dns/knot.generated.conf',
            'version: ""',
        ):
            self.assertIn(line, conf)
        self.assertNotIn(
            'action: transfer', conf
        )  # transfers only to the secondaries the console lists

    def test_the_container_scripts_are_valid_shell(self) -> None:
        for path in (
            ('dns', 'entrypoint.sh'),
            ('firewall', 'entrypoint.sh'),
            ('certbot', 'entrypoint.sh'),
        ):
            result = subprocess.run(['sh', '-n', str(DOCKER.joinpath(*path))], capture_output=True)
            self.assertEqual(result.returncode, 0, msg=str(path))

    def test_the_dns_container_exports_ds_records_and_reloads_on_change(self) -> None:
        script = _read('dns', 'entrypoint.sh')
        self.assertIn('keymgr', script)
        self.assertIn('/ds/', script)
        self.assertIn('knotc -c "$CONF" reload', script)
        self.assertIn('conf-check', script)  # never reload a configuration that does not parse

    def test_the_firewall_agent_validates_before_applying_and_cleans_up(self) -> None:
        script = _read('firewall', 'entrypoint.sh')
        self.assertIn('nft -c -f', script)
        self.assertIn('delete table inet ifinmail', script)
        self.assertNotIn('flush ruleset', script)  # only our own table is ever touched

    def test_provisioning_detects_the_address_and_explains_delegation(self) -> None:
        provision = (ROOT / 'provisioning' / 'scripts' / 'provision.sh').read_text()
        self.assertIn('detect_public_ip', provision)
        self.assertIn('DNS_NS_HOSTS', provision)
        self.assertIn('127.0.0.53', provision)  # systemd-resolved holds port 53
        self.assertIn('glue', provision)

    def test_the_host_firewall_and_backups_cover_dns(self) -> None:
        firewall = (ROOT / 'provisioning' / 'scripts' / 'firewall.sh').read_text()
        self.assertIn('ufw allow 53/udp', firewall)
        self.assertIn('ufw allow 53/tcp', firewall)
        self.assertIn('25,53,80', firewall)
        backup = (ROOT / 'provisioning' / 'scripts' / 'backup_full.sh').read_text()
        self.assertIn('dns_data', backup)  # losing the DNSSEC keys breaks the DS record

    def test_the_certbot_image_has_the_tools_the_request_handler_uses(self) -> None:
        dockerfile = _read('certbot', 'Dockerfile')
        for tool in ('jq', 'openssl'):
            self.assertIn(tool, dockerfile)

    def test_zone_files_come_from_the_runtime_volume_the_console_writes(self) -> None:
        from backend.apps.dns.services.server import DEFAULT_CONTAINER_RUNTIME
        from backend.apps.dns.services.zones import GENERATED_CONF, ZONES_DIR

        script = _read('dns', 'entrypoint.sh')
        self.assertEqual(DEFAULT_CONTAINER_RUNTIME, '/runtime')
        self.assertIn(GENERATED_CONF.split('/')[-1], script)
        self.assertIn(ZONES_DIR.split('/')[-1], script)
