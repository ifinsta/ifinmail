import uuid

from django.db import models

from backend.apps.mail.types.quota import DEFAULT_QUOTA_BYTES


class Mailbox(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    domain = models.ForeignKey(
        'domains.Domain',
        on_delete=models.CASCADE,
        db_column='domain_id',
    )
    local_part = models.CharField(max_length=128)
    # 0 = unlimited; new mailboxes default to 1024 MB (see types/quota.py).
    quota_bytes = models.BigIntegerField(default=DEFAULT_QUOTA_BYTES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'mailboxes'
        unique_together = [('domain', 'local_part')]

    def __str__(self) -> str:
        return f'{self.local_part}@{self.domain.name}'


class Alias(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    domain = models.ForeignKey(
        'domains.Domain',
        on_delete=models.CASCADE,
        db_column='domain_id',
    )
    source = models.CharField(max_length=128)
    destination = models.CharField(max_length=255)

    class Meta:
        managed = False
        db_table = 'aliases'
        verbose_name_plural = 'aliases'
        ordering = ['domain', 'source']

    def __str__(self) -> str:
        return f'{self.source} → {self.destination}'
