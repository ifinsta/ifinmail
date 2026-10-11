"""Mailbox, alias and outbound-setting services."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from unittest.mock import patch

from backend.apps.accounts.models import MailUser
from backend.apps.core.platform.services.runtime import read_runtime_file
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.mail.models import Alias, Mailbox
from backend.apps.mail.services import AliasService, MailboxService
from backend.apps.mail.services.postfix_runtime import OutboundConfigError, PostfixRuntime
from backend.apps.mail.types.provisioning import MailboxError
from backend.apps.mail.types.quota import DEFAULT_QUOTA_BYTES

GOOD = 'Correct-Horse-9'


def _bash_works() -> bool:
    exe = shutil.which('bash')
    if not exe:
        return False
    try:
        result = subprocess.run([exe, '--version'], capture_output=True, text=True, timeout=10)
        return result.returncode == 0 and 'GNU' in (result.stdout + result.stderr)
    except Exception:
        return False


class MailboxServiceTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.domain = self.make_domain()

    def test_creates_mailbox_and_login_together(self) -> None:
        mailbox, user = MailboxService.create('ifinmail.test', 'Alice', GOOD, quota_bytes=5_000_000)
        self.assertEqual(MailboxService.address_for(mailbox), 'alice@ifinmail.test')
        self.assertEqual(user.email, 'alice@ifinmail.test')
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertEqual(mailbox.quota_bytes, 5_000_000)

    def test_new_mailboxes_default_to_1024_mb(self) -> None:
        mailbox, _ = MailboxService.create('ifinmail.test', 'alice', GOOD)
        self.assertEqual(mailbox.quota_bytes, DEFAULT_QUOTA_BYTES)

    def test_explicit_zero_means_unlimited(self) -> None:
        mailbox, _ = MailboxService.create('ifinmail.test', 'alice', GOOD, quota_bytes=0)
        self.assertEqual(mailbox.quota_bytes, 0)

    def test_dovecot_hash_is_sha512_crypt_and_verifies_with_openssl(self) -> None:
        _, user = MailboxService.create('ifinmail.test', 'alice', GOOD)
        self.assertTrue(user.password_hash.startswith('$6$'))
        self.assertTrue(user.check_password(GOOD))
        if shutil.which('openssl') is None:
            self.skipTest('needs openssl')
        salt = user.password_hash.split('$')[2]
        expected = subprocess.run(
            ['openssl', 'passwd', '-6', '-salt', salt, GOOD], capture_output=True, text=True
        ).stdout.strip()
        self.assertEqual(user.password_hash, expected)

    def test_nothing_is_left_behind_when_creation_fails_half_way(self) -> None:
        with (
            patch.object(MailUser.objects, 'create_user', side_effect=RuntimeError('boom')),
            self.assertRaises(RuntimeError),
        ):
            MailboxService.create('ifinmail.test', 'alice', GOOD)
        self.assertEqual(Mailbox.objects.count(), 0)

    def test_rejects_bad_names_weak_passwords_and_unknown_domains(self) -> None:
        for local in ('', 'a b', '-x', 'x-', 'a..b', 'x' * 65, 'a@b'):
            with self.assertRaises(MailboxError, msg=local):
                MailboxService.create('ifinmail.test', local, GOOD)
        with self.assertRaises(MailboxError):
            MailboxService.create('ifinmail.test', 'alice', 'short')
        with self.assertRaises(MailboxError):
            MailboxService.create('ifinmail.test', 'alice', 'password')  # too common
        with self.assertRaises(MailboxError):
            MailboxService.create('nope.test', 'alice', GOOD)

    def test_duplicates_are_refused_including_aliases_and_logins(self) -> None:
        MailboxService.create('ifinmail.test', 'alice', GOOD)
        with self.assertRaises(MailboxError):
            MailboxService.create('ifinmail.test', 'ALICE', GOOD)
        Alias.objects.create(
            domain=self.domain, source='sales@ifinmail.test', destination='x@y.test'
        )
        with self.assertRaises(MailboxError):
            MailboxService.create('ifinmail.test', 'sales', GOOD)

    def test_reserved_names_are_only_blocked_for_self_registration(self) -> None:
        MailboxService.create('ifinmail.test', 'postmaster', GOOD)  # an admin may
        with self.assertRaises(MailboxError):
            MailboxService.create('ifinmail.test', 'admin', GOOD, enforce_reserved=True)

    def test_first_run_wizard_can_adopt_the_bootstrap_admin_login(self) -> None:
        MailUser.objects.create_user('admin@ifinmail.test', 'Bootstrap-Pass-1', is_staff=True)
        with self.assertRaises(MailboxError):
            MailboxService.create('ifinmail.test', 'admin', GOOD)
        _, user = MailboxService.create(
            'ifinmail.test', 'admin', GOOD, is_admin=True, adopt_existing_login=True
        )
        self.assertEqual(MailUser.objects.count(), 1)
        self.assertTrue(user.check_password(GOOD))
        self.assertTrue(user.is_staff)

    def test_change_password_updates_both_hashes(self) -> None:
        _, user = MailboxService.create('ifinmail.test', 'alice', GOOD)
        old_hash = user.password_hash
        MailboxService.set_password('alice@ifinmail.test', 'Another-Pass-77')
        user.refresh_from_db()
        self.assertNotEqual(user.password_hash, old_hash)
        self.assertTrue(user.check_password('Another-Pass-77'))
        with self.assertRaises(MailboxError):
            MailboxService.set_password('alice@ifinmail.test', 'x')

    def test_quota_and_disable(self) -> None:
        MailboxService.create('ifinmail.test', 'alice', GOOD)
        MailboxService.create('ifinmail.test', 'root1', GOOD, is_admin=True)
        MailboxService.set_quota('alice@ifinmail.test', 10 * 1024 * 1024)
        self.assertEqual(Mailbox.objects.get(local_part='alice').quota_bytes, 10 * 1024 * 1024)
        with self.assertRaises(MailboxError):
            MailboxService.set_quota('alice@ifinmail.test', -1)
        MailboxService.set_active('alice@ifinmail.test', False)
        self.assertFalse(MailUser.objects.get(email='alice@ifinmail.test').is_active)

    def test_the_last_administrator_cannot_be_disabled_or_deleted(self) -> None:
        MailboxService.create('ifinmail.test', 'root1', GOOD, is_admin=True)
        with self.assertRaises(MailboxError):
            MailboxService.set_active('root1@ifinmail.test', False)
        with self.assertRaises(MailboxError):
            MailboxService.delete('root1@ifinmail.test')
        MailboxService.create('ifinmail.test', 'root2', GOOD, is_admin=True)
        MailboxService.delete('root1@ifinmail.test')

    def test_delete_removes_mailbox_login_and_outgoing_aliases(self) -> None:
        MailboxService.create('ifinmail.test', 'alice', GOOD)
        MailboxService.delete('alice@ifinmail.test')
        self.assertEqual(Mailbox.objects.count(), 0)
        self.assertEqual(MailUser.objects.count(), 0)
        with self.assertRaises(MailboxError):
            MailboxService.delete('alice@ifinmail.test')

    def test_list_rows_reports_status_and_role(self) -> None:
        MailboxService.create('ifinmail.test', 'alice', GOOD)
        MailboxService.create('ifinmail.test', 'boss', GOOD, is_admin=True)
        MailboxService.set_active('alice@ifinmail.test', False)
        rows = {r.address: r for r in MailboxService.list_rows()}
        self.assertFalse(rows['alice@ifinmail.test'].is_active)
        self.assertTrue(rows['boss@ifinmail.test'].is_admin)

    def test_claim_for_login_renames_the_login_to_the_new_address(self) -> None:
        pending = MailUser.objects.create_user('person@gmail.example', GOOD, is_active=True)
        MailboxService.claim_for_login(pending, 'ifinmail.test', 'person')
        pending.refresh_from_db()
        self.assertEqual(pending.email, 'person@ifinmail.test')
        self.assertTrue(pending.check_password(GOOD))
        self.assertTrue(Mailbox.objects.filter(local_part='person').exists())

    def test_claiming_cannot_hijack_an_existing_mailbox_or_alias(self) -> None:
        Mailbox.objects.create(domain=self.domain, local_part='finance')  # no login yet
        Alias.objects.create(
            domain=self.domain, source='sales@ifinmail.test', destination='a@b.test'
        )
        for name in ('finance', 'sales', 'postmaster'):
            pending = MailUser.objects.create_user(f'{name}@ext.example', GOOD)
            with self.assertRaises(MailboxError, msg=name):
                MailboxService.claim_for_login(pending, 'ifinmail.test', name)
            pending.refresh_from_db()
            self.assertTrue(pending.email.endswith('@ext.example'))


class AliasServiceTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.domain = self.make_domain()

    def test_creates_an_alias_with_a_full_address_source(self) -> None:
        alias = AliasService.create('Sales@ifinmail.test', 'Me@Example.org')
        self.assertEqual(
            (alias.source, alias.destination), ('sales@ifinmail.test', 'me@example.org')
        )

    def test_postfix_lookup_key_is_the_full_address(self) -> None:
        """virtual_aliases.cf looks the whole address up in aliases.source."""
        AliasService.create('sales@ifinmail.test', 'me@example.org')
        self.assertTrue(Alias.objects.filter(source='sales@ifinmail.test').exists())

    def test_rejects_loops_self_forwards_shadowing_and_bad_input(self) -> None:
        AliasService.create('a@ifinmail.test', 'b@ifinmail.test')
        with self.assertRaises(MailboxError):
            AliasService.create('b@ifinmail.test', 'a@ifinmail.test')
        with self.assertRaises(MailboxError):
            AliasService.create('c@ifinmail.test', 'c@ifinmail.test')
        MailboxService.create('ifinmail.test', 'real', GOOD)
        with self.assertRaises(MailboxError):
            AliasService.create('real@ifinmail.test', 'x@example.org')
        with self.assertRaises(MailboxError):
            AliasService.create('d@ifinmail.test', 'not-an-email')
        with self.assertRaises(MailboxError):
            AliasService.create('d@unknown.test', 'x@example.org')

    def test_several_destinations_for_one_alias_and_deleting(self) -> None:
        AliasService.create('team@ifinmail.test', 'a@example.org')
        AliasService.create('team@ifinmail.test', 'b@example.org')
        self.assertEqual(Alias.objects.filter(source='team@ifinmail.test').count(), 2)
        AliasService.delete(str(Alias.objects.first().pk))
        self.assertEqual(Alias.objects.count(), 1)
        with self.assertRaises(MailboxError):
            AliasService.delete('00000000-0000-0000-0000-000000000000')


class PostfixRuntimeTests(MailTablesTestCase):
    env = {'MAIL_SMART_HOST': 'relay.example.net', 'MAIL_SMTP_PROXY': 'proxy.example.net:2525'}

    def test_defaults_render_no_relay_and_the_configured_hop_limit(self) -> None:
        text = PostfixRuntime.render()
        self.assertIn(
            'relayhost = [relay.example.net]:587', text
        )  # env says enabled when a host is set
        with patch.dict(os.environ, {'MAIL_SMART_HOST': '', 'MAIL_SMTP_PROXY': ''}):
            text = PostfixRuntime.render()
        self.assertIn('relayhost = \n', text)
        self.assertIn('default_transport = \n', text)

    def test_toggles_persist_and_publish_the_file_postfix_reads(self) -> None:
        PostfixRuntime.set_smart_host(False)
        PostfixRuntime.set_smtp_proxy(True)
        PostfixRuntime.set_max_hops(12)
        published = read_runtime_file('postfix-overrides.conf')
        self.assertIn('relayhost = \n', published)
        self.assertIn('default_transport = smtp:[proxy.example.net]:2525', published)
        self.assertIn('hopcount_limit = 12', published)
        self.assertFalse(PostfixRuntime.state().smart_host_enabled)  # survives a "restart"

    def test_enabling_without_a_host_is_refused_not_faked(self) -> None:
        with (
            patch.dict(os.environ, {'MAIL_SMART_HOST': ''}),
            self.assertRaises(OutboundConfigError),
        ):
            PostfixRuntime.set_smart_host(True)

    def test_hop_limit_is_bounded(self) -> None:
        for bad in (4, 31, -1):
            with self.assertRaises(OutboundConfigError):
                PostfixRuntime.set_max_hops(bad)

    def test_legacy_boolean_env_values_do_not_become_hostnames(self) -> None:
        with patch.dict(os.environ, {'MAIL_SMART_HOST': 'true', 'MAIL_SMTP_PROXY': '1'}):
            state = PostfixRuntime.state()
            self.assertEqual((state.smart_host, state.smtp_proxy), ('', ''))
            self.assertIn('relayhost = \n', PostfixRuntime.render())


class SyncScriptTests(MailTablesTestCase):
    """The watcher inside the postfix container, run against fake postconf/postfix."""

    SCRIPT = os.path.join(
        os.path.dirname(__file__),
        '..',
        '..',
        '..',
        '..',
        'provisioning',
        'docker',
        'postfix',
        'sync-overrides.sh',
    )

    def setUp(self) -> None:
        super().setUp()
        if not _bash_works():
            self.skipTest('needs working bash')

    def _run(self, content: str) -> list[str]:
        work = tempfile.mkdtemp(dir=self.tmp)
        for name in ('postconf', 'postfix'):
            path = os.path.join(work, name)
            with open(path, 'w') as handle:
                handle.write(f'#!/bin/sh\necho "{name} $*" >> "{work}/calls.log"\n')
            os.chmod(path, 0o755)
        overrides = os.path.join(work, 'overrides.conf')
        with open(overrides, 'w') as handle:
            handle.write(content)
        env = {
            **os.environ,
            'IFINMAIL_OVERRIDES_FILE': overrides,
            'IFINMAIL_OVERRIDES_STATE': os.path.join(work, 'state'),
            'POSTCONF_BIN': os.path.join(work, 'postconf'),
            'POSTFIX_BIN': os.path.join(work, 'postfix'),
        }
        subprocess.run(['bash', self.SCRIPT, '--once'], env=env, check=True, capture_output=True)
        calls = os.path.join(work, 'calls.log')
        return open(calls).read().splitlines() if os.path.exists(calls) else []

    def test_applies_the_rendered_file_and_reloads_postfix(self) -> None:
        with patch.dict(os.environ, {'MAIL_SMART_HOST': '', 'MAIL_SMTP_PROXY': ''}):
            rendered = PostfixRuntime.render()
        calls = self._run(rendered)
        self.assertEqual(
            calls,
            [
                'postconf -X relayhost',
                'postconf -X default_transport',
                'postconf -e hopcount_limit=10',
                'postfix reload',
            ],
        )

    def test_only_allow_listed_keys_with_safe_values_are_applied(self) -> None:
        calls = self._run(
            'relayhost = [smtp.example.net]:587\nmyhostname = evil.example\n'
            'inet_interfaces = $(touch /tmp/pwned)\nhopcount_limit = 5;rm -rf\n'
        )
        self.assertEqual(calls, ['postconf -e relayhost=[smtp.example.net]:587', 'postfix reload'])
        self.assertFalse(os.path.exists('/tmp/pwned'))
