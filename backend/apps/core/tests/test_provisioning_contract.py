"""Static guards for provisioning bugs that only show up when the real services run.

Each assertion below corresponds to a failure found by running Dovecot, Rspamd,
Postfix, nginx and PostgreSQL against the provisioning files; they cannot be hit
by Django's own tests, so the files are checked directly.
"""

from __future__ import annotations

import re
import shutil
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

    def test_new_mailboxes_get_the_1024_mb_default_at_the_schema_level(self) -> None:
        """The SQL default and the Python default must not drift apart."""
        from backend.apps.mail.types.quota import DEFAULT_QUOTA_BYTES

        self.assertIn(f'quota_bytes BIGINT DEFAULT {DEFAULT_QUOTA_BYTES}', _read('init-db.sh'))
        self.assertIn(
            f'ALTER COLUMN quota_bytes SET DEFAULT {DEFAULT_QUOTA_BYTES}',
            _read('db-upgrade.sql'),
        )


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

    def test_postfix_may_read_every_table_its_maps_query(self) -> None:
        init = _read('init-db.sh')
        for path in sorted((DOCKER / 'postfix' / 'pgsql').glob('*.cf')):
            for table in re.findall(r'FROM\s+(\w+)', path.read_text()):
                self.assertIn(f'GRANT SELECT ON {table} TO postfix;', init, msg=path.name)


class OutboundPolicyWiringTests(SimpleTestCase):
    def test_submission_services_take_their_recipient_limit_from_one_parameter(self) -> None:
        master = _read('postfix', 'master.cf')
        self.assertEqual(
            master.count('-o smtpd_recipient_limit=$ifinmail_recipient_limit'), 2
        )  # submission and smtps, never port 25
        main = _read('postfix', 'main.cf')
        self.assertRegex(main, r'(?m)^ifinmail_recipient_limit = \d+\r?$')
        script = _read('postfix', 'sync-overrides.sh')
        self.assertIn('ifinmail_recipient_limit', script)

    def test_rspamd_counters_use_the_keys_the_console_reads(self) -> None:
        from backend.apps.mail.services import containment

        lua = _read('rspamd', 'rspamd.local.lua')
        self.assertIn(f"'{containment.KEY_PREFIX}'", lua)
        for suffix in (':m', ':r', ':d'):
            self.assertIn(f"base .. '{suffix}'", lua)
        # One atomic script, and every key gets the same one-hour expiry the console expects.
        self.assertIn("'EVAL'", lua)
        self.assertIn("WINDOW = '3600'", lua)
        self.assertIn("redis.call('EXPIRE'", lua)
        # Only for logged-in users, and only hashes of recipients are kept.
        self.assertIn('task:get_user()', lua)
        self.assertIn('hash.create(', lua)

    def test_the_containment_job_is_scheduled_every_minute(self) -> None:
        from django.conf import settings

        entry = settings.CELERY_BEAT_SCHEDULE['outbound-containment']
        self.assertEqual(entry['task'], 'mail.check_outbound_containment')
        self.assertEqual(entry['schedule'].minute, set(range(60)))


class PostgresConfigContractTests(SimpleTestCase):
    def test_the_tuning_file_is_the_servers_main_configuration(self) -> None:
        # Regression: the file used to be mounted but never read (an include appended to the
        # wrong file), so the server ran on defaults for months.
        import yaml

        postgres = yaml.safe_load(_read('docker-compose.yml'))['services']['postgres']
        self.assertEqual(
            postgres['command'], ['postgres', '-c', 'config_file=/etc/postgresql/custom.conf']
        )
        self.assertIn('./postgres/custom.conf:/etc/postgresql/custom.conf:ro', postgres['volumes'])

    def test_the_file_repeats_what_the_image_would_have_set(self) -> None:
        settings = dict(
            re.findall(
                r"^([a-z_]+)\s*=\s*'?([^'#\n]*?)'?\s*(?:#.*)?$",
                _read('postgres', 'custom.conf'),
                re.M,
            )
        )
        # As the main file it replaces the image's, which is where listen_addresses came from.
        self.assertEqual(settings.get('listen_addresses'), '*')
        # Connection and statement logging stay off: one line per console request drowns the log.
        self.assertEqual(settings.get('log_connections'), 'off')
        self.assertEqual(settings.get('log_disconnections'), 'off')
        self.assertEqual(settings.get('log_min_messages'), 'warning')
        # More than the console, worker and mail services can use at once, and no more.
        self.assertLessEqual(int(settings['max_connections']), 100)
        self.assertGreaterEqual(int(settings['max_connections']), 30)


