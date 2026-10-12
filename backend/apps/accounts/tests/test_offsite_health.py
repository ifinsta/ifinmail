"""Off-site backup and backup-key health checks, and the offsite script's safety contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from backend.apps.accounts.services import system_health as sh

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / 'provisioning' / 'scripts'
RUNTIME = 'backend.apps.core.platform.services.runtime.read_runtime_file'


def _iso(hours_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).strftime('%Y-%m-%dT%H:%M:%SZ')


def _runtime(files: dict[str, str]):
    return patch(RUNTIME, side_effect=lambda name: files.get(name))


class OffsiteCheckTests(SimpleTestCase):
    def test_waits_for_the_first_backup(self) -> None:
        with _runtime({}):
            self.assertEqual(sh._offsite_backup().state, sh.WAITING)

    def test_not_configured_is_a_warning_with_the_fix(self) -> None:
        with _runtime({'last-backup-at': _iso(2)}):
            check = sh._offsite_backup()
        self.assertEqual(check.state, sh.WARNING)
        self.assertIn('only on this server', check.summary)
        self.assertIn('BACKUP_OFFSITE_TARGET', check.values[0][1])
        with _runtime({'last-backup-at': _iso(2), 'offsite-status': f'disabled {_iso(2)}'}):
            self.assertEqual(sh._offsite_backup().state, sh.WARNING)

    def test_a_recent_verified_copy_is_ok(self) -> None:
        with _runtime({'offsite-status': f'ok {_iso(3)} backup@store.example'}):
            check = sh._offsite_backup()
        self.assertEqual(check.state, sh.OK)
        self.assertIn('backup@store.example', check.summary)

    def test_a_stale_copy_escalates(self) -> None:
        with _runtime({'offsite-status': f'ok {_iso(40)} h'}):
            self.assertEqual(sh._offsite_backup().state, sh.WARNING)
        with _runtime({'offsite-status': f'ok {_iso(100)} h'}):
            self.assertEqual(sh._offsite_backup().state, sh.ERROR)

    def test_a_failed_copy_is_an_error_with_the_reason(self) -> None:
        with _runtime({'offsite-status': f'failed {_iso(1)} copy to h did not complete'}):
            check = sh._offsite_backup()
        self.assertEqual(check.state, sh.ERROR)
        self.assertIn('did not complete', check.summary)

    def test_garbage_is_reported_not_raised(self) -> None:
        with _runtime({'offsite-status': 'ok not-a-time h'}):
            self.assertEqual(sh._offsite_backup().state, sh.UNKNOWN)


class BackupKeyCheckTests(SimpleTestCase):
    def test_unexported_key_warns(self) -> None:
        with _runtime({}):
            check = sh._backup_key()
        self.assertEqual(check.state, sh.WARNING)
        self.assertIn('make backup-key', check.values[0][1])

    def test_exported_key_is_ok(self) -> None:
        with _runtime({'backup-key-exported-at': '2026-10-12T04:00:00Z'}):
            check = sh._backup_key()
        self.assertEqual(check.state, sh.OK)
        self.assertIn('2026-10-12', check.summary)


class OffsiteScriptContractTests(SimpleTestCase):
    """Properties that must not regress; the behaviour itself is exercised end to end by drills."""

    def setUp(self) -> None:
        self.script = (SCRIPTS / 'backup_offsite.sh').read_text()

    def test_plaintext_archives_are_refused(self) -> None:
        self.assertIn('*.gpg) ;;', self.script)
        self.assertIn('refusing to send an unencrypted archive', self.script)

    def test_the_target_is_validated_before_it_reaches_a_remote_shell(self) -> None:
        self.assertIn('[A-Za-z0-9._/-]+', self.script)
        self.assertNotIn('StrictHostKeyChecking=no', self.script)

    def test_the_copy_is_verified_by_checksum_and_published_atomically(self) -> None:
        self.assertIn('sha256sum', self.script)
        self.assertIn('.partial', self.script)

    def test_the_key_is_never_sent_with_the_backups(self) -> None:
        send = self.script.split('cmd_send()')[1].split('cmd_check()')[0]
        self.assertNotIn('.asc', send)
        self.assertNotIn('PASSPHRASE', send)

    def test_a_backup_runs_the_copy_and_survives_its_failure(self) -> None:
        backup = (SCRIPTS / 'backup_full.sh').read_text()
        self.assertIn('backup_offsite.sh" send "$ARCHIVE_NAME"', backup)
        self.assertLess(
            backup.index('backup_offsite.sh" send'), backup.index('record_backup_status\n')
        )
        self.assertIn('the local backup is intact', backup)

    def test_make_targets_exist(self) -> None:
        makefile = (ROOT / 'Makefile').read_text()
        self.assertIn('backup_offsite.sh check', makefile)
        self.assertIn('backup_offsite.sh export-key', makefile)
