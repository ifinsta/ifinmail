"""Files exchanged with the mail containers through the shared runtime volume.

The api and worker containers write; postfix and certbot read. Writes are
atomic so a reader never sees a half-written file.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def runtime_dir() -> Path:
    return Path(os.environ.get('IFINMAIL_RUNTIME_DIR', '/var/lib/ifinmail/runtime'))


def write_runtime_file(name: str, text: str, *, mode: int = 0o644) -> Path:
    """Atomically write ``text`` to ``<runtime>/<name>`` and return its path."""
    if '/' in name or name.startswith('.'):
        raise ValueError(f'Invalid runtime file name: {name!r}')
    directory = runtime_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=f'.{name}.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, target)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise
    return target


def read_runtime_file(name: str) -> str | None:
    path = runtime_dir() / name
    try:
        return path.read_text(encoding='utf-8')
    except OSError:
        return None
