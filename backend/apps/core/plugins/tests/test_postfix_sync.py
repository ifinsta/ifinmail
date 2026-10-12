"""The postfix watcher (sync-overrides.sh) applying the plugins file, end to end with stubs."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from backend.apps.core.plugins.services import InstallationService, registry
from backend.apps.core.plugins.types import ApplyStatus
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.mail.models import Mailbox

SCRIPT = (
    Path(__file__).resolve().parents[5]
    / 'provisioning'
    / 'docker'
    / 'postfix'
    / 'sync-overrides.sh'
)

RESTORE_SIZE = 'postconf -e message_size_limit=52428800'


def _bash_works() -> bool:
    return shutil.which('bash') is not None and shutil.which('sha256sum') is not None


class _Harness:
    def __init__(self) -> None:
        self.work = tempfile.mkdtemp(prefix='ifinmail-sync-')
        for name in ('postconf', 'postfix'):
            path = Path(self.work, name)
            path.write_text(f'#!/bin/sh\necho "{name} $*" >> "{self.work}/calls.log"\n')
            path.chmod(0o755)
        self.status = Path(self.work, 'status')
        self.status.mkdir()
        self.plugins = Path(self.work, 'postfix-plugins.conf')
        self.core = Path(self.work, 'postfix-overrides.conf')
        self.template = Path(self.work, 'main.cf.template')
        self.template.write_text('message_size_limit = 52428800\r\n')
        self.sender = Path(self.work, 'postfix-sender-policy.conf')
        self.sender_map = Path(self.work, 'internal_only')

    def run(self) -> list[str]:
        log = Path(self.work, 'calls.log')
        log.unlink(missing_ok=True)
        env = {
            **os.environ,
            'IFINMAIL_OVERRIDES_FILE': str(self.core),
            'IFINMAIL_OVERRIDES_STATE': str(Path(self.work, 'core.state')),
            'IFINMAIL_PLUGINS_FILE': str(self.plugins),
            'IFINMAIL_PLUGINS_STATE': str(Path(self.work, 'plugins.state')),
            'IFINMAIL_STATUS_DIR': str(self.status),
            'IFINMAIL_MAIN_CF_TEMPLATE': str(self.template),
            'IFINMAIL_TLS_POLICY_FILE': str(Path(self.work, 'none')),
            'IFINMAIL_SENDER_POLICY_FILE': str(self.sender),
            'IFINMAIL_SENDER_POLICY_STATE': str(Path(self.work, 'sender.state')),
            'IFINMAIL_SENDER_POLICY_MAP': str(self.sender_map),
            'POSTCONF_BIN': str(Path(self.work, 'postconf')),
            'POSTFIX_BIN': str(Path(self.work, 'postfix')),
        }
        subprocess.run(['bash', str(SCRIPT), '--once'], env=env, check=True, capture_output=True)
        return log.read_text().splitlines() if log.exists() else []

    def ack(self, name: str = 'postfix-plugins.applied') -> str:
        path = self.status / name
        return path.read_text().strip() if path.exists() else ''

    def cleanup(self) -> None:
        shutil.rmtree(self.work, True)


class WatcherTests(SimpleTestCase):
    def setUp(self) -> None:
        if not _bash_works():
            self.skipTest('needs bash and sha256sum')
        self.h = _Harness()
        self.addCleanup(self.h.cleanup)

    def test_applies_the_value_reloads_and_acknowledges(self) -> None:
        self.h.plugins.write_text('# generated\nalways_bcc = journal@example.test\n')
        self.assertEqual(
            self.h.run(), ['postconf -e always_bcc=journal@example.test', 'postfix reload']
        )
        self.assertEqual(self.h.ack(), hashlib.sha256(self.h.plugins.read_bytes()).hexdigest())

    def test_unchanged_file_costs_nothing_and_a_lost_ack_is_restored(self) -> None:
        self.h.plugins.write_text('always_bcc = journal@example.test\n')
        self.h.run()
        self.assertEqual(self.h.run(), [])
        (self.h.status / 'postfix-plugins.applied').unlink()
        self.assertEqual(self.h.run(), [])
        self.assertNotEqual(self.h.ack(), '')

    def test_an_empty_value_removes_the_setting(self) -> None:
        self.h.plugins.write_text('always_bcc = \n')
        self.assertEqual(self.h.run(), ['postconf -X always_bcc', 'postfix reload'])

    def test_plugins_can_never_set_core_keys_or_unsafe_values(self) -> None:
        self.h.plugins.write_text(
            'relayhost = [smtp.evil.test]:587\n'
            'mynetworks = 0.0.0.0/0\n'
            'always_bcc = a@b.test,c@d.test\n'
            'always_bcc = $(touch /tmp/pwned)@x.test\n'
            'always_bcc = a@b.test c@d.test\n'
            'always_bcc = proxy:pgsql:/etc/x\n'
            'not a setting line\n'
        )
        self.assertEqual(self.h.run(), [])

    def test_the_core_file_cannot_set_plugin_keys(self) -> None:
        self.h.core.write_text('always_bcc = spy@example.test\nhopcount_limit = 10\n')
        self.assertEqual(self.h.run(), ['postconf -e hopcount_limit=10', 'postfix reload'])

    def test_a_missing_status_dir_does_not_break_applying(self) -> None:
        shutil.rmtree(self.h.status)
        self.h.plugins.write_text('always_bcc = journal@example.test\n')
        self.assertEqual(self.h.run()[0], 'postconf -e always_bcc=journal@example.test')

    def test_message_size_is_set_in_bytes_and_restored_from_the_template(self) -> None:
        self.h.plugins.write_text('message_size_limit_mb = 25\n')
        self.assertEqual(
            self.h.run(), ['postconf -e message_size_limit=26214400', 'postfix reload']
        )
        self.h.plugins.write_text('message_size_limit_mb = \n')
        # This server's own 50 MB, never Postfix's built-in 10 MB.
        self.assertEqual(self.h.run(), [RESTORE_SIZE, 'postfix reload'])

    def test_message_size_out_of_range_is_ignored(self) -> None:
        for bad in ('0', '51', '150', '25MB', '-1', '1e3'):
            with self.subTest(bad=bad):
                self.h.plugins.write_text(f'message_size_limit_mb = {bad}\n')
                self.assertEqual(self.h.run(), [])

    def test_internal_only_logins_become_a_sasl_map(self) -> None:
        self.h.sender.write_text('internal_only_logins = intern@x.test,temp@x.test\n')
        self.assertEqual(
            self.h.run(),
            [
                'postconf -e ifinmail_submission_restrictions=check_sasl_access '
                f'texthash:{self.h.sender_map}, permit_sasl_authenticated, reject',
                'postfix reload',
            ],
        )
        self.assertEqual(
            self.h.sender_map.read_text(),
            'intern@x.test ifinmail_internal_only\ntemp@x.test ifinmail_internal_only\n',
        )
        digest = hashlib.sha256(self.h.sender.read_bytes()).hexdigest()
        self.assertEqual(self.h.ack('postfix-sender-policy.applied'), digest)
        self.h.sender.write_text('internal_only_logins = \n')
        self.assertEqual(
            self.h.run(),
            [
                'postconf -e ifinmail_submission_restrictions=permit_sasl_authenticated, reject',
                'postfix reload',
            ],
        )
        self.assertEqual(self.h.sender_map.read_text(), '')

    def test_unsafe_logins_and_foreign_keys_never_reach_postfix(self) -> None:
        self.h.sender.write_text(
            'internal_only_logins = a@x.test, permit\n'
            'internal_only_logins = a@x.test;reject\n'
            'smtpd_recipient_restrictions = permit\n'
        )
        self.assertEqual(
            self.h.run(),
            [
                'postconf -e ifinmail_submission_restrictions=permit_sasl_authenticated, reject',
                'postfix reload',
            ],
        )


class EndToEndTests(MailTablesTestCase):
    """Console renders -> watcher applies -> console reports Applied."""

    def setUp(self) -> None:
        super().setUp()
        if not _bash_works():
            self.skipTest('needs bash and sha256sum')
        self.h = _Harness()
        self.addCleanup(self.h.cleanup)
        patcher = patch.dict(os.environ, {'IFINMAIL_STATUS_DIR': str(self.h.status)})
        patcher.start()
        self.addCleanup(patcher.stop)
        Mailbox.objects.create(domain=self.make_domain(), local_part='journal')

    def sync(self) -> list[str]:
        shutil.copy(Path(self.runtime_dir) / 'postfix-plugins.conf', self.h.plugins)
        return self.h.run()

    def test_install_apply_disable_apply(self) -> None:
        point = registry.get_target('postfix.main')
        InstallationService.install(
            'compliance-journal', {'archive_address': 'journal@ifinmail.test'}, 'a'
        )
        self.assertNotEqual(point.applied_status(), ApplyStatus.APPLIED)
        self.assertEqual(
            self.sync(),
            [
                'postconf -e always_bcc=journal@ifinmail.test',
                RESTORE_SIZE,
                'postfix reload',
            ],
        )
        self.assertEqual(point.applied_status(), ApplyStatus.APPLIED)
        InstallationService.disable('compliance-journal', 'a')
        self.assertNotEqual(point.applied_status(), ApplyStatus.APPLIED)
        self.assertEqual(self.sync(), ['postconf -X always_bcc', RESTORE_SIZE, 'postfix reload'])
        self.assertEqual(point.applied_status(), ApplyStatus.APPLIED)
