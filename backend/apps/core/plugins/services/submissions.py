"""Submissions: the review queue behind the Marketplace.

Nothing is ever approved automatically. Approval is one explicit action by a reviewer and is
recorded in the audit trail. The manifest is validated again at approval time, because the core
(and the capabilities it offers) may have changed since it was submitted.
"""

from __future__ import annotations

import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.plugins.models import PluginSubmission
from backend.apps.core.plugins.services import manifest as manifests
from backend.apps.core.plugins.services.catalog import CatalogService
from backend.apps.core.plugins.services.manifest import PluginManifest
from backend.apps.core.plugins.types import (
    LIVE_SUBMISSION_STATES,
    SUBMISSION_TRANSITIONS,
    NotFoundError,
    PluginError,
    SubmissionState,
    TransitionError,
)

MAX_NOTE = 2000


def _uuid(value: object) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise NotFoundError('That submission does not exist.') from None


class SubmissionService:
    @staticmethod
    def list(state: str | None = None) -> list[PluginSubmission]:
        rows = PluginSubmission.objects.all()
        if state:
            rows = rows.filter(state=state)
        return list(rows)

    @staticmethod
    def pending_count() -> int:
        return PluginSubmission.objects.filter(state=SubmissionState.SUBMITTED).count()

    @staticmethod
    def get(submission_id: str) -> PluginSubmission:
        row = PluginSubmission.objects.filter(pk=_uuid(submission_id)).first()
        if row is None:
            raise NotFoundError('That submission does not exist.')
        return row

    @staticmethod
    def manifest_of(row: PluginSubmission) -> PluginManifest | None:
        try:
            return manifests.load(row.manifest)
        except PluginError:
            return None

    @classmethod
    def submit(cls, text: str | bytes, actor: str, note: str = '') -> PluginSubmission:
        manifest = manifests.load(text)  # raises ManifestError listing every problem
        cls._check_publishable(manifest)
        try:
            with transaction.atomic():
                row = PluginSubmission.objects.create(
                    plugin_id=manifest.id,
                    version=manifest.version,
                    name=manifest.name,
                    manifest=manifest.text,
                    manifest_sha256=manifest.sha256,
                    submitted_by=actor,
                    submitter_note=(note or '').strip()[:MAX_NOTE],
                )
        except IntegrityError:
            raise PluginError(
                f'{manifest.id} {manifest.version} is already submitted or published. '
                'Raise the version to submit a change.'
            ) from None
        AuditService.record(
            action='plugin_submitted', user=actor, detail=f'{manifest.id} {manifest.version}'
        )
        return row

    @classmethod
    def approve(cls, submission_id: str, actor: str, note: str = '') -> PluginSubmission:
        def check(row: PluginSubmission) -> None:
            manifest = manifests.load(row.manifest)  # still valid against today's core?
            cls._check_publishable(manifest, ignore=row.pk)

        return cls._transition(submission_id, 'approve', actor, note, check)

    @classmethod
    def reject(cls, submission_id: str, actor: str, note: str) -> PluginSubmission:
        if not (note or '').strip():
            raise PluginError('Say why it is rejected so the developer can fix it.')
        return cls._transition(submission_id, 'reject', actor, note)

    @classmethod
    def withdraw(cls, submission_id: str, actor: str, *, is_reviewer: bool) -> PluginSubmission:
        row = cls.get(submission_id)
        if row.submitted_by != actor and not is_reviewer:
            raise PluginError('Only the person who submitted it, or a reviewer, can withdraw it.')
        return cls._transition(submission_id, 'withdraw', actor, '')

    @classmethod
    def retire(cls, submission_id: str, actor: str, note: str = '') -> PluginSubmission:
        return cls._transition(submission_id, 'retire', actor, note)

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _check_publishable(manifest: PluginManifest, ignore: object = None) -> None:
        if manifest.id in CatalogService.bundled_ids():
            raise PluginError(f'"{manifest.id}" is a built-in plugin; choose another id.')
        live = PluginSubmission.objects.filter(
            plugin_id=manifest.id, state__in=list(LIVE_SUBMISSION_STATES)
        ).exclude(pk=ignore)
        if live.filter(version=manifest.version).exists():
            raise PluginError(
                f'{manifest.id} {manifest.version} is already submitted or published. '
                'Raise the version to submit a change.'
            )
        newest = max(
            (
                manifests.parse_version(v) or (0, 0, 0)
                for v in live.filter(state=SubmissionState.APPROVED).values_list(
                    'version', flat=True
                )
            ),
            default=None,
        )
        if newest is not None and manifest.version_tuple <= newest:
            raise PluginError(
                f'Version {manifest.version} is not newer than the published '
                f'{".".join(map(str, newest))}.'
            )

    @staticmethod
    def _transition(submission_id, action, actor, note, check=None) -> PluginSubmission:
        sources, target = SUBMISSION_TRANSITIONS[action]
        with transaction.atomic():
            row = (
                PluginSubmission.objects.select_for_update().filter(pk=_uuid(submission_id)).first()
            )
            if row is None:
                raise NotFoundError('That submission does not exist.')
            if row.state not in sources:
                raise TransitionError(f'Cannot {action} a submission that is {row.state}.')
            if check is not None:
                check(row)
            previous = row.state
            row.state = target
            if action != 'withdraw':
                row.reviewed_by = actor
                row.reviewed_at = timezone.now()
                row.review_note = (note or '').strip()[:MAX_NOTE]
            row.save()
        AuditService.record(
            action=f'plugin_submission_{action}',
            user=actor,
            detail=f'{row.plugin_id} {row.version}: {previous} -> {target}',
        )
        return row