class SenderIdentityContractTests(SimpleTestCase):
    """A logged-in user may send only as their own address or an alias that delivers to them."""

    def test_the_submission_ports_reject_a_sender_the_login_does_not_own(self) -> None:
        master = _read('postfix', 'master.cf')
        self.assertEqual(
            master.count('-o smtpd_sender_restrictions=reject_sender_login_mismatch'), 2
        )
        self.assertIn(
            'smtpd_sender_login_maps = pgsql:/etc/postfix/pgsql/sender_logins.cf',
            _read('postfix', 'main.cf'),
        )

    def test_owners_come_from_hosted_domains_and_aliases_never_from_users(self) -> None:
        query = _read('postfix', 'pgsql', 'sender_logins.cf')
        self.assertIn("FROM domains WHERE name = '%d'", query)
        self.assertIn("SELECT destination FROM aliases WHERE source = '%s'", query)
        self.assertNotIn('users', query.split('query =')[1])  # password hashes stay unreadable

    def test_rspamd_requires_the_from_header_to_match_for_logged_in_senders(self) -> None:
        self.assertIn(
            'COPY rspamd.local.lua /etc/rspamd/rspamd.local.lua', _read('rspamd', 'Dockerfile')
        )
        rule = _read('rspamd', 'rspamd.local.lua')
        self.assertIn('if not task:get_user() then', rule)
        self.assertIn("task:set_pre_result('reject'", rule)


class ContainerContractTests(SimpleTestCase):
    def test_compose_runs_the_background_jobs_and_shares_the_runtime_volume(self) -> None:
        compose = _read('docker-compose.yml')
        self.assertIn('  worker:', compose)
        # One server, one scheduler: beat runs inside the worker, not in its own container.
        self.assertIn('celery", "-A", "backend.config.celery", "worker", "--beat"', compose)
        self.assertNotIn('  beat:', compose)
        self.assertIn('runtime_data:/var/lib/ifinmail/runtime:ro', compose)  # postfix reads
        self.assertIn('runtime_data:/runtime ', compose)  # certbot reads and reports back (rw)
        self.assertNotIn('runtime_data:/runtime:ro', compose)
        self.assertNotIn('profiles:', compose.split('  certbot:')[1].split('  # ---')[0])

    def test_the_worker_sees_what_system_health_reads(self) -> None:
        # The assistant runs System health in the worker: same status files and hints as the api.
        import yaml

        services = yaml.safe_load(_read('docker-compose.yml'))['services']
        api, worker = services['api'], services['worker']
        self.assertIn('mail_status:/var/lib/ifinmail/status:ro', worker['volumes'])
        for key in ('IFINMAIL_INSTALL_DIR', 'DNS_SERVER_ENABLED', 'DAV_ENABLED', 'MAIL_HOSTNAME'):
            self.assertIn(key, api['environment'], key)
            self.assertIn(key, worker['environment'], key)

    def test_no_container_can_control_docker(self) -> None:
        # The Docker socket is root on the host; renewals are picked up by watching the file.
        compose = _read('docker-compose.yml')
        self.assertNotIn('docker.sock', compose)
        self.assertNotIn('  telemetry:', compose)
        self.assertNotIn('docker', _read('certbot', 'deploy-hook.sh').split('set -e', 1)[1])
        self.assertNotIn('docker-cli', _read('certbot', 'Dockerfile'))

    def test_services_reload_a_renewed_certificate_themselves(self) -> None:
        compose = _read('docker-compose.yml')
        live = '/etc/letsencrypt/live/${MAIL_HOSTNAME}/fullchain.pem'
        self.assertIn(f'sh /cert-watch.sh {live} nginx -s reload', compose)
        self.assertIn('./nginx/cert-watch.sh:/cert-watch.sh:ro', compose)
        for script in (('postfix', 'sync-overrides.sh'), ('dovecot', 'sync-plugins.sh')):
            text = _read(*script)
            self.assertIn('watch_certificate()', text, script)
            self.assertIn('    watch_certificate\n', text, script)

    def test_dns_and_dav_are_optional_profiles_set_by_provisioning(self) -> None:
        compose = _read('docker-compose.yml')
        self.assertIn('profiles: [dns]', compose.split('  dns:')[1].split('\n\n')[0])
        self.assertIn('profiles: [dav]', compose.split('  dav:')[1].split('\n\n')[0])
        provision = (ROOT / 'provisioning' / 'scripts' / 'provision.sh').read_text()
        self.assertIn('ensure_profiles   # before the build', provision)
        self.assertIn('up -d --remove-orphans', provision)
        self.assertLess(
            provision.index('ensure_profiles   # before'), provision.index('build --pull')
        )
        makefile = (ROOT / 'Makefile').read_text()
        self.assertIn("$(DOCKER_COMPOSE) --profile '*' down", makefile)

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


