from django.db import models

from backend.apps.core.base.models.base import CoreModel


class DNSProviderConfig(CoreModel):
    """Encrypted DNS provider credentials."""

    id = models.BigAutoField(primary_key=True)
    provider = models.CharField(
        max_length=32,
        unique=True,
        choices=[
            ('cloudflare', 'Cloudflare'),
            ('porkbun', 'Porkbun'),
            ('digitalocean', 'DigitalOcean'),
        ],
    )
    credentials = models.JSONField(default=dict)

    class Meta:
        managed = False
        db_table = 'dns_provider_config'

    def __str__(self) -> str:
        return f'DNS: {self.provider}'


class DNSZone(CoreModel):
    """A zone this server answers for, plus the state used to version it."""

    zone = models.CharField(max_length=255, unique=True)
    mode = models.CharField(
        max_length=16,
        choices=[('authoritative', 'Authoritative'), ('external', 'External')],
        default='authoritative',
    )
    serial = models.BigIntegerField(default=0)
    content_hash = models.CharField(max_length=64, blank=True, default='')
    dnssec = models.BooleanField(default=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'dns_zones'
        ordering = ['zone']

    def __str__(self) -> str:
        return f'{self.zone} ({self.mode})'


class CustomDNSRecord(CoreModel):
    """A record an administrator added to a zone (in addition to the managed ones)."""

    zone = models.CharField(max_length=255, db_index=True)
    name = models.CharField(max_length=255, default='@')
    rtype = models.CharField(max_length=8)
    value = models.TextField()
    ttl = models.PositiveIntegerField(default=3600)
    priority = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = 'dns_custom_records'
        ordering = ['zone', 'name', 'rtype']
        unique_together = [('zone', 'name', 'rtype', 'value')]

    def __str__(self) -> str:
        return f'{self.name}.{self.zone} {self.rtype} {self.value}'
