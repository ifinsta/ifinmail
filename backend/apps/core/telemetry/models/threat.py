"""Threat digest storage: one slim row per hour, and the findings that carry a threat.

Raw requests are never stored here. The hour row keeps counts and classes; a finding keeps what
decides an action (who, how much, a few correlation ids, where to tighten).
"""

from __future__ import annotations

from django.db import models

from backend.apps.core.base.models.base import CoreModel


class ThreatDigest(CoreModel):
    hour = models.DateTimeField(unique=True)  # start of the UTC hour this row summarises
    summary = models.JSONField(default=dict)  # counts and classes (threats.types.WindowSummary)
    findings_count = models.PositiveIntegerField(default=0)
    top_severity = models.PositiveSmallIntegerField(default=0)
    gist = models.TextField(blank=True, default='')
    gist_source = models.CharField(max_length=16, default='rules')  # "rules" | "assistant"
    priorities = models.JSONField(default=list)  # [{"key": ..., "why": ...}]
    correlations = models.JSONField(default=list)  # sentences that join findings
    ignored = models.JSONField(default=list)  # what the model advised to disregard
    tokens = models.PositiveIntegerField(default=0)
    summarised_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'ifinmail_threat_digest'
        ordering = ['-hour']

    def __str__(self) -> str:
        return f'{self.hour:%Y-%m-%d %H}:00 ({self.findings_count} findings)'


class ThreatFinding(CoreModel):
    OPEN = 'open'
    ACKNOWLEDGED = 'acknowledged'
    RESOLVED = 'resolved'

    key = models.CharField(max_length=190, unique=True)
    kind = models.CharField(max_length=40)
    severity = models.PositiveSmallIntegerField(default=0)
    subject = models.CharField(max_length=190, blank=True, default='')
    title = models.CharField(max_length=200)
    summary = models.TextField(blank=True, default='')
    count = models.PositiveIntegerField(default=0)
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField(db_index=True)
    evidence = models.JSONField(default=list)
    samples = models.JSONField(default=list)
    tighten = models.JSONField(default=list)  # [{"label", "where", "detail"}]
    status = models.CharField(max_length=16, default=OPEN, db_index=True)
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'ifinmail_threat_finding'
        ordering = ['-severity', '-last_seen']

    def __str__(self) -> str:
        return f'{self.kind} {self.subject} [{self.status}]'
