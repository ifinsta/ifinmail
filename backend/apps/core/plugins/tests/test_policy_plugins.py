"""The rspamd.policy, dovecot.policy, postfix.tls_policy and postfix.sender_policy points and the
plugins built on them."""

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
from backend.apps.mail.models import Mailbox

ROOT = Path(__file__).resolve().parents[5]
DOCKER = ROOT / 'provisioning' / 'docker'


def point(key: str):
    return registry.get_target(key)


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

    def test_arc_keys(self) -> None:
        p = point('rspamd.policy')
        self.assertEqual(
            p.normalize('arc_trusted_sealers', 'Google.com, microsoft.com.'),
            'google.com,microsoft.com',
        )
        self.assertIsNone(p.validate('arc_trusted_sealers', 'google.com,microsoft.com'))
        self.assertIsNotNone(p.validate('arc_trusted_sealers', 'google.com;evil'))
        self.assertIsNone(p.validate('arc_sealing', 'yes'))
        self.assertIsNone(p.validate('arc_sealing', 'no'))
        self.assertIsNotNone(p.validate('arc_sealing', 'true'))

    def test_sender_lists_take_addresses_and_domains(self) -> None:
        p = point('rspamd.policy')
        self.assertEqual(
            p.normalize('sender_block_list', 'Spam.Example., Bob@Bad.Example'),
            'bob@bad.example,spam.example',
        )
        for key in ('sender_block_list', 'sender_allow_list'):
            self.assertIsNone(p.validate(key, 'bob@bad.example,spam.example'))
            for bad in ('localhost', '@bad.example', 'a b@x.example', 'x.example;rm', '*.example'):
                with self.subTest(key=key, bad=bad):
                    self.assertIsNotNone(p.validate(key, bad))
        self.assertIsNotNone(
            p.validate('sender_block_list', ','.join(f'd{i}.example' for i in range(201)))
        )

    def test_mail_policy_switches_and_limits(self) -> None:
        p = point('rspamd.policy')
        self.assertIsNone(p.validate('greylisting', 'off'))
        self.assertIsNotNone(p.validate('greylisting', 'no'))
        self.assertIsNone(p.validate('send_limit_per_minute', '1000'))
        self.assertIsNotNone(p.validate('send_limit_per_minute', '1001'))
        self.assertIsNone(p.validate('send_limit_per_day', '100000'))
        self.assertIsNotNone(p.validate('send_limit_per_day', '0'))
        size = point('postfix.main')
        self.assertIsNone(size.validate('message_size_limit_mb', '50'))
        for bad in ('0', '51', '25MB'):
            with self.subTest(bad=bad):
                self.assertIsNotNone(size.validate('message_size_limit_mb', bad))
        self.assertIsNone(point('dovecot.policy').validate('quota_warnings', 'yes'))
        self.assertIsNotNone(point('dovecot.policy').validate('quota_warnings', 'true'))

    def test_internal_only_logins_must_be_addresses(self) -> None:
        p = point('postfix.sender_policy')
        self.assertEqual(
            p.normalize('internal_only_logins', 'Intern@X.Example, desk@x.example'),
            'desk@x.example,intern@x.example',
        )
        self.assertIsNone(p.validate('internal_only_logins', 'desk@x.example'))
        for bad in ('x.example', 'desk@x.example permit', 'desk@localhost'):
            with self.subTest(bad=bad):
                self.assertIsNotNone(p.validate('internal_only_logins', bad))

    def test_line_breaks_never_survive_normalisation(self) -> None:
        p = point('rspamd.policy')
        value = p.normalize('blocked_attachment_types', 'exe\nrelayhost = evil')
        self.assertIsNotNone(p.validate('blocked_attachment_types', value))


