#!/usr/bin/env python3
"""Mirror the console's contact directory into Radicale as one read-only address book.

The console writes ``<runtime>/directory/manifest.json`` and ``people/<id>.vcf`` (see
backend/apps/accounts/services/directory.py). This process, running beside Radicale, keeps:

    collection-root/_directory/people/        the address book: one .vcf per person
    collection-root/<address>/directory   ->  ../_directory/people   (symlink, one per mailbox)

so the address book shows up in every mailbox's CardDAV home under the name "directory"
(rights make it read-only; see the rights file). Withdrawing is the reverse: when the manifest
says disabled or goes missing, the book and the links are removed. Only the standard library is
used, and every write is an atomic rename so Radicale never reads half a file.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

SOURCE = Path(os.environ.get('DIRECTORY_SOURCE', '/var/lib/ifinmail/runtime/directory'))
ROOT = Path(os.environ.get('RADICALE_ROOT', '/var/lib/radicale/collections/collection-root'))
HEARTBEAT = Path(os.environ.get('DIRECTORY_HEARTBEAT', '/tmp/directory-sync.heartbeat'))
INTERVAL = float(os.environ.get('DIRECTORY_INTERVAL', '5'))
LINK = 'directory'
HOME = '_directory'
BOOK = 'people'
TARGET = f'../{HOME}/{BOOK}'


def log(message: str) -> None:
    print(f'directory-sync: {message}', flush=True)


def safe_name(address: str) -> bool:
    """A mailbox address that can be a directory name: no separators, no dot-prefix."""
    return (
        bool(address)
        and '@' in address
        and not address.startswith('.')
        and not any(ch in address for ch in '/\\\x00')
        and address == address.lower()
        and len(address) <= 254
    )


def atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(f'.{path.name}.tmp')
    tmp.write_bytes(data)
    os.replace(tmp, path)


def read_manifest() -> dict | None:
    try:
        data = json.loads((SOURCE / 'manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get('enabled'):
        return None
    return data


def withdraw() -> int:
    """Remove the address book and every link to it. Returns how many things were removed."""
    removed = 0
    if ROOT.is_dir():
        for home in ROOT.iterdir():
            link = home / LINK
            if link.is_symlink() and os.readlink(link) == TARGET:
                link.unlink()
                removed += 1
    book_home = ROOT / HOME
    if book_home.is_dir():
        shutil.rmtree(book_home, ignore_errors=True)
        removed += 1
    return removed


def book_props(name: str) -> bytes:
    props = {
        'tag': 'VADDRESSBOOK',
        'D:displayname': name,
        'CR:addressbook-description': 'Everyone on this server. Read-only; managed by the console.',
    }
    return json.dumps(props, sort_keys=True).encode('utf-8')


def sync_book(manifest: dict) -> tuple[int, int]:
    book = ROOT / HOME / BOOK
    book.mkdir(parents=True, exist_ok=True)
    props = book / '.Radicale.props'
    wanted = book_props(str(manifest.get('name') or 'Directory')[:120])
    if not props.exists() or props.read_bytes() != wanted:
        atomic_write(props, wanted)
    written = removed = 0
    source_cards = {p.name: p for p in (SOURCE / 'people').glob('*.vcf')}
    for name, src in source_cards.items():
        data = src.read_bytes()
        dest = book / name
        if dest.exists() and dest.read_bytes() == data:
            continue
        atomic_write(dest, data)
        written += 1
    for dest in book.glob('*.vcf'):
        if dest.name not in source_cards:
            dest.unlink()
            removed += 1
    return written, removed


def sync_links(users: list[str]) -> tuple[int, int]:
    wanted = {u for u in users if safe_name(u)}
    made = dropped = 0
    ROOT.mkdir(parents=True, exist_ok=True)
    for address in sorted(wanted):
        home = ROOT / address
        home.mkdir(exist_ok=True)
        link = home / LINK
        if link.is_symlink():
            if os.readlink(link) == TARGET:
                continue
            link.unlink()
        elif link.exists():
            log(f'{address} has its own "{LINK}" collection; leaving it alone')
            continue
        os.symlink(TARGET, link)
        made += 1
    for home in ROOT.iterdir():
        if home.name in wanted or home.name == HOME or not home.is_dir():
            continue
        link = home / LINK
        if link.is_symlink() and os.readlink(link) == TARGET:
            link.unlink()
            dropped += 1
    return made, dropped


def cycle(last: str | None) -> str | None:
    manifest = read_manifest()
    if manifest is None:
        if last != 'off':
            log(f'withdrawn ({withdraw()} removed)')
        return 'off'
    written, removed = sync_book(manifest)
    made, dropped = sync_links([str(u) for u in manifest.get('users', [])])
    state = str(manifest.get('sha256', ''))
    if written or removed or made or dropped or state != last:
        log(
            f'published {len(manifest.get("users", []))} people '
            f'(cards +{written} -{removed}, links +{made} -{dropped})'
        )
    return state or 'on'


def main() -> int:
    log(f'watching {SOURCE}')
    last: str | None = None
    while True:
        try:
            last = cycle(last)
        except Exception as exc:  # keep going: the next cycle may succeed
            log(f'error: {exc!r}')
        with contextlib.suppress(OSError):
            HEARTBEAT.touch()
        time.sleep(INTERVAL)


if __name__ == '__main__':
    sys.exit(main())
