"""The catalog: bundled plugins plus approved submissions, newest approved version per plugin.

Bundled manifests are read once per process (they change only with a deploy). Approved submissions
come from one indexed query; their parsing is cached by content.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from backend.apps.core.plugins.models import PluginSubmission
from backend.apps.core.plugins.services import manifest as manifests
from backend.apps.core.plugins.services.manifest import PluginManifest
from backend.apps.core.plugins.types import ManifestError, PluginSource, SubmissionState

logger = logging.getLogger('backend')

BUNDLED_DIR = Path(__file__).resolve().parents[1] / 'bundled'


@dataclass(frozen=True)
class CatalogEntry:
    manifest: PluginManifest
    source: PluginSource
    submission_id: str = ''

    @property
    def plugin_id(self) -> str:
        return self.manifest.id


def core_version() -> tuple[int, int, int] | None:
    """The running release, or None for development builds (treated as compatible)."""
    from backend.apps.core.platform.services.updates import parse_version

    parsed = parse_version(os.environ.get('APP_VERSION', ''))
    return parsed[:3] if parsed else None


def is_compatible(manifest: PluginManifest) -> bool:
    if not manifest.requires_core:
        return True
    running = core_version()
    return running is None or running >= (
        manifests.parse_version(manifest.requires_core) or (0, 0, 0)
    )


class CatalogService:
    @staticmethod
    @lru_cache(maxsize=1)
    def _bundled() -> tuple[tuple[CatalogEntry, ...], tuple[tuple[str, str], ...]]:
        entries: list[CatalogEntry] = []
        errors: list[tuple[str, str]] = []
        for path in sorted(BUNDLED_DIR.glob('*/plugin.toml')):
            try:
                manifest = manifests.load(path.read_bytes())
            except (ManifestError, OSError) as exc:
                errors.append((path.parent.name, str(exc)))
                logger.error('Bundled plugin %s is invalid: %s', path.parent.name, exc)
                continue
            if manifest.id != path.parent.name:
                errors.append(
                    (path.parent.name, f'directory name must equal plugin.id ({manifest.id})')
                )
                continue
            entries.append(CatalogEntry(manifest=manifest, source=PluginSource.BUNDLED))
        return tuple(entries), tuple(errors)

    @classmethod
    def bundled(cls) -> tuple[CatalogEntry, ...]:
        return cls._bundled()[0]

    @classmethod
    def bundled_errors(cls) -> tuple[tuple[str, str], ...]:
        return cls._bundled()[1]

    @classmethod
    def bundled_ids(cls) -> frozenset[str]:
        return frozenset(e.plugin_id for e in cls.bundled())

    @classmethod
    def entries(cls) -> list[CatalogEntry]:
        """Everything installable, sorted by name."""
        found: dict[str, CatalogEntry] = {e.plugin_id: e for e in cls.bundled()}
        rows = PluginSubmission.objects.filter(state=SubmissionState.APPROVED).values_list(
            'id', 'plugin_id', 'manifest'
        )
        for row_id, plugin_id, text in rows:
            if plugin_id in found and found[plugin_id].source == PluginSource.BUNDLED:
                continue
            try:
                manifest = manifests.load(text)
            except ManifestError as exc:
                logger.warning('Approved plugin %s no longer validates: %s', plugin_id, exc)
                continue
            current = found.get(plugin_id)
            if current is None or manifest.version_tuple > current.manifest.version_tuple:
                found[plugin_id] = CatalogEntry(
                    manifest=manifest, source=PluginSource.SUBMITTED, submission_id=str(row_id)
                )
        return sorted(found.values(), key=lambda e: (e.manifest.name.lower(), e.plugin_id))

    @classmethod
    def get(cls, plugin_id: str) -> CatalogEntry | None:
        return next((e for e in cls.entries() if e.plugin_id == plugin_id), None)