class CapabilityContractTests(SimpleTestCase):
    """Plugins speak capabilities; only the adapter knows the mail software."""

    ENGINE_WORDS = ('postfix', 'dovecot', 'rspamd', 'sieve', 'milter', 'main.cf', 'postconf')

    def test_bundled_manifests_never_name_the_mail_software(self) -> None:
        engine_keys = {key for t in registry.targets() for key in t.keys}
        for entry in CatalogService.bundled():
            text = entry.manifest.text.lower()
            with self.subTest(plugin=entry.plugin_id):
                for word in self.ENGINE_WORDS:
                    self.assertNotIn(word, text)
                for contribution in entry.manifest.contributes:
                    self.assertIsNotNone(registry.get_capability(contribution.capability))
                    for key, _ in contribution.values:
                        self.assertNotIn(key, engine_keys - {'domains', 'max_redirects'})

    def test_capabilities_describe_outcomes_not_software(self) -> None:
        for capability in registry.capabilities():
            words = ' '.join(
                [capability.key, capability.title, capability.description]
                + [f'{name} {f.description}' for name, f in capability.fields.items()]
            ).lower()
            with self.subTest(capability=capability.key):
                for word in self.ENGINE_WORDS:
                    self.assertNotIn(word, words)

    def test_every_field_is_bound_to_its_own_existing_target_key(self) -> None:
        seen = set()
        for capability in registry.capabilities():
            for name, spec in capability.fields.items():
                target = registry.get_target(spec.target[0])
                self.assertIsNotNone(target, f'{capability.key}.{name}')
                self.assertIn(spec.target[1], target.keys, f'{capability.key}.{name}')
                self.assertNotIn(spec.target, seen, f'{capability.key}.{name} shares a target')
                seen.add(spec.target)

    def test_registration_refuses_unknown_or_shared_bindings(self) -> None:
        from backend.apps.core.plugins.services.registry import Capability, CapabilityField

        def capability(target: tuple[str, str]) -> Capability:
            cap = Capability()
            cap.key, cap.title, cap.description = 'test.x', 'X', 'X'
            cap.fields = {'v': CapabilityField(lambda v: None, 'x', target)}
            return cap

        with self.assertRaisesMessage(ValueError, 'unknown target'):
            registry.register_capability(capability(('postfix.main', 'relayhost')))
        with self.assertRaisesMessage(ValueError, 'share a target'):
            registry.register_capability(capability(('postfix.main', 'always_bcc')))
        self.assertIsNone(registry.get_capability('test.x'))

    def test_values_are_translated_for_the_engine(self) -> None:
        self.assertEqual(
            registry.to_targets(
                {
                    'delivery.require_tls': {
                        'domains': 'bank.example',
                        'verify_certificate': 'yes',
                    },
                    'inbound.greylisting': {'enabled': 'no'},
                    'mail.journal': {'archive_address': 'j@x.example'},
                }
            ),
            {
                'postfix.tls_policy': {'domains': 'bank.example', 'level': 'secure'},
                'rspamd.policy': {'greylisting': 'off'},
                'postfix.main': {'always_bcc': 'j@x.example'},
            },
        )
        # Empty means "remove the setting" on both sides.
        self.assertEqual(
            registry.to_targets({'inbound.greylisting': {'enabled': ''}}),
            {'rspamd.policy': {'greylisting': ''}},
        )

    def test_contract_grammar_is_checked_before_the_engine_sees_anything(self) -> None:
        cap = registry.get_capability('inbound.greylisting')
        self.assertIsNotNone(cap.validate('enabled', 'off'))  # engine word, not the contract's
        self.assertIsNone(cap.validate('enabled', 'no'))
        self.assertIsNotNone(cap.validate('nope', 'yes'))
        tls = registry.get_capability('delivery.require_tls')
        self.assertIsNotNone(tls.validate('verify_certificate', 'secure'))

    def test_each_plugin_reports_the_targets_it_uses(self) -> None:
        bundled = {e.plugin_id: e.manifest for e in CatalogService.bundled()}
        journal = bundled['compliance-journal']
        self.assertEqual(
            [t.key for t in registry.targets_of(journal.capability_keys())], ['postfix.main']
        )
        policy = bundled['mail-policy']
        self.assertEqual(
            {t.service for t in registry.targets_of(policy.capability_keys())},
            {'postfix', 'rspamd', 'dovecot'},
        )


