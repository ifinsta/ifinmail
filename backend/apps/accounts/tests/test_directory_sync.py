"""The CardDAV-side mirror (provisioning/docker/dav/directory-sync.py).

It runs in the dav container, not in Django, so it is loaded from its file here and pointed at
temporary directories. The rights and Radicale behaviour it relies on are covered by the
integration check recorded in docs (real Radicale 3.8.3); these tests pin the file operations.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from types import ModuleType

from django.conf import settings
from django.test import SimpleTestCase

SCRIPT = Path(settings.BASE_DIR) / 'provisioning' / 'docker' / 'dav' / 'directory-sync.py'
CARD = 'BEGIN:VCARD\r\nVERSION:3.0\r\nUID:{uid}\r\nFN:{name}\r\nEND:VCARD\r\n'


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location('directory_sync', SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DirectorySyncTests(SimpleTestCase):
    def setUp(self) -> None:
        self.sync = load()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.source = base / 'runtime' / 'directory'
        self.root = base / 'collection-root'
        (self.source / 'people').mkdir(parents=True)
        self.root.mkdir()
        self.sync.SOURCE = self.source
        self.sync.ROOT = self.root

    # -- helpers -------------------------------------------------------------------------
    def publish(self, users: list[str], cards: dict[str, str], *, sha: str = 'a') -> None:
        for old in (self.source / 'people').glob('*.vcf'):
            old.unlink()
        for name, text in cards.items():
            (self.source / 'people' / name).write_text(text, newline='')
        (self.source / 'manifest.json').write_text(
            json.dumps({'enabled': True, 'name': 'Team', 'users': users, 'sha256': sha})
        )

    def book(self) -> Path:
        return self.root / '_directory' / 'people'

    def link(self, address: str) -> Path:
        return self.root / address / 'directory'

    # -- tests ---------------------------------------------------------------------------
    def test_builds_the_book_and_one_link_per_mailbox(self) -> None:
        self.publish(
            ['a@x.test', 'b@x.test'],
            {'1.vcf': CARD.format(uid='1', name='A'), '2.vcf': CARD.format(uid='2', name='B')},
        )
        self.sync.cycle(None)
        self.assertEqual(sorted(p.name for p in self.book().glob('*.vcf')), ['1.vcf', '2.vcf'])
        for address in ('a@x.test', 'b@x.test'):
            self.assertTrue(self.link(address).is_symlink())
            self.assertEqual(self.link(address).resolve(), self.book().resolve())
        props = json.loads((self.book() / '.Radicale.props').read_text())
        self.assertEqual(props['tag'], 'VADDRESSBOOK')
        self.assertEqual(props['D:displayname'], 'Team')

    def test_cards_are_copied_byte_for_byte(self) -> None:
        self.publish(['a@x.test'], {'1.vcf': CARD.format(uid='1', name='Ü, ñ')})
        self.sync.cycle(None)
        self.assertEqual(
            (self.book() / '1.vcf').read_bytes(), (self.source / 'people' / '1.vcf').read_bytes()
        )

    def test_a_second_cycle_changes_nothing(self) -> None:
        self.publish(['a@x.test'], {'1.vcf': CARD.format(uid='1', name='A')})
        state = self.sync.cycle(None)
        before = (self.book() / '1.vcf').stat().st_mtime_ns
        self.sync.cycle(state)
        self.assertEqual((self.book() / '1.vcf').stat().st_mtime_ns, before)

    def test_a_changed_card_is_replaced_and_a_removed_one_deleted(self) -> None:
        self.publish(
            ['a@x.test'],
            {'1.vcf': CARD.format(uid='1', name='A'), '2.vcf': CARD.format(uid='2', name='B')},
        )
        self.sync.cycle(None)
        self.publish(['a@x.test'], {'1.vcf': CARD.format(uid='1', name='A2')}, sha='b')
        self.sync.cycle('a')
        self.assertIn('FN:A2', (self.book() / '1.vcf').read_text())
        self.assertFalse((self.book() / '2.vcf').exists())

    def test_a_mailbox_that_leaves_loses_its_link_only(self) -> None:
        self.publish(['a@x.test', 'b@x.test'], {'1.vcf': CARD.format(uid='1', name='A')})
        self.sync.cycle(None)
        mine = self.root / 'b@x.test' / 'contacts'
        mine.mkdir()
        self.publish(['a@x.test'], {'1.vcf': CARD.format(uid='1', name='A')}, sha='b')
        self.sync.cycle('a')
        self.assertTrue(self.link('a@x.test').is_symlink())
        self.assertFalse(self.link('b@x.test').exists())
        self.assertTrue(mine.is_dir())  # their own address book is untouched

    def test_disabling_withdraws_book_and_links_but_not_personal_collections(self) -> None:
        self.publish(['a@x.test'], {'1.vcf': CARD.format(uid='1', name='A')})
        self.sync.cycle(None)
        personal = self.root / 'a@x.test' / 'family'
        personal.mkdir()
        (self.source / 'manifest.json').write_text(json.dumps({'enabled': False}))
        self.assertEqual(self.sync.cycle('a'), 'off')
        self.assertFalse((self.root / '_directory').exists())
        self.assertFalse(self.link('a@x.test').exists())
        self.assertTrue(personal.is_dir())

    def test_a_missing_manifest_also_withdraws(self) -> None:
        self.publish(['a@x.test'], {'1.vcf': CARD.format(uid='1', name='A')})
        self.sync.cycle(None)
        (self.source / 'manifest.json').unlink()
        self.assertEqual(self.sync.cycle('a'), 'off')
        self.assertFalse(self.link('a@x.test').exists())

    def test_a_people_own_directory_collection_is_never_replaced(self) -> None:
        own = self.root / 'a@x.test' / 'directory'
        own.mkdir(parents=True)
        (own / 'keep.vcf').write_text('x')
        self.publish(['a@x.test'], {'1.vcf': CARD.format(uid='1', name='A')})
        self.sync.cycle(None)
        self.assertFalse(own.is_symlink())
        self.assertTrue((own / 'keep.vcf').exists())

    def test_unsafe_addresses_are_ignored(self) -> None:
        bad = [
            '../evil@x.test',
            '/abs@x.test',
            '.hidden@x.test',
            'a\\b@x.test',
            'Upper@x.test',
            'nodomain',
            '',
        ]
        self.publish(bad + ['ok@x.test'], {})
        self.sync.cycle(None)
        names = sorted(p.name for p in self.root.iterdir())
        self.assertEqual(names, ['_directory', 'ok@x.test'])
        self.assertFalse((self.root.parent / 'evil@x.test').exists())

    def test_withdrawing_never_follows_a_link_out_of_the_tree(self) -> None:
        outside = Path(self._tmp.name) / 'outside'
        outside.mkdir()
        (outside / 'precious').write_text('keep')
        (self.root / 'a@x.test').mkdir()
        os.symlink(outside, self.root / 'a@x.test' / 'directory')  # not our link target
        self.publish(['a@x.test'], {})
        (self.source / 'manifest.json').write_text(json.dumps({'enabled': False}))
        self.sync.cycle('a')
        self.assertTrue((outside / 'precious').exists())
        self.assertTrue((self.root / 'a@x.test' / 'directory').is_symlink())  # not ours: kept
