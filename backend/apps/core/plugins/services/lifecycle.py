"""Installation lifecycle: the state machine, effects and reconciliation.

Every operation runs in three phases (see references/state-machines.md):

1. Validate, then in one transaction (all plugin operations serialised by a lock) move the row to
   its transient state, store the desired values and bump the revision.
2. Publish every extension point from the database. Transient rows count as their target.
3. In a second transaction, settle the row on its target (or delete it after an uninstall).

A failure in phase 2 leaves the row ``failed`` with the target it was heading for; ``retry`` or
``uninstall`` recover it. A request that dies between phases leaves a transient row that the next
operation, page view or the reconcile job finishes once it is older than ``STALE_SECONDS``.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.plugins.models import PluginInstallation
from backend.apps.core.plugins.services import manifest as manifests
from backend.apps.core.plugins.services import registry
from backend.apps.core.plugins.services.catalog import CatalogEntry, CatalogService, is_compatible
from backend.apps.core.plugins.services.manifest import PluginManifest
from backend.apps.core.plugins.types import (
    ABSENT,
    STALE_SECONDS,
    TRANSIENT_STATES,
    TRANSITIONS,
    ApplyStatus,
    BusyError,
    ConflictError,
    InstallationState,
    NotFoundError,
    Operation,
    PluginError,
    StaleRevisionError,
    TransitionError,
)

logger = logging.getLogger('backend')

_LOCK_KEY = 0x1F_1A_6E  # advisory lock id shared by every plugin operation (PostgreSQL)

_STATE_WORDS = {
    ABSENT: 'not installed',
    InstallationState.INSTALLING: 'installing',
    InstallationState.ENABLED: 'enabled',
    InstallationState.DISABLED: 'disabled',
    InstallationState.APPLYING: 'applying a change',
    InstallationState.UNINSTALLING: 'uninstalling',
    InstallationState.FAILED: 'failed',
}


@dataclass(frozen=True)
class OperationResult:
    plugin_id: str
    operation: Operation
    from_state: str
    to_state: str


def _effective_state(row: PluginInstallation) -> str:
    """What the renderers should treat this row as."""
    if row.state in TRANSIENT_STATES:
        return row.target_state or ABSENT
    return row.state


def _global_lock() -> None:
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [_LOCK_KEY])


def _stale(row: PluginInstallation) -> bool:
    return row.updated_at < timezone.now() - timedelta(seconds=STALE_SECONDS)


class InstallationService:
    # ------------------------------------------------------------------ queries

    @staticmethod
    def get(plugin_id: str) -> PluginInstallation | None:
        row = PluginInstallation.objects.filter(plugin_id=plugin_id).first()
        if row is not None and row.state in TRANSIENT_STATES and _stale(row):
            InstallationService._finish_stale(row)
            row = PluginInstallation.objects.filter(plugin_id=plugin_id).first()
        return row

    @staticmethod
    def all() -> list[PluginInstallation]:
        return list(PluginInstallation.objects.all())

    @staticmethod
    def manifest_of(row: PluginInstallation) -> PluginManifest:
        return manifests.load(row.manifest)

    @staticmethod
    def apply_status() -> dict[str, ApplyStatus]:
        return {point.key: point.applied_status() for point in registry.points()}

    @staticmethod
    def update_available(row: PluginInstallation, entry: CatalogEntry | None) -> bool:
        if entry is None:
            return False
        return entry.manifest.version_tuple > (manifests.parse_version(row.version) or (0, 0, 0))

    # ------------------------------------------------------------------ operations

    @classmethod
    def install(cls, plugin_id: str, settings: Mapping[str, object], actor: str) -> OperationResult:
        entry = CatalogService.get(plugin_id)
        if entry is None:
            raise NotFoundError(f'No plugin "{plugin_id}" is available.')
        manifest = entry.manifest
        cls._check_compatible(manifest)
        cleaned = manifests.clean_settings(manifest, settings)
        manifests.rendered_values(manifest, cleaned)

        def prepare(row: PluginInstallation | None) -> dict:
            cls._check_conflicts(manifest, exclude=plugin_id)
            return {
                'version': manifest.version,
                'source': entry.source,
                'manifest': manifest.text,
                'settings': cleaned,
                'installed_by': actor,
            }

        return cls._run(plugin_id, Operation.INSTALL, actor, None, prepare)

    @classmethod
    def configure(
        cls, plugin_id: str, settings: Mapping[str, object], actor: str, revision: int | None = None
    ) -> OperationResult:
        row = cls._require(plugin_id)
        manifest = cls.manifest_of(row)
        cleaned = manifests.clean_settings(manifest, settings)
        manifests.rendered_values(manifest, cleaned)
        if cleaned == row.settings and row.state in (
            InstallationState.ENABLED,
            InstallationState.DISABLED,
        ):
            return OperationResult(plugin_id, Operation.CONFIGURE, row.state, row.state)
        return cls._run(
            plugin_id, Operation.CONFIGURE, actor, revision, lambda r: {'settings': cleaned}
        )

    @classmethod
    def enable(cls, plugin_id: str, actor: str, revision: int | None = None) -> OperationResult:
        row = cls._require(plugin_id)
        manifest = cls.manifest_of(row)

        def prepare(r: PluginInstallation | None) -> dict:
            cls._check_compatible(manifest)
            # Settings may refer to something that has gone since (e.g. a deleted mailbox).
            manifests.rendered_values(manifest, manifests.clean_settings(manifest, r.settings))
            cls._check_conflicts(manifest, exclude=plugin_id)
            return {}

        return cls._run(plugin_id, Operation.ENABLE, actor, revision, prepare)

    @classmethod
    def disable(cls, plugin_id: str, actor: str, revision: int | None = None) -> OperationResult:
        cls._require(plugin_id)
        return cls._run(plugin_id, Operation.DISABLE, actor, revision, lambda r: {})

    @classmethod
    def update(
        cls,
        plugin_id: str,
        actor: str,
        revision: int | None = None,
        settings: Mapping[str, object] | None = None,
    ) -> OperationResult:
        row = cls._require(plugin_id)
        entry = CatalogService.get(plugin_id)
        if not cls.update_available(row, entry):
            raise TransitionError(f'{plugin_id} is already at the newest available version.')
        manifest = entry.manifest
        cls._check_compatible(manifest)
        # Carry current values over; new settings take their defaults; removed ones are dropped.
        merged = {**row.settings, **(settings or {})}
        cleaned = manifests.clean_settings(manifest, merged)
        manifests.rendered_values(manifest, cleaned)

        def prepare(r: PluginInstallation | None) -> dict:
            if r.state == InstallationState.ENABLED:
                cls._check_conflicts(manifest, exclude=plugin_id)
            return {
                'version': manifest.version,
                'source': entry.source,
                'manifest': manifest.text,
                'settings': cleaned,
            }

        return cls._run(plugin_id, Operation.UPDATE, actor, revision, prepare)

    @classmethod
    def retry(cls, plugin_id: str, actor: str, revision: int | None = None) -> OperationResult:
        row = cls._require(plugin_id)
        manifest = cls.manifest_of(row)

        def prepare(r: PluginInstallation | None) -> dict:
            if r.target_state == InstallationState.ENABLED:
                manifests.rendered_values(manifest, manifests.clean_settings(manifest, r.settings))
                cls._check_conflicts(manifest, exclude=plugin_id)
            return {}

        return cls._run(plugin_id, Operation.RETRY, actor, revision, prepare)

    @classmethod
    def uninstall(cls, plugin_id: str, actor: str, revision: int | None = None) -> OperationResult:
        cls._require(plugin_id)
        return cls._run(plugin_id, Operation.UNINSTALL, actor, revision, lambda r: {})

    # ------------------------------------------------------------------ reconciliation

    @classmethod
    def publish_all(cls) -> dict[str, bool]:
        """Render every extension point from the database; write only what changed."""
        values: dict[str, dict[str, str]] = {p.key: {} for p in registry.points()}
        for row in PluginInstallation.objects.all():
            if _effective_state(row) != InstallationState.ENABLED:
                continue
            try:
                manifest = manifests.load(row.manifest)
                rendered = manifests.rendered_values(manifest, row.settings)
            except PluginError as exc:
                # Never let one broken row block the others; it is reported on its page.
                logger.warning('Plugin %s cannot be rendered: %s', row.plugin_id, exc)
                continue
            for point_key, pairs in rendered.items():
                bucket = values.setdefault(point_key, {})
                for key, value in pairs.items():
                    bucket.setdefault(key, value)  # conflicts are refused earlier; first wins
        changed: dict[str, bool] = {}
        for point in registry.points():
            changed[point.key] = point.publish(point.render(values.get(point.key, {})))
        return changed

    @classmethod
    def reconcile(cls) -> dict[str, object]:
        """Finish stale operations and republish every point (idempotent, cheap)."""
        finished = 0
        for row in PluginInstallation.objects.filter(state__in=list(TRANSIENT_STATES)):
            if _stale(row):
                cls._finish_stale(row)
                finished += 1
        return {'finished_stale': finished, 'written': cls.publish_all()}

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _require(plugin_id: str) -> PluginInstallation:
        row = InstallationService.get(plugin_id)
        if row is None:
            raise NotFoundError(f'{plugin_id} is not installed.')
        return row

    @staticmethod
    def _check_compatible(manifest: PluginManifest) -> None:
        if not is_compatible(manifest):
            raise PluginError(
                f'{manifest.name} {manifest.version} needs ifinmail {manifest.requires_core} '
                'or newer.'
            )

    @staticmethod
    def _check_conflicts(manifest: PluginManifest, *, exclude: str) -> None:
        wanted = manifest.claimed_keys()
        for other in PluginInstallation.objects.exclude(plugin_id=exclude):
            if _effective_state(other) != InstallationState.ENABLED:
                continue
            try:
                theirs = manifests.load(other.manifest).claimed_keys()
            except PluginError:
                continue
            clash = sorted(wanted & theirs)
            if clash:
                point, key = clash[0]
                raise ConflictError(
                    f'{other.plugin_id} already sets {key} at {point}. Disable it first.'
                )

    @classmethod
    def _run(
        cls,
        plugin_id: str,
        operation: Operation,
        actor: str,
        revision: int | None,
        prepare: Callable[[PluginInstallation | None], dict],
    ) -> OperationResult:
        sources, transient, target = TRANSITIONS[operation]
        existing = PluginInstallation.objects.filter(plugin_id=plugin_id).first()
        if existing is not None and existing.state in TRANSIENT_STATES and _stale(existing):
            cls._finish_stale(existing)
        try:
            with transaction.atomic():
                _global_lock()
                row = (
                    PluginInstallation.objects.select_for_update()
                    .filter(plugin_id=plugin_id)
                    .first()
                )
                current = row.state if row is not None else ABSENT
                if current in TRANSIENT_STATES:
                    raise BusyError(
                        f'{plugin_id} is busy ({_STATE_WORDS[current]}). Try again shortly.'
                    )
                if current not in sources:
                    raise TransitionError(
                        f'Cannot {operation.value} {plugin_id}: '
                        f'it is {_STATE_WORDS.get(current, current)}.'
                    )
                if revision is not None and row is not None and row.revision != revision:
                    raise StaleRevisionError(
                        f'{plugin_id} was changed by someone else. Reload the page and try again.'
                    )
                updates = prepare(row)
                if operation == Operation.RETRY:
                    target = row.target_state or InstallationState.ENABLED
                    if target == ABSENT:
                        transient = InstallationState.UNINSTALLING
                if target is None:
                    target = current
                if row is None:
                    row = PluginInstallation(plugin_id=plugin_id)
                for field, value in updates.items():
                    setattr(row, field, value)
                row.state = transient
                row.target_state = target
                row.pending_operation = operation.value
                row.last_error = ''
                row.revision = (row.revision or 0) + 1 if row.pk and current != ABSENT else 1
                row.save()
        except IntegrityError:
            raise BusyError(f'{plugin_id} is being installed by another request.') from None
        return cls._effects_then_settle(row, operation, actor, from_state=current)

    @classmethod
    def _effects_then_settle(
        cls, row: PluginInstallation, operation: Operation, actor: str, *, from_state: str
    ) -> OperationResult:
        try:
            cls.publish_all()
        except Exception as exc:  # any I/O or render failure
            message = f'Could not apply {row.plugin_id}: {exc}'
            with transaction.atomic():
                PluginInstallation.objects.filter(pk=row.pk).update(
                    state=InstallationState.FAILED,
                    last_error=message[:2000],
                    pending_operation='',
                    updated_at=timezone.now(),
                )
            AuditService.record(
                action='plugin_failed',
                user=actor,
                detail=(
                    f'{row.plugin_id} {row.version}: {operation.value} {from_state} -> failed '
                    f'({exc})'
                ),
                severity='err',
            )
            try:
                cls.publish_all()  # put the files back in line with the database
            except Exception:
                logger.exception('Plugin reconcile after a failure also failed')
            raise PluginError(message) from exc
        to_state = cls._settle(row)
        AuditService.record(
            action=f'plugin_{operation.value}',
            user=actor,
            detail=f'{row.plugin_id} {row.version}: {from_state} -> {to_state}',
        )
        return OperationResult(row.plugin_id, operation, from_state, to_state)

    @staticmethod
    def _settle(row: PluginInstallation) -> str:
        with transaction.atomic():
            locked = PluginInstallation.objects.select_for_update().filter(pk=row.pk).first()
            if locked is None:
                return ABSENT
            target = locked.target_state or InstallationState.ENABLED
            if target == ABSENT:
                locked.delete()
                return ABSENT
            locked.state = target
            locked.target_state = ''
            locked.pending_operation = ''
            locked.save()
            return target

    @classmethod
    def _finish_stale(cls, row: PluginInstallation) -> None:
        """Complete an operation whose request died between phases."""
        operation = Operation(row.pending_operation) if row.pending_operation else Operation.RETRY
        logger.warning('Finishing stale plugin operation %s on %s', operation, row.plugin_id)
        # A failure is recorded on the row (state failed) by _effects_then_settle.
        with contextlib.suppress(PluginError):
            cls._effects_then_settle(row, operation, 'system', from_state=row.state)