class BundledPluginsTests(SimpleTestCase):
    def test_all_bundled_plugins_load(self) -> None:
        self.assertEqual(CatalogService.bundled_errors(), ())
        self.assertEqual(
            sorted(e.plugin_id for e in CatalogService.bundled()),
            [
                'arc-forwarding',
                'attachment-guard',
                'compliance-journal',
                'dmarc-enforcement',
                'forwarding-control',
                'mail-policy',
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
                'arc_sealing': '',
                'arc_trusted_sealers': '',
                'blocked_attachment_action': 'quarantine',
                'blocked_attachment_types': 'exe,js',
                'dmarc_enforcement': 'enforce',
                'greylisting': '',
                'send_limit_per_day': '',
                'send_limit_per_minute': '',
                'sender_allow_list': '',
                'sender_block_list': '',
            },
        )
        InstallationService.disable('dmarc-enforcement', 'a')
        self.assertEqual(self.file('rspamd-plugins.conf')['dmarc_enforcement'], '')
        self.assertEqual(self.file('rspamd-plugins.conf')['blocked_attachment_types'], 'exe,js')

    def test_arc_forwarding_defaults_and_switches(self) -> None:
        InstallationService.install('arc-forwarding', {}, 'a')
        values = self.file('rspamd-plugins.conf')
        self.assertEqual(values['arc_trusted_sealers'], 'google.com,microsoft.com,yahoo.com')
        self.assertEqual(values['arc_sealing'], 'yes')
        # A partial change keeps the other values; an empty checkbox value means off.
        InstallationService.configure('arc-forwarding', {'trusted_sealers': ''}, 'a')
        values = self.file('rspamd-plugins.conf')
        self.assertEqual((values['arc_trusted_sealers'], values['arc_sealing']), ('', 'yes'))
        InstallationService.configure('arc-forwarding', {'seal_forwarded': ''}, 'a')
        self.assertEqual(self.file('rspamd-plugins.conf')['arc_sealing'], 'no')

    def test_arc_and_dmarc_enforcement_work_together(self) -> None:
        InstallationService.install('dmarc-enforcement', {}, 'a')
        InstallationService.install('arc-forwarding', {'seal_forwarded': 'on'}, 'a')
        values = self.file('rspamd-plugins.conf')
        self.assertEqual(values['dmarc_enforcement'], 'enforce')
        self.assertEqual(values['arc_sealing'], 'yes')

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
                'quota_warnings': '',
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

    def test_mail_policy_defaults_follow_the_large_providers(self) -> None:
        InstallationService.install('mail-policy', {}, 'a')
        self.assertEqual(
            {k: v for k, v in self.file('rspamd-plugins.conf').items() if v},
            {'greylisting': 'on', 'send_limit_per_day': '2000', 'send_limit_per_minute': '30'},
        )
        self.assertEqual(self.file('postfix-plugins.conf')['message_size_limit_mb'], '50')
        self.assertEqual(self.file('postfix-sender-policy.conf'), {'internal_only_logins': ''})
        self.assertEqual(self.file('dovecot-plugins.conf')['quota_warnings'], 'yes')

    def test_mail_policy_lists_and_switches(self) -> None:
        InstallationService.install(
            'mail-policy',
            {
                'block_senders': 'Spam.Example, bob@bad.example',
                'allow_senders': 'partner.example',
                'internal_only': 'Intern@ifinmail.test',
                'greylisting': 'off',
                'quota_warnings': '',
            },
            'a',
        )
        values = self.file('rspamd-plugins.conf')
        self.assertEqual(values['sender_block_list'], 'bob@bad.example,spam.example')
        self.assertEqual(values['sender_allow_list'], 'partner.example')
        self.assertEqual(values['greylisting'], 'off')
        self.assertEqual(
            self.file('postfix-sender-policy.conf')['internal_only_logins'], 'intern@ifinmail.test'
        )
        self.assertEqual(self.file('dovecot-plugins.conf')['quota_warnings'], 'no')
        with self.assertRaises(SettingsError):
            InstallationService.configure('mail-policy', {'message_size_mb': '150'}, 'a')
        with self.assertRaises(SettingsError):
            InstallationService.configure('mail-policy', {'block_senders': 'evil;rm'}, 'a')
        InstallationService.uninstall('mail-policy', 'a')
        self.assertEqual(self.file('postfix-plugins.conf')['message_size_limit_mb'], '')
        self.assertEqual(self.file('postfix-sender-policy.conf'), {'internal_only_logins': ''})
        self.assertEqual(set(self.file('rspamd-plugins.conf').values()), {''})

    def test_the_new_plugins_never_conflict_with_each_other(self) -> None:
        Mailbox.objects.create(domain=self.make_domain(), local_part='journal')
        for plugin_id, settings in (
            ('attachment-guard', {}),
            ('dmarc-enforcement', {}),
            ('forwarding-control', {}),
            ('mailbox-cleanup', {}),
            ('partner-tls', {'domains': 'bank.example'}),
            ('arc-forwarding', {}),
            ('mail-policy', {}),
            ('compliance-journal', {'archive_address': 'journal@ifinmail.test'}),
        ):
            try:
                InstallationService.install(plugin_id, settings, 'a')
            except ConflictError as exc:  # pragma: no cover - the assertion below explains
                self.fail(f'{plugin_id}: {exc}')
        self.assertEqual(len(InstallationService.all()), 8)


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

    def test_arc_trust_and_sealing(self) -> None:
        self.file.write_text('arc_trusted_sealers = google.com,microsoft.com\narc_sealing = yes\n')
        self.run_script()
        self.assertEqual((self.out / 'arc_trusted.map').read_text(), 'google.com\nmicrosoft.com\n')
        arc = (self.out / 'arc.conf').read_text()
        self.assertIn(f'whitelisted_signers_map = "file://{self.out}/arc_trusted.map";', arc)
        self.assertIn('adjust_dmarc = true;', arc)
        self.assertIn('path = "/etc/dkim/$domain.$selector.key";', arc)  # the DKIM keys
        self.assertIn('selector = "default";', arc)
        self.assertIn('sign_inbound = true;', arc)
        self.file.write_text('arc_trusted_sealers = google.com\narc_sealing = no\n')
        self.run_script()
        arc = (self.out / 'arc.conf').read_text()
        self.assertIn('whitelisted_signers_map', arc)
        self.assertNotIn('sign_inbound', arc)

    def test_unsafe_sealers_are_refused(self) -> None:
        self.file.write_text('arc_trusted_sealers = google.com";evil\narc_sealing = maybe\n')
        log = self.run_script()
        self.assertEqual(log.count('ignoring unsafe value'), 2)
        self.assertEqual((self.out / 'arc.conf').read_text(), '')

    def test_sender_lists_split_addresses_from_domains(self) -> None:
        self.file.write_text(
            'sender_block_list = bob@bad.example,spam.example\n'
            'sender_allow_list = partner.example\n'
        )
        self.run_script()
        self.assertEqual((self.out / 'sender_block_addr.map').read_text(), 'bob@bad.example\n')
        self.assertEqual((self.out / 'sender_block_domain.map').read_text(), 'spam.example\n')
        self.assertEqual((self.out / 'sender_allow_addr.map').read_text(), '')
        rules = (self.out / 'multimap.conf').read_text()
        # Blocked in the envelope and in the From header; allow entries only score.
        for symbol in (
            'IFINMAIL_BLOCK_ENV',
            'IFINMAIL_BLOCK_HDR',
            'IFINMAIL_BLOCK_ENV_DOMAIN',
            'IFINMAIL_BLOCK_HDR_DOMAIN',
            'IFINMAIL_ALLOW_ENV_DOMAIN',
            'IFINMAIL_ALLOW_HDR_DOMAIN',
        ):
            self.assertIn(f'{symbol} {{', rules)
        self.assertNotIn('IFINMAIL_ALLOW_ENV {', rules)  # no addresses, no rule
        self.assertEqual(rules.count('action = "reject";'), 4)
        self.assertEqual(rules.count('score = 0.0;'), 2)
        # An allow entry counts only with SPF or DKIM, and exempts the sender from greylisting.
        composite = (self.out / 'composites.conf').read_text()
        self.assertIn('& (R_DKIM_ALLOW | R_SPF_ALLOW)', composite)
        self.assertIn(
            'whitelist_symbols = ["IFINMAIL_SENDER_ALLOWED"];',
            (self.out / 'greylist.conf').read_text(),
        )

    def test_unsafe_sender_entries_are_refused(self) -> None:
        self.file.write_text(
            'sender_block_list = bad.example";}evil{\nsender_allow_list = *.example\n'
        )
        self.assertEqual(self.run_script().count('ignoring unsafe value'), 2)
        self.assertEqual((self.out / 'multimap.conf').read_text(), '')
        self.assertEqual((self.out / 'composites.conf').read_text(), '')

    def test_greylisting_off(self) -> None:
        self.file.write_text('greylisting = off\n')
        self.run_script()
        self.assertEqual((self.out / 'greylist.conf').read_text(), 'enabled = false;\n')
        self.file.write_text('greylisting = on\n')
        self.run_script()
        self.assertEqual((self.out / 'greylist.conf').read_text(), '')

    def test_sending_limits_use_separate_buckets(self) -> None:
        self.file.write_text('send_limit_per_minute = 30\nsend_limit_per_day = 2000\n')
        self.run_script()
        rates = (self.out / 'ratelimit.conf').read_text()
        # Rspamd keys a bucket by the selector value: the same selector twice shares a counter.
        self.assertIn(
            'selector = "user.lower";\n    bucket = { burst = 30; rate = "30 / 1m"; };', rates
        )
        self.assertIn('selector = "user.lower.append(\\"/day\\")";', rates)
        self.assertIn('rate = "2000 / 1d"', rates)
        self.assertIn('user_to_domain {', rates)  # the built-in per-domain limit is kept
        self.file.write_text('send_limit_per_minute = 0\nsend_limit_per_day = 2000\n')
        self.assertIn('ignoring unsafe value', self.run_script())
        self.assertEqual((self.out / 'ratelimit.conf').read_text(), '')  # built-in rates apply

    def test_empty_values_remove_the_rules(self) -> None:
        self.file.write_text('blocked_attachment_types = \ndmarc_enforcement = \n')
        self.run_script()
        self.assertEqual((self.out / 'arc.conf').read_text(), '')
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

    def test_quota_warnings(self) -> None:
        self.file.write_text('quota_warnings = yes\n')
        self.run_script()
        text = self.out.read_text()
        self.assertIn('quota_warning = storage=95%% quota-warning 95 %u', text)
        self.assertIn('quota_warning2 = storage=80%% quota-warning 80 %u', text)
        self.assertIn('executable = script /usr/local/bin/ifinmail-quota-warning', text)
        self.assertIn('user = vmail\n    mode = 0600', text)
        for off in ('no', ''):
            self.file.write_text(f'quota_warnings = {off}\n')
            self.run_script()
            self.assertNotIn('quota', self.out.read_text())
        self.file.write_text('quota_warnings = true\n')
        self.assertIn('ignoring unsafe value', self.run_script())

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
        for rel in (
            'rspamd/local.d/multimap.conf',
            'rspamd/local.d/dmarc.conf',
            'rspamd/local.d/arc.conf',
            'rspamd/local.d/composites.conf',
            'rspamd/local.d/greylist.conf',
            'rspamd/local.d/ratelimit.conf',
        ):
            self.assertIn('.include(try=true;', (DOCKER / rel).read_text(), rel)
        dovecot = (DOCKER / 'dovecot' / 'dovecot.conf').read_text()
        self.assertTrue(
            dovecot.rstrip().endswith('!include_try /etc/dovecot/ifinmail-plugins.conf'),
            'dovecot.conf must include the plugin file last so it overrides',
        )

    def test_submission_restrictions_are_one_postfix_parameter(self) -> None:
        # The sender-policy watcher rewrites this parameter; both submission services use it.
        master = (DOCKER / 'postfix' / 'master.cf').read_text()
        self.assertEqual(
            master.count('-o smtpd_recipient_restrictions=$ifinmail_submission_restrictions'), 2
        )
        main = (DOCKER / 'postfix' / 'main.cf').read_text()
        self.assertIn('ifinmail_submission_restrictions = permit_sasl_authenticated, reject', main)
        self.assertIn('smtpd_restriction_classes = ifinmail_internal_only', main)
        self.assertIn('ifinmail_internal_only = permit_auth_destination, ', main)
        self.assertIn('message_size_limit = 52428800', main)  # what an uninstall restores

    def test_quota_warning_script_ships_in_the_image(self) -> None:
        dockerfile = (DOCKER / 'dovecot' / 'Dockerfile').read_text()
        self.assertIn('/usr/local/bin/ifinmail-quota-warning', dockerfile)
        script = (DOCKER / 'dovecot' / 'quota-warning.sh').read_text()
        self.assertIn('plugin/quota=maildir:User quota:noenforcing', script)