def _shell_works(exe: str | None) -> bool:
    """True only for a working shell (WSL's bash stub counts as missing)."""
    if not exe:
        return False
    try:
        result = subprocess.run([exe, '--version'], capture_output=True, text=True, timeout=10)
        return result.returncode == 0 and 'GNU' in (result.stdout + result.stderr)
    except Exception:
        return False


_BASH_WORKS = _shell_works(shutil.which('bash'))
_SH_WORKS = _shell_works(shutil.which('sh'))


@pytest.mark.skipif(not _BASH_WORKS, reason='needs working bash')
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

    @pytest.mark.skipif(not _SH_WORKS, reason='needs working sh')
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

    def test_branding_uploads_are_mounted_and_served(self) -> None:
        """The console writes logo/favicon uploads to MEDIA_ROOT (/app/media); nginx
        must serve that volume or the branding images 404 in production."""
        compose = self._compose()
        self.assertIn('media_data:/app/media', compose['services']['api']['volumes'])
        self.assertIn('media_data:/app/media:ro', compose['services']['nginx']['volumes'])
        self.assertIn('media_data', compose['volumes'])
        nginx = _read('nginx', 'conf.d', 'ifinmail.conf')
        self.assertIn('location /media/', nginx)
        self.assertIn('alias /app/media/', nginx)


class Pop3ContractTests(SimpleTestCase):
    """Clients (and the autoconfig XML) offer POP3, so the stack has to serve it."""

    def test_dovecot_serves_pop3_on_110_and_995_with_the_same_tls_rules_as_imap(self) -> None:
        self.assertIn('protocols = imap pop3 lmtp', _read('dovecot', 'dovecot.conf'))
        master = _read('dovecot', 'conf.d', '10-master.conf')
        block = master.split('service pop3-login')[1].split('\n}')[0]
        self.assertRegex(block, r'inet_listener pop3 \{\s+port = 110')
        self.assertRegex(block, r'inet_listener pop3s \{\s+port = 995\s+ssl = yes')
        self.assertIn('disable_plaintext_auth = yes', _read('dovecot', 'conf.d', '10-auth.conf'))
        self.assertIn('dovecot-pop3d', _read('dovecot', 'Dockerfile'))

    def test_uidl_is_stable_so_clients_do_not_download_mail_twice(self) -> None:
        self.assertIn('pop3_uidl_format = %08Xu%08Xv', _read('dovecot', 'conf.d', '20-pop3.conf'))

    def test_the_ports_are_published_and_opened(self) -> None:
        import yaml

        ports = yaml.safe_load(_read('docker-compose.yml'))['services']['dovecot']['ports']
        self.assertTrue({'110:110', '995:995'} <= set(ports))
        firewall = (ROOT / 'provisioning' / 'scripts' / 'firewall.sh').read_text()
        self.assertIn('ufw allow 995/tcp', firewall)
        self.assertIn('110,143', firewall)

    def test_the_console_can_close_them(self) -> None:
        from backend.apps.core.platform.services.entrypoints import BY_KEY

        for key, port in (('pop3', 110), ('pop3s', 995)):
            self.assertEqual(BY_KEY[key].ports[0][1], port)
            self.assertFalse(BY_KEY[key].locked)


