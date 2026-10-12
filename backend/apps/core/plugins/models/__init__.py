"""Plugin persistence: installations (desired state) and submissions (the review queue).

All reads and writes go through ``backend.apps.core.plugins.services``.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from backend.apps.core.base.models.base import CoreModel
from backend.apps.core.plugins.types import (
    LIVE_SUBMISSION_STATES,
    InstallationState,
    PluginSource,
    SubmissionState,
)


class PluginInstallation(CoreModel):
    """One installed plugin. No row = not installed.

    ``manifest`` is a snapshot of the manifest installed or last updated to, so rendering never
    depends on the catalog still listing the plugin. ``target_state`` is where the current (or
    failed) operation is heading; while ``state`` is transient, renderers treat the row as its
    target.
    """

    plugin_id = models.CharField(max_length=40, unique=True)
    version = models.CharField(max_length=20)
    source = models.CharField(max_length=16, choices=[(s.value, s.value) for s in PluginSource])
    manifest = models.TextField()
    settings = models.JSONField(default=dict)
    state = models.CharField(
        max_length=16, choices=[(s.value, s.value) for s in InstallationState], db_index=True
    )
    target_state = models.CharField(max_length=16, blank=True, default='')
    pending_operation = models.CharField(max_length=16, blank=True, default='')
    last_error = models.TextField(blank=True, default='')
    revision = models.PositiveIntegerField(default=1)
    installed_by = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        db_table = 'plugin_installation'
        ordering = ['plugin_id']

    def __str__(self) -> str:
        return f'{self.plugin_id} {self.version} ({self.state})'


class PluginSubmission(CoreModel):
    """A manifest submitted for review. Approved submissions are listed in the Marketplace."""

    plugin_id = models.CharField(max_length=40, db_index=True)
    version = models.CharField(max_length=20)
    name = models.CharField(max_length=60)
    manifest = models.TextField()
    manifest_sha256 = models.CharField(max_length=64)
    state = models.CharField(
        max_length=16,
        choices=[(s.value, s.value) for s in SubmissionState],
        default=SubmissionState.SUBMITTED,
        db_index=True,
    )
    submitted_by = models.CharField(max_length=255)
    submitter_note = models.TextField(blank=True, default='')
    reviewed_by = models.CharField(max_length=255, blank=True, default='')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'plugin_submission'
        ordering = ['-created_at']
        constraints = [
            # One live copy of an id + version; rejected/withdrawn ones may be resubmitted.
            models.UniqueConstraint(
                fields=['plugin_id', 'version'],
                condition=Q(state__in=sorted(s.value for s in LIVE_SUBMISSION_STATES)),
                name='plugin_submission_live_version_unique',
            )
        ]

    def __str__(self) -> str:
        return f'{self.plugin_id} {self.version} ({self.state})'