class QuotaWarningScriptTests(SimpleTestCase):
    script = DOCKER / 'dovecot' / 'quota-warning.sh'

    def deliver(self, *args: str) -> tuple[int, str]:
        if shutil.which('sh') is None:
            self.skipTest('needs sh')
        work = Path(tempfile.mkdtemp(prefix='ifinmail-qw-'))
        self.addCleanup(shutil.rmtree, work, True)
        lda = work / 'lda'
        lda.write_text(f'#!/bin/sh\necho "$@" > "{work}/args"\ncat > "{work}/message"\n')
        lda.chmod(0o755)
        env = {**os.environ, 'DOVECOT_LDA': str(lda)}
        result = subprocess.run(['sh', str(self.script), *args], env=env, capture_output=True)
        out = ''
        if (work / 'message').exists():
            out = (work / 'args').read_text() + (work / 'message').read_text()
        return result.returncode, out

    def test_delivers_a_notice_past_the_quota(self) -> None:
        code, out = self.deliver('80', 'u@x.example')
        self.assertEqual(code, 0)
        self.assertIn('-d u@x.example -o plugin/quota=maildir:User quota:noenforcing', out)
        self.assertIn('Subject: Your mailbox is 80% full', out)
        self.assertIn('From: Mail server <postmaster@x.example>', out)
        self.assertIn('Auto-Submitted: auto-generated', out)

    def test_refuses_odd_arguments(self) -> None:
        for args in (('8O', 'u@x.example'), ('80', 'u@x.example -o x'), ('80', '$(id)@x')):
            with self.subTest(args=args):
                code, out = self.deliver(*args)
                self.assertNotEqual(code, 0)
                self.assertEqual(out, '')


class ApplyStatusTests(MailTablesTestCase):
    def test_every_point_reports_status(self) -> None:
        status_dir = Path(self.tmp) / 'status'
        status_dir.mkdir()
        with patch.dict(os.environ, {'IFINMAIL_STATUS_DIR': str(status_dir)}):
            InstallationService.install('dmarc-enforcement', {}, 'a')
            statuses = InstallationService.apply_status()
        self.assertEqual(
            sorted(statuses),
            [
                'dovecot.policy',
                'postfix.main',
                'postfix.sender_policy',
                'postfix.tls_policy',
                'rspamd.policy',
            ],
        )