class DavContractTests(SimpleTestCase):
    """Calendars and contacts: Radicale behind nginx, signing in with the mailbox password."""

    def test_the_dav_container_is_internal_and_checks_passwords_with_dovecot(self) -> None:
        import yaml

        compose = yaml.safe_load(_read('docker-compose.yml'))
        dav = compose['services']['dav']
        self.assertNotIn('ports', dav)  # reachable only through nginx
        self.assertIn('rundir:/var/run/dovecot', dav['volumes'])  # Dovecot's auth socket
        self.assertIn('dav_data', compose['volumes'])
        config = _read('dav', 'config')
        self.assertRegex(config, r'(?m)^type = dovecot$')
        self.assertIn('dovecot_socket = /var/run/dovecot/auth', config)
        self.assertRegex(config, r'(?m)^type = owner_only$')  # people see only their own data
        self.assertIn('radicale==', _read('dav', 'Dockerfile'))  # pinned

    def test_the_socket_radicale_uses_is_the_one_dovecot_creates(self) -> None:
        master = _read('dovecot', 'conf.d', '10-master.conf')
        self.assertIn('unix_listener auth {', master)
        self.assertIn('/var/run/dovecot', _read('dovecot', 'dovecot.conf'))

    def test_nginx_serves_dav_and_the_rfc_6764_well_known_paths(self) -> None:
        conf = _read('nginx', 'conf.d', 'ifinmail.conf')
        for line in (
            'location = /.well-known/caldav',
            'location = /.well-known/carddav',
            'location /dav/',
            'proxy_set_header X-Script-Name /dav;',
            'proxy_pass_header Authorization;',
        ):
            self.assertIn(line, conf)
        # Resolved per request: nginx must still start when the dav container is down.
        self.assertIn('set $dav_upstream http://dav:5232;', conf)
        self.assertIn('proxy_pass $dav_upstream;', conf)

    def test_the_dav_service_is_backed_up(self) -> None:
        backup = (ROOT / 'provisioning' / 'scripts' / 'backup_full.sh').read_text()
        self.assertIn('dav_data', backup)


