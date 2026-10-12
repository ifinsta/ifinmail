"""The rspamd.policy, dovecot.policy and postfix.tls_policy points and their five plugins."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from backend.apps.core.plugins.services import CatalogService, InstallationService, registry
from backend.apps.core.plugins.types import ConflictError, SettingsError
from backend.apps.core.tests.mail_base import MailTablesTestCase

ROOT = Path(__file__).resolve().parents[5]
DOCKER = ROOT / 'provisioning' / 'docker'


def point(key: str):
    return registry.get_point(key)


class PointGrammarTests(SimpleTestCase):
    def test_extension_lists_are_normalised_then_validated(self) -> None:
        p = point('rspamd.policy')
        self.assertEqual(
            p.normalize('blocked_attachment_types', ' EXE, .Js;iso  exe '), 'exe,iso,js'
        )
        self.assertIsNone(p.validate('blocked_attachment_types', 'exe,iso,js'))
        for bad in ('ex e', 'toolongextension', 'exe,../x', 'exe;rm'):
            with self.subTest(bad=bad):
                self.assertIsNotNone(p.validate('blocked_attachment_types', bad))
        self.assertIsNotNone(
            p.validate('blocked_attachment_types', ','.join(f'e{i}' for i in range(201)))
        )

    def test_choices(self) -> None:
        p = point('rspamd.policy')
        self.assertIsNone(p.validate('blocked_attachment_action', 'quarantine'))
        self.assertIsNotNone(p.validate('blocked_attachment_action', 'discard'))
        self.assertIsNone(p.validate('dmarc_enforcement', 'enforce'))
        self.assertIsNotNone(p.validate('dmarc_enforcement', 'reject'))
        self.assertIsNone(p.validate('dmarc_enforcement', ''))  # empty = removed

    def test_integers(self) -> None:
        p = point('dovecot.policy')
        for good in ('0', '20'):
            self.assertIsNone(p.validate('max_redirects', good))
        for bad in ('21', '-1', '1.5', 'x'):
            with self.subTest(bad=bad):
                self.assertIsNotNone(p.validate('max_redirects', bad))
        self.assertIsNone(p.validate('autoexpunge_junk_days', '3650'))
        self.assertIsNotNone(p.validate('autoexpunge_junk_days', '0'))
        self.assertIsNotNone(p.validate('autoexpunge_junk_days', '3651'))

    def test_domain_lists(self) -> None:
        p = point('postfix.tls_policy')
        self.assertEqual(
            p.normalize('domains', 'Law.Example., bank.example'), 'bank.example,law.example'
        )
        self.assertIsNone(p.validate('domains', 'bank.example,law.example'))
        for bad in (
            'localhost',
            'bank..example',
            '-bank.example',
            'bank.example;rm',
            'b ank.example',
        ):
            with self.subTest(bad=bad):
                self.assertIsNotNone(p.validate('domains', bad))
        self.assertIsNotNone(p.validate('level', 'may'))

    def test_line_breaks_never_survive_normalisation(self) -> None:
        p = point('rspamd.policy')
        value = p.normalize('blocked_attachment_types', 'exe\nrelayhost = evil')
        self.assertIsNotNone(p.validate('blocked_attachment_types', value))


class BundledPluginsTests(SimpleTestCase):
    def test_all_six_plugins_load(self) -> None:
        self.assertEqual(CatalogService.bundled_errors(), ())
        self.assertEqual(
            sorted(e.plugin_id for e in CatalogService.bundled()),
            [
                'attachment-guard',
                'compliance-journal',
                'dmarc-enforcement',
                'forwarding-control',
                'mailbox-cleanup',
                'partner-tls',
            ],
        )
        claimed = [k for e in CatalogService.bundled() for k in e.manifest.claimed_keys()]
        self.assertEqual(len(claimed), len(set(claimed)), 'two bundled plugins claim the same key')


class LifecycleTests(MailTablesTestCase):
    def file(self, name: str) -> dict[str, str]:
        path = Path(self.runtime_dir) / name
        if not path.exists():
            return {}
        out = {}
        for line in path.read_text().splitlines():
            if line and not line.startswith('#'):
                key, _, value = line.partition('=')
                out[key.strip()] = value.strip()
        return out

    def test_attachment_guard_and_dmarc_share_a_point(self) -> None:
        InstallationService.install(
            'attachment-guard', {'blocked_types': 'EXE, .js', 'action': 'quarantine'}, 'a'
        )
        InstallationService.install('dmarc-enforcement', {'mode': 'enforce'}, 'a')
        self.assertEqual(
            self.file('rspamd-plugins.conf'),
            {
                'blocked_attachment_action': 'quarantine',
                'blocked_attachment_types': 'exe,js',
                'dmarc_enforcement': 'enforce',
            },
        )
        InstallationService.disable('dmarc-enforcement', 'a')
        self.assertEqual(self.file('rspamd-plugins.conf')['dmarc_enforcement'], '')
        self.assertEqual(self.file('rspamd-plugins.conf')['blocked_attachment_types'], 'exe,js')

    def test_attachment_guard_defaults(self) -> None:
        InstallationService.install('attachment-guard', {}, 'a')
        types = self.file('rspamd-plugins.conf')['blocked_attachment_types'].split(',')
        self.assertIn('exe', types)
        self.assertIn('docm', types)
        self.assertNotIn('pdf', types)
        self.assertEqual(types, sorted(types))

    def test_bad_attachment_types_are_refused(self) -> None:
        with self.assertRaises(SettingsError):
            InstallationService.install('attachment-guard', {'blocked_types': 'exe, ../etc'}, 'a')

    def test_mailbox_cleanup_and_forwarding_control_share_a_point(self) -> None:
        InstallationService.install('mailbox-cleanup', {'trash_days': '7'}, 'a')
        InstallationService.install('forwarding-control', {}, 'a')
        self.assertEqual(
            self.file('dovecot-plugins.conf'),
            {
                'autoexpunge_junk_days': '30',
                'autoexpunge_sent_days': '',
                'autoexpunge_trash_days': '7',
                'max_redirects': '0',
            },
        )
        InstallationService.uninstall('mailbox-cleanup', 'a')
        self.assertEqual(self.file('dovecot-plugins.conf')['autoexpunge_trash_days'], '')
        self.assertEqual(self.file('dovecot-plugins.conf')['max_redirects'], '0')

    def test_partner_tls(self) -> None:
        with self.assertRaises(SettingsError):
            InstallationService.install('partner-tls', {}, 'a')  # domains required
        with self.assertRaises(SettingsError):
            InstallationService.install('partner-tls', {'domains': 'bank.example, localhost'}, 'a')
        InstallationService.install('partner-tls', {'domains': 'Law.Example, bank.example'}, 'a')
        self.assertEqual(
            self.file('postfix-tls-policy.conf'),
            {'domains': 'bank.example,law.example', 'level': 'encrypt'},
        )

    def test_the_new_plugins_never_conflict_with_each_other(self) -> None:
        for plugin_id, settings in (
            ('attachment-guard', {}),
            ('dmarc-enforcement', {}),
            ('forwarding-control', {}),
            ('mailbox-cleanup', {}),
            ('partner-tls', {'domains': 'bank.example'}),
        ):
            try:
                InstallationService.install(plugin_id, settings, 'a')
            except ConflictError as exc:  # pragma: no cover - the assertion below explains
                self.fail(f'{plugin_id}: {exc}')
        self.assertEqual(len(InstallationService.all()), 5)


def _bash_works() -> bool:
    return shutil.which('bash') is not None and shutil.which('sha256sum') is not None


class _ScriptHarness(SimpleTestCase):
    script: Path
    prefix: str

    def setUp(self) -> None:
        if not _bash_works():
            self.skipTest('needs bash and sha256sum')
        self.work = Path(tempfile.mkdtemp(prefix='ifinmail-watch-'))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.status = self.work / 'status'
        self.status.mkdir()
        self.file = self.work / 'plugins.conf'

    def run_script(self, check_ok: bool = True, reload_ok: bool = True) -> str:
        env = {
            **os.environ,
            f'IFINMAIL_{self.prefix}_PLUGINS_FILE': str(self.file),
            f'IFINMAIL_{self.prefix}_PLUGINS_STATE': str(self.work / 'state'),
            'IFINMAIL_STATUS_DIR': str(self.status),
            **self.extra_env(check_ok, reload_ok),
        }
        result = subprocess.run(
            ['bash', str(self.script), '--once'], env=env, capture_output=True, text=True
        )
        return result.stdout

    def ack(self) -> str:
        path = self.status / self.ack_name
        return path.read_text().strip() if path.exists() else ''

    def file_hash(self) -> str:
        return hashlib.sha256(self.file.read_bytes()).hexdigest()


class RspamdWatcherTests(_ScriptHarness):
    script = DOCKER / 'rspamd' / 'sync-plugins.sh'
    prefix = 'RSPAMD'
    ack_name = 'rspamd-plugins.applied'

    def extra_env(self, check_ok: bool, reload_ok: bool) -> dict[str, str]:
        self.out = self.work / 'out'
        return {
            'IFINMAIL_RSPAMD_OUT': str(self.out),
            'RSPAMADM_BIN': 'true' if check_ok else 'false',
            'RSPAMD_RELOAD': 'true' if reload_ok else 'false',
        }

    def test_renders_rules_and_acknowledges(self) -> None:
        self.file.write_text(
            'blocked_attachment_types = exe,js\nblocked_attachment_action = quarantine\n'
            'dmarc_enforcement = enforce\n'
        )
        self.run_script()
        self.assertEqual(
            (self.out / 'blocked_attachments.map').read_text(), '/\\.exe$/i\n/\\.js$/i\n'
        )
        rule = (self.out / 'multimap.conf').read_text()
        self.assertIn('action = "add header";', rule)
        self.assertIn('regexp = true;', rule)
        self.assertIn('reject = "reject";', (self.out / 'dmarc.conf').read_text())
        self.assertEqual(self.ack(), self.file_hash())

    def test_refuses_foreign_keys_and_unsafe_values(self) -> None:
        self.file.write_text(
            'relayhost = evil\nblocked_attachment_types = exe;$(id)\ndmarc_enforcement = reject\n'
        )
        log = self.run_script()
        self.assertIn('not on the allow-list: relayhost', log)
        self.assertEqual((self.out / 'multimap.conf').read_text(), '')
        self.assertEqual((self.out / 'dmarc.conf').read_text(), '')

    def test_failed_check_rolls_back_and_failed_reload_is_not_acknowledged(self) -> None:
        self.file.write_text('blocked_attachment_types = exe\n')
        self.run_script()
        good = (self.out / 'multimap.conf').read_text()
        self.file.write_text('blocked_attachment_types = exe,js\n')
        self.assertIn('configuration test failed', self.run_script(check_ok=False))
        self.assertEqual((self.out / 'multimap.conf').read_text(), good)
        self.assertNotEqual(self.ack(), self.file_hash())
        self.assertIn('reload failed', self.run_script(reload_ok=False))
        self.assertNotEqual(self.ack(), self.file_hash())
        self.run_script()
        self.assertEqual(self.ack(), self.file_hash())

    def test_empty_values_remove_the_rules(self) -> None:
        self.file.write_text('blocked_attachment_types = \ndmarc_enforcement = \n')
        self.run_script()
        self.assertEqual((self.out / 'multimap.conf').read_text(), '')
        self.assertEqual((self.out / 'dmarc.conf').read_text(), '')


class DovecotWatcherTests(_ScriptHarness):
    script = DOCKER / 'dovecot' / 'sync-plugins.sh'
    prefix = 'DOVECOT'
    ack_name = 'dovecot-plugins.applied'

    def extra_env(self, check_ok: bool, reload_ok: bool) -> dict[str, str]:
        self.out = self.work / 'ifinmail-plugins.conf'
        return {
            'IFINMAIL_DOVECOT_OUT': str(self.out),
            'DOVECONF_BIN': 'true' if check_ok else 'false',
            'DOVECOT_RELOAD': 'true' if reload_ok else 'false',
        }

    def test_renders_and_acknowledges(self) -> None:
        self.file.write_text(
            'max_redirects = 0\nautoexpunge_trash_days = 30\nautoexpunge_sent_days = \n'
        )
        self.run_script()
        text = self.out.read_text()
        self.assertIn('mailbox Trash {\n    autoexpunge = 30d\n  }', text)
        self.assertNotIn('Sent', text)
        self.assertIn('sieve_max_redirects = 0', text)
        self.assertEqual(self.ack(), self.file_hash())

    def test_refuses_foreign_keys_and_out_of_range(self) -> None:
        self.file.write_text(
            'sieve_before = /tmp/x\nautoexpunge_junk_days = 99999\nmax_redirects = 21\n'
        )
        log = self.run_script()
        self.assertIn('not on the allow-list: sieve_before', log)
        self.assertNotIn('autoexpunge', self.out.read_text())
        self.assertNotIn('sieve_max_redirects', self.out.read_text())

    def test_failed_check_rolls_back(self) -> None:
        self.file.write_text('max_redirects = 1\n')
        self.run_script()
        good = self.out.read_text()
        self.file.write_text('max_redirects = 5\n')
        self.run_script(check_ok=False)
        self.assertEqual(self.out.read_text().strip(), good.strip())
        self.assertNotEqual(self.ack(), self.file_hash())


class PostfixTlsWatcherTests(SimpleTestCase):
    script = DOCKER / 'postfix' / 'sync-overrides.sh'

    def setUp(self) -> None:
        if not _bash_works():
            self.skipTest('needs bash and sha256sum')
        self.work = Path(tempfile.mkdtemp(prefix='ifinmail-tls-'))
        self.addCleanup(shutil.rmtree, self.work, True)
        for name in ('postconf', 'postfix'):
            stub = self.work / name
            stub.write_text(f'#!/bin/sh\necho "{name} $*" >> "{self.work}/calls.log"\n')
            stub.chmod(0o755)
        (self.work / 'status').mkdir()
        self.file = self.work / 'tls.conf'
        self.map = self.work / 'policy'

    def run_script(self) -> list[str]:
        log = self.work / 'calls.log'
        log.unlink(missing_ok=True)
        env = {
            **os.environ,
            'IFINMAIL_OVERRIDES_FILE': str(self.work / 'none'),
            'IFINMAIL_PLUGINS_FILE': str(self.work / 'none'),
            'IFINMAIL_TLS_POLICY_FILE': str(self.file),
            'IFINMAIL_TLS_POLICY_STATE': str(self.work / 'state'),
            'IFINMAIL_TLS_POLICY_MAP': str(self.map),
            'IFINMAIL_STATUS_DIR': str(self.work / 'status'),
            'POSTCONF_BIN': str(self.work / 'postconf'),
            'POSTFIX_BIN': str(self.work / 'postfix'),
        }
        subprocess.run(
            ['bash', str(self.script), '--once'], env=env, check=True, capture_output=True
        )
        return log.read_text().splitlines() if log.exists() else []

    def test_map_policy_and_removal(self) -> None:
        self.file.write_text('domains = bank.example,law.example\nlevel = secure\n')
        self.assertEqual(
            self.run_script(),
            [f'postconf -e smtp_tls_policy_maps=texthash:{self.map}', 'postfix reload'],
        )
        self.assertEqual(self.map.read_text(), 'bank.example secure\nlaw.example secure\n')
        ack = (self.work / 'status' / 'postfix-tls-policy.applied').read_text().strip()
        self.assertEqual(ack, hashlib.sha256(self.file.read_bytes()).hexdigest())
        self.file.write_text('domains = \n')
        self.assertEqual(self.run_script(), ['postconf -X smtp_tls_policy_maps', 'postfix reload'])

    def test_unsafe_domains_and_foreign_keys_are_ignored(self) -> None:
        self.file.write_text('domains = bank.example;rm -rf /\nmynetworks = 0.0.0.0/0\n')
        self.assertEqual(self.run_script(), ['postconf -X smtp_tls_policy_maps', 'postfix reload'])
        self.assertEqual(self.map.read_text(), '')


class WiringContractTests(SimpleTestCase):
    def test_containers_see_plugin_files_and_acknowledge(self) -> None:
        import yaml

        services = yaml.safe_load((DOCKER / 'docker-compose.yml').read_text())['services']
        for name in ('rspamd', 'dovecot', 'postfix'):
            volumes = services[name]['volumes']
            self.assertIn('runtime_data:/var/lib/ifinmail/runtime:ro', volumes, name)
            self.assertIn('mail_status:/var/lib/ifinmail/status', volumes, name)

    def test_images_install_and_start_the_watchers_safely(self) -> None:
        rspamd_entry = (DOCKER / 'rspamd' / 'entrypoint.sh').read_text()
        # The first pass runs before exec: it must not signal PID 1 (still the shell).
        self.assertIn('RSPAMD_RELOAD=true /usr/local/bin/ifinmail-rspamd-sync --once', rspamd_entry)
        self.assertLess(
            rspamd_entry.index('ifinmail-rspamd-sync &'), rspamd_entry.index('exec rspamd')
        )
        self.assertIn('ifinmail-rspamd-sync', (DOCKER / 'rspamd' / 'Dockerfile').read_text())
        dovecot_entry = (DOCKER / 'dovecot' / 'entrypoint.sh').read_text()
        self.assertIn(
            'DOVECOT_RELOAD=true /usr/local/bin/ifinmail-dovecot-sync --once', dovecot_entry
        )
        self.assertIn('ifinmail-dovecot-sync', (DOCKER / 'dovecot' / 'Dockerfile').read_text())

    def test_configs_include_the_generated_fragments_optionally(self) -> None:
        for rel in ('rspamd/local.d/multimap.conf', 'rspamd/local.d/dmarc.conf'):
            self.assertIn('.include(try=true;', (DOCKER / rel).read_text(), rel)
        dovecot = (DOCKER / 'dovecot' / 'dovecot.conf').read_text()
        self.assertTrue(
            dovecot.rstrip().endswith('!include_try /etc/dovecot/ifinmail-plugins.conf'),
            'dovecot.conf must include the plugin file last so it overrides',
        )


class ApplyStatusTests(MailTablesTestCase):
    def test_every_point_reports_status(self) -> None:
        status_dir = Path(self.tmp) / 'status'
        status_dir.mkdir()
        with patch.dict(os.environ, {'IFINMAIL_STATUS_DIR': str(status_dir)}):
            InstallationService.install('dmarc-enforcement', {}, 'a')
            statuses = InstallationService.apply_status()
        self.assertEqual(
            sorted(statuses),
            ['dovecot.policy', 'postfix.main', 'postfix.tls_policy', 'rspamd.policy'],
        )
