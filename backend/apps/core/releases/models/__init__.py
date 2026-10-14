from __future__ import annotations

from django.db import models
from django.utils import timezone

from backend.apps.core.base.models.base import CoreModel
from backend.apps.core.releases.types import CHANNEL_VALUES, DEFAULT_CHANNEL, PLATFORM_VALUES


class AppRelease(CoreModel):
    """One installable build of a client app, as devices and the download page see it.

    The file itself is a ``StoredFile`` (the only way files are kept); this row adds what a device
    needs to decide and verify an update: the monotonic ``version_code`` Android compares, the
    SHA-256 of the file and the certificate it is signed with.
    """

    platform = models.CharField(max_length=16, choices=[(v, v) for v in PLATFORM_VALUES])
    channel = models.CharField(
        max_length=16, choices=[(v, v) for v in CHANNEL_VALUES], default=DEFAULT_CHANNEL
    )
    version_code = models.PositiveIntegerField()
    version_name = models.CharField(max_length=64)
    package_name = models.CharField(max_length=255)
    min_sdk = models.PositiveSmallIntegerField(default=0)
    notes = models.TextField(blank=True, default='')
    stored_file = models.ForeignKey(
        'ifinmail_storage.StoredFile', on_delete=models.PROTECT, related_name='app_releases'
    )
    sha256 = models.CharField(max_length=64)
    size_bytes = models.BigIntegerField()
    signing_cert_sha256 = models.CharField(max_length=64, blank=True, default='')
    # Visible to devices and the download page. A withdrawn release stays on record.
    is_published = models.BooleanField(default=True)
    # Devices below a mandatory release must update before they keep working.
    mandatory = models.BooleanField(default=False)
    # Share of devices (0-100) that are offered this release; the rest keep the previous one.
    rollout_percent = models.PositiveSmallIntegerField(default=100)
    published_by = models.CharField(max_length=255, blank=True, default='')
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        ordering = ['-version_code']
        constraints = [
            models.UniqueConstraint(
                fields=['platform', 'channel', 'version_code'], name='releases_unique_version'
            ),
            models.CheckConstraint(
                condition=models.Q(rollout_percent__gte=0) & models.Q(rollout_percent__lte=100),
                name='releases_rollout_percent_range',
            ),
        ]
        indexes = [models.Index(fields=['platform', 'channel', 'is_published', '-version_code'])]

    def __str__(self) -> str:
        return f'{self.platform} {self.version_name} ({self.version_code}, {self.channel})'

    def mark_published(self) -> None:
        self.is_published = True
        if self.published_at is None:
            self.published_at = timezone.now()


class DeviceCheckin(CoreModel):
    """The last time one install asked for updates, and what it was running.

    ``device_id`` is a random identifier the app generates for itself on first run: it is not
    the Android ID, an account, or anything that identifies a person. It exists so the console can
    show how many devices run which version and so a staged rollout is stable per device.
    """

    platform = models.CharField(max_length=16)
    device_id = models.CharField(max_length=64)
    channel = models.CharField(max_length=16, default=DEFAULT_CHANNEL)
    version_code = models.PositiveIntegerField(default=0)
    version_name = models.CharField(max_length=64, blank=True, default='')
    sdk_int = models.PositiveSmallIntegerField(default=0)
    last_seen = models.DateTimeField(default=timezone.now)
    checks = models.PositiveIntegerField(default=0)

    class Meta:
        managed = True
        ordering = ['-last_seen']
        constraints = [
            models.UniqueConstraint(fields=['platform', 'device_id'], name='releases_unique_device')
        ]
        indexes = [models.Index(fields=['platform', 'last_seen'])]

    def __str__(self) -> str:
        return f'{self.platform}:{self.device_id[:8]} v{self.version_code}'


__all__ = ['AppRelease', 'DeviceCheckin']