class PostfixDovecotHandoffContractTests(SimpleTestCase):
    """Found by running Postfix and Dovecot together: mail clients could not send, and inbound
    mail was never delivered, because of two lines of configuration."""

    def _master_rows(self) -> dict[str, list[str]]:
        rows: dict[str, list[str]] = {}
        for line in _read('postfix', 'master.cf').splitlines():
            parts = line.split()
            if len(parts) >= 8 and not line.startswith(('#', ' ')):
                rows[f'{parts[0]}/{parts[1]}'] = parts
        return rows

    def test_services_that_use_dovecots_sockets_are_not_chrooted(self) -> None:
        """smtpd (SASL) and lmtp reach Dovecot at /var/run/dovecot; inside the postfix chroot
        that path does not exist, so SASL ("no SASL authentication mechanisms") and delivery
        fail."""
        rows = self._master_rows()
        for service in ('smtp/inet', 'submission/inet', 'smtps/inet', 'lmtp/unix'):
            self.assertIn(service, rows)
            self.assertEqual(rows[service][4], 'n', msg=f'{service} must have chroot = n')

    def test_the_sockets_are_the_ones_dovecot_creates(self) -> None:
        main = _read('postfix', 'main.cf')
        self.assertIn('smtpd_sasl_path = /var/run/dovecot/auth', main)
        self.assertIn('virtual_transport = lmtp:unix:/var/run/dovecot/lmtp', main)
        master = _read('dovecot', 'conf.d', '10-master.conf')
        self.assertIn('unix_listener auth', master)
        self.assertIn('unix_listener lmtp', master)

    def test_the_domain_list_is_not_used_as_a_transport_table(self) -> None:
        """transport_maps must return "transport:nexthop"; virtual_domains.cf returns the domain
        name, which Postfix then tried to use as a transport ("private/example.test"), deferring
        every inbound message."""
        main = _read('postfix', 'main.cf')
        self.assertNotRegex(main, r'(?m)^transport_maps\s*=.*virtual_domains')

    def test_submission_and_smtps_require_tls_and_authentication(self) -> None:
        master = _read('postfix', 'master.cf')
        for service in ('submission inet', 'smtps     inet'):
            block = master.split(service)[1].split('\n\n')[0]
            self.assertIn('permit_sasl_authenticated,reject', block)
        self.assertIn(
            'smtpd_tls_security_level=encrypt', master.split('submission inet')[1].split('smtps')[0]
        )
        self.assertIn('smtpd_tls_wrappermode=yes', master.split('smtps     inet')[1])

    def test_the_console_sends_system_email_through_an_internal_only_relay(self) -> None:
        """Without EMAIL_HOST the app tried localhost:25 inside its own container, so every
        setup-link and verification email failed. The relay it uses instead must stay off the
        published ports and accept only the Docker network, or the server is an open relay."""
        import yaml

        compose = yaml.safe_load(_read('docker-compose.yml'))['services']
        for service in ('api', 'worker'):
            env = compose[service]['environment']
            self.assertEqual(env['EMAIL_HOST'], '${EMAIL_HOST:-postfix}')
            self.assertEqual(env['EMAIL_PORT'], '${EMAIL_PORT:-10025}')
        self.assertFalse(any('10025' in str(p) for p in compose['postfix']['ports']))
        block = _read('postfix', 'master.cf').split('10025     inet')[1].split('\n\n')[0]
        for restriction in ('client', 'relay', 'recipient'):
            self.assertIn(f'smtpd_{restriction}_restrictions=permit_mynetworks,reject', block)
        self.assertIn('postconf -P "10025/inet/mynetworks=', _read('postfix', 'entrypoint.sh'))
        self.assertIn('iproute2', _read('postfix', 'Dockerfile'))


class SelfSignedFirstBootContractTests(SimpleTestCase):
    """Mail apps connect before Let's Encrypt has issued anything. They only accept the temporary
    certificate after the person confirms its fingerprint, and still check the host name, so the
    certificate must name the mail host and the fingerprint must be shown to the administrator."""

    def setUp(self) -> None:
        self.provision = (ROOT / 'provisioning' / 'scripts' / 'provision.sh').read_text()

    def test_the_bootstrap_certificate_names_the_mail_host(self) -> None:
        block = self.provision.split('ensure_bootstrap_cert()')[1].split('ensure_mta_sts')[0]
        self.assertIn('DNS:$MAIL_HOSTNAME', block)
        self.assertIn('-x509', block)

    def test_provisioning_prints_the_fingerprint_of_a_temporary_certificate(self) -> None:
        block = self.provision.split('print_dns()')[1]
        self.assertIn('-fingerprint -sha256', block)
        self.assertIn('mail apps will ask you to trust it once', block)

    def test_the_client_docs_describe_the_first_connect_prompt(self) -> None:
        self.assertIn('fingerprint', (ROOT / 'clients' / 'README.md').read_text().lower())


class OutboundContainmentContractTests(SimpleTestCase):
    def test_authenticated_senders_are_rate_limited(self) -> None:
        """One stolen mailbox password must not be able to burn the server's IP reputation."""
        conf = _read('rspamd', 'local.d', 'ratelimit.conf')
        self.assertRegex(conf, r'selector = "user";')
        self.assertRegex(conf, r'rate = "\d+ / 1h";')
        self.assertIn('rcpt_domain', conf)
        # The username only reaches Rspamd when Postfix passes the SASL login to the milter.
        self.assertIn('{auth_authen}', _read('postfix', 'main.cf'))


