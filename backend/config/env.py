"""Environment helpers shared across apps.

Two jobs live here, both deliberately dependency-free so settings modules can
import this file while Django is still booting:

* ``load_dotenv`` fills ``os.environ`` from a ``.env`` file for local runs —
  real environment variables always win, and empty values count as unset.
* ``primary_domain`` resolves the configured mail domain with one precedence
  everywhere (compose uses ``DOMAIN`` first, falling back to ``MAIL_DOMAIN``).
"""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | os.PathLike[str]) -> None:
    """Load ``KEY=VALUE`` lines from ``path`` into ``os.environ``.

    Existing environment variables are never overwritten and empty values are
    ignored, so ``cp .env.example .env`` leaves placeholders like an empty
    ``DJANGO_SECRET_KEY`` to the normal fallbacks.
    """
    try:
        text = Path(path).read_text(encoding='utf-8')
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        key = key.strip()
        if key.startswith('export '):
            key = key[len('export ') :].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key and value:
            os.environ.setdefault(key, value)


def primary_domain() -> str:
    """The server's primary mail domain, or ``''`` when unset.

    Precedence mirrors provisioning and compose: ``DOMAIN`` first, then
    ``MAIL_DOMAIN`` (the two are normally the same value).
    """
    return os.environ.get('DOMAIN', '').strip() or os.environ.get('MAIL_DOMAIN', '').strip()
