"""Models for backend services.

Contains the AuditEvent model used by AuditService for persistent
audit trail storage.
"""

import uuid

from django.db import models
from django.utils import timezone


class AuditEvent(models.Model):
    """Persistent audit trail event.

    Managed by Django (not read from init-db.sh).  Retention is time-based
    (``AuditService.retention_days``), and every row carries a hash link to
    the one before it so edits or deletions inside the window are detectable
    (``AuditService.verify_chain``).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    time = models.DateTimeField(default=timezone.now, db_index=True)
    user = models.CharField(max_length=255)
    action = models.CharField(max_length=255)
    detail = models.TextField(blank=True)
    severity = models.CharField(max_length=32, default='info')
    # Tamper evidence. ``seq`` orders the chain; rows written before the chain
    # existed have ``seq`` NULL and sit outside it.
    seq = models.BigIntegerField(null=True, blank=True, unique=True)
    prev_hash = models.CharField(max_length=64, blank=True, default='')
    entry_hash = models.CharField(max_length=64, blank=True, default='')

    class Meta:
        managed = True
        db_table = 'ifinmail_audit_event'
        ordering = ['-time']

    def __str__(self) -> str:
        return f'{self.action} by {self.user} at {self.time}'
