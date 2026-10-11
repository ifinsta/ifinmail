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
    parts = name.split('/')
    if not all(parts) or any(part.startswith('.') for part in parts):
        raise ValueError(f'Invalid runtime file name: {name!r}')
    target = runtime_dir().joinpath(*parts)
    directory = target.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=f'.{parts[-1]}.')
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
    parts = name.split('/')
    if not all(parts) or any(part.startswith('.') for part in parts):
        return None
    path = runtime_dir().joinpath(*parts)
    try:
        return path.read_text(encoding='utf-8')
    except OSError:
        return None