class HealthcheckContractTests(SimpleTestCase):
    """Every container reports whether it is doing its job; nothing is "up" without evidence."""

    def _services(self) -> dict:
        import yaml

        return yaml.safe_load(_read('docker-compose.yml'))['services']

    def test_every_service_has_a_healthcheck(self) -> None:
        missing = [
            name for name, service in self._services().items() if not service.get('healthcheck')
        ]
        self.assertEqual(missing, [], 'every service needs a healthcheck: ' + ', '.join(missing))

    def test_no_healthcheck_is_disabled_or_trivial(self) -> None:
        for name, service in self._services().items():
            check = service['healthcheck']
            with self.subTest(service=name):
                self.assertFalse(check.get('disable'), 'a disabled healthcheck is no check')
                test = check.get('test')
                self.assertTrue(test, 'the check must run something')
                command = ' '.join(test) if isinstance(test, list) else str(test)
                for trivial in ('exit 0', ' true', 'echo ok'):
                    self.assertNotIn(trivial, command)
                self.assertTrue(check.get('interval'), 'an interval must be set')

    def test_the_firewall_check_reads_the_agents_heartbeat_and_the_kernel_table(self) -> None:
        script = _read('firewall', 'healthcheck.sh')
        for needle in ('firewall-status.json', 'nft list table inet ifinmail', 'rejected'):
            self.assertIn(needle, script)
        self.assertIn('healthcheck.sh', _read('firewall', 'Dockerfile'))
        shell = shutil.which('sh')
        if shell:
            result = subprocess.run(
                [shell, '-n', str(DOCKER / 'firewall' / 'healthcheck.sh')],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


class MailLogContractTests(SimpleTestCase):
    """The threat digest reads Postfix and Dovecot logs from a shared volume (read-only)."""

    def test_the_console_reads_the_same_volume_the_mail_services_write(self) -> None:
        compose = _read('docker-compose.yml')
        self.assertRegex(compose, r'(?m)^  mail_logs:')
        self.assertEqual(compose.count('mail_logs:/var/log/ifinmail\n'), 0)  # never bare
        writers = compose.count('- mail_logs:/var/log/ifinmail ')
        self.assertGreaterEqual(writers, 2)  # postfix and dovecot
        self.assertIn('mail_logs:/var/log/ifinmail-mail:ro', compose)  # worker, read-only

    def test_each_service_logs_to_the_file_and_still_to_the_container_output(self) -> None:
        postfix = _read('postfix', 'entrypoint.sh')
        self.assertIn('maillog_file=$MAIL_LOG', postfix)
        self.assertIn('tail -n 0 -F "$MAIL_LOG"', postfix)
        self.assertIn('maillog_file=/dev/stdout', postfix)  # the fallback without the volume
        dovecot = _read('dovecot', 'entrypoint.sh')
        self.assertIn('/etc/dovecot/ifinmail-log.conf', dovecot)
        self.assertIn('tail -n 0 -F "$MAIL_LOG"', dovecot)
        conf = _read('dovecot', 'dovecot.conf')
        self.assertIn('!include_try /etc/dovecot/ifinmail-log.conf', conf)

    def test_the_logs_are_rotated_and_stay_readable_by_the_console(self) -> None:
        reopeners = (('postfix', 'pkill -x postlogd'), ('dovecot', 'doveadm log reopen'))
        for service, reopen in reopeners:
            script = _read(service, 'log-rotate.sh')
            self.assertIn(reopen, script)
            self.assertIn('chmod 0644', script)  # a fresh file would otherwise be root-only
            self.assertIn('ifinmail-log-rotate', _read(service, 'Dockerfile'))

    def test_scanner_hosts_do_not_flood_the_log_with_tracebacks(self) -> None:
        production = (ROOT / 'backend' / 'config' / 'settings' / 'production.py').read_text()
        self.assertRegex(
            production,
            r"'django\.security\.DisallowedHost': \{[^}]*'level': 'CRITICAL'"
            r"[^}]*'propagate': False",
        )
