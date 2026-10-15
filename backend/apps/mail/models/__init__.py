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


class SandboxMessage(models.Model):
    """A message a sandbox API key sent: kept for inspection, never delivered (Developer sandbox).

    Retained for the plugin's number of days and capped per key; the oldest go first.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key_prefix = models.CharField(max_length=16, db_index=True)
    key_name = models.CharField(max_length=64, blank=True, default='')
    message_id = models.CharField(max_length=255)
    sender = models.CharField(max_length=254)
    to = models.JSONField(default=list)
    cc = models.JSONField(default=list)
    bcc = models.JSONField(default=list)
    reply_to = models.CharField(max_length=254, blank=True, default='')
    subject = models.CharField(max_length=998)
    text = models.TextField(blank=True, default='')
    html = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'mail_sandbox_message'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'{self.sender}: {self.subject[:40]}'

    @property
    def recipients(self) -> list[str]:
        return [*self.to, *self.cc, *self.bcc]


class WebhookEndpoint(models.Model):
    """Where the server POSTs events (signed JSON): delivery outcomes, received mail.

    An endpoint created in the console hears about every message sent through the API; one created
    with an API key hears only about that key's messages (``owner_prefix``). The signing secret is
    stored encrypted and shown once.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=64)
    url = models.URLField(max_length=500)
    secret = models.TextField()  # encrypted (plugin-secret:...)
    events = models.JSONField(default=list)  # event types, e.g. ["message.bounced"]
    owner_prefix = models.CharField(max_length=16, blank=True, default='', db_index=True)
    mailboxes = models.JSONField(default=list, blank=True)  # message.received: which mailboxes
    active = models.BooleanField(default=True)
    created_by = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    failing_since = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True, default='')

    class Meta:
        db_table = 'mail_webhook_endpoint'
        ordering = ['name']

    def __str__(self) -> str:
        return f'{self.name} ({self.url})'


class WebhookDelivery(models.Model):
    """One event for one endpoint, and the attempts to deliver it."""

    PENDING, DELIVERED, FAILED = 'pending', 'delivered', 'failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.CASCADE, related_name='deliveries'
    )
    event_id = models.CharField(max_length=40)  # evt_..., the same for every endpoint
    event_type = models.CharField(max_length=40)
    payload = models.JSONField()
    status = models.CharField(max_length=10, default=PENDING, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'mail_webhook_delivery'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['endpoint', 'event_id'], name='webhook_event_once')
        ]
