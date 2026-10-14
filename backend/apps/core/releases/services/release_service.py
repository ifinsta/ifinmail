"""ReleaseService — single interface for app releases and device update checks.

Publishing validates the upload as an installable APK of the right application, keeps the
signing certificate stable across releases (a device refuses an update signed with another key),
stores the file through ``StorageService`` and records an audit entry. Checking answers what one
device should do, applying channel, minimum SDK, mandatory floor and staged rollout.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, QuerySet
from django.db.utils import DatabaseError
from django.utils import timezone

from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.releases.models import AppRelease, DeviceCheckin
from backend.apps.core.releases.services.apk import ApkError, inspect_apk
from backend.apps.core.releases.types import (
    ACTIVE_DEVICE_DAYS,
    APK_CONTENT_TYPE,
    CHANNEL_VALUES,
    CHECKIN_RETENTION_DAYS,
    DEFAULT_ANDROID_PACKAGE,
    DEFAULT_CHANNEL,
    PLATFORM_VALUES,
    Platform,
)
from backend.apps.core.storage.services import StorageService
from backend.apps.core.types.enums import EntityType, StorageVisibility

logger = logging.getLogger('backend')

# The update manifest is public and a check-in needs no credentials, so anyone can invent device
# ids. Past this many tracked devices new ones are not recorded (known devices still update), so
# the table cannot grow without bound between the daily prunes.
MAX_TRACKED_DEVICES = 100_000


@dataclass(frozen=True)
class UpdateDecision:
    """What one device is told: the build to offer (if any) and whether it must be taken."""

    latest: AppRelease | None
    update_available: bool
    required: bool
    minimum_version_code: int


@dataclass(frozen=True)
class AdoptionRow:
    version_code: int
    version_name: str
    devices: int


def rollout_bucket(device_id: str, platform: str, channel: str, version_code: int) -> int:
    """A stable 0-99 position for one device in one release's staged rollout.

    The release is part of the hash so a device is not always first (or always last) in line.
    """
    material = f'{platform}:{channel}:{version_code}:{device_id}'.encode()
    return int(hashlib.sha256(material).hexdigest()[:8], 16) % 100


class ReleaseService:
    # -- configuration ---------------------------------------------------------------------

    @staticmethod
    def expected_package(platform: str) -> str:
        if platform == Platform.ANDROID.value:
            configured = getattr(settings, 'RELEASES_ANDROID_PACKAGE', '') or ''
            return str(configured).strip() or DEFAULT_ANDROID_PACKAGE
        raise ValueError(f'Unsupported platform: {platform}.')

    # -- reading ---------------------------------------------------------------------------

    @staticmethod
    def list_releases(
        platform: str = Platform.ANDROID.value,
        channel: str | None = None,
        *,
        published_only: bool = False,
    ) -> QuerySet[AppRelease]:
        rows = AppRelease.objects.filter(platform=platform).select_related('stored_file')
        if channel:
            rows = rows.filter(channel=channel)
        if published_only:
            rows = rows.filter(is_published=True)
        return rows.order_by('-version_code')

    @staticmethod
    def get(platform: str, channel: str, version_code: int) -> AppRelease | None:
        return (
            AppRelease.objects.filter(
                platform=platform, channel=channel, version_code=version_code
            )
            .select_related('stored_file')
            .first()
        )

    @staticmethod
    def latest_published(
        platform: str = Platform.ANDROID.value, channel: str = DEFAULT_CHANNEL
    ) -> AppRelease | None:
        try:
            return ReleaseService.list_releases(platform, channel, published_only=True).first()
        except DatabaseError:
            logger.exception('Failed to read the latest release')
            return None

    @staticmethod
    def download_path(release: AppRelease) -> str:
        """Site-relative URL of the file (``/media/...``); nginx serves it from disk."""
        return str(release.stored_file.file.url)

    # -- publishing ------------------------------------------------------------------------

    @staticmethod
    def publish(
        *,
        upload: UploadedFile,
        platform: str = Platform.ANDROID.value,
        channel: str = DEFAULT_CHANNEL,
        notes: str = '',
        mandatory: bool = False,
        rollout_percent: int = 100,
        publish: bool = True,
        actor: str | None = None,
    ) -> AppRelease:
        """Validate ``upload`` and make it a release. Raises ``ValueError`` (safe to show)."""
        if platform not in PLATFORM_VALUES:
            raise ValueError(f'Unsupported platform: {platform}.')
        if channel not in CHANNEL_VALUES:
            raise ValueError(f'Unknown channel: {channel}. Use one of: {", ".join(CHANNEL_VALUES)}.')
        if not 0 <= rollout_percent <= 100:
            raise ValueError('The rollout share must be between 0 and 100.')
        if mandatory and rollout_percent != 100:
            raise ValueError('A mandatory release goes to every device; set the rollout to 100.')

        try:
            info = inspect_apk(upload.file)  # type: ignore[arg-type]
        except ApkError as exc:
            raise ValueError(str(exc)) from exc

        expected = ReleaseService.expected_package(platform)
        if info.package != expected:
            raise ValueError(
                f'This APK is for {info.package}, but this server distributes {expected}.'
            )
        if not info.signed:
            raise ValueError(
                'This APK is not signed. Sign the release build (a debug-signed or unsigned '
                'APK cannot update an installed app).'
            )
        if AppRelease.objects.filter(
            platform=platform, channel=channel, version_code=info.version_code
        ).exists():
            raise ValueError(
                f'Version code {info.version_code} already exists on the {channel} channel. '
                'Raise versionCode in the app build and publish again.'
            )
        ReleaseService._require_same_signer(platform, info.signing_cert_sha256)

        upload.name = f'ifinmail-{info.version_code}.apk'
        upload.content_type = APK_CONTENT_TYPE
        upload.file.seek(0)
        stored = StorageService.upload(
            file=upload, user=None, entity_type=EntityType.APP_RELEASE.value
        )
        try:
            with transaction.atomic():
                stored.visibility = StorageVisibility.PUBLIC.value
                stored.save(update_fields=['visibility', 'updated_at'])
                release = AppRelease(
                    platform=platform,
                    channel=channel,
                    version_code=info.version_code,
                    version_name=info.version_name or str(info.version_code),
                    package_name=info.package,
                    min_sdk=info.min_sdk,
                    notes=notes.strip(),
                    stored_file=stored,
                    sha256=info.sha256,
                    size_bytes=info.size_bytes,
                    signing_cert_sha256=info.signing_cert_sha256,
                    is_published=publish,
                    mandatory=mandatory,
                    rollout_percent=rollout_percent,
                    published_by=(actor or '')[:255],
                )
                if publish:
                    release.mark_published()
                release.save()
                stored.entity_id = release.id
                stored.save(update_fields=['entity_id', 'updated_at'])
        except IntegrityError as exc:
            ReleaseService._discard_file(stored)
            raise ValueError(
                f'Version code {info.version_code} already exists on the {channel} channel.'
            ) from exc
        except Exception:
            ReleaseService._discard_file(stored)
            raise

        AuditService.record(
            action='app_release_published' if publish else 'app_release_uploaded',
            user=actor,
            detail=f'{release} sha256={release.sha256[:12]} mandatory={mandatory} '
            f'rollout={rollout_percent}',
        )
        return release

    @staticmethod
    def _require_same_signer(platform: str, certificate: str) -> None:
        previous = (
            AppRelease.objects.filter(platform=platform)
            .exclude(signing_cert_sha256='')
            .order_by('-version_code')
            .values_list('signing_cert_sha256', flat=True)
            .first()
        )
        if previous and certificate != previous:
            if not certificate:
                raise ValueError(
                    'Could not read the signing certificate of this APK. Sign it with APK '
                    'Signature Scheme v2 or later (the Android Gradle plugin and apksigner do).'
                )
            raise ValueError(
                'This APK is signed with a different key than the releases published so far '
                f'(expected {previous[:16]}…, found {certificate[:16]}…). Devices would refuse '
                'to update, so it was not accepted.'
            )

    @staticmethod
    def _discard_file(stored: Any) -> None:
        try:
            stored.file.delete(save=False)
            stored.delete()
        except Exception:
            logger.exception('Could not clean up a rejected release file')

    # -- changing --------------------------------------------------------------------------

    @staticmethod
    def update(
        release: AppRelease,
        *,
        notes: str | None = None,
        is_published: bool | None = None,
        mandatory: bool | None = None,
        rollout_percent: int | None = None,
        actor: str | None = None,
    ) -> AppRelease:
        if rollout_percent is not None and not 0 <= rollout_percent <= 100:
            raise ValueError('The rollout share must be between 0 and 100.')
        new_mandatory = release.mandatory if mandatory is None else mandatory
        new_rollout = release.rollout_percent if rollout_percent is None else rollout_percent
        if new_mandatory and new_rollout != 100:
            raise ValueError('A mandatory release goes to every device; set the rollout to 100.')
        changed: list[str] = []
        if notes is not None:
            release.notes = notes.strip()
            changed.append('notes')
        if mandatory is not None:
            release.mandatory = mandatory
            changed.append(f'mandatory={mandatory}')
        if rollout_percent is not None:
            release.rollout_percent = rollout_percent
            changed.append(f'rollout={rollout_percent}')
        if is_published is not None:
            if is_published:
                release.mark_published()
            else:
                release.is_published = False
            changed.append(f'published={is_published}')
        release.save()
        if changed:
            AuditService.record(
                action='app_release_updated', user=actor, detail=f'{release} {" ".join(changed)}'
            )
        return release

    @staticmethod
    def delete(release: AppRelease, *, actor: str | None = None) -> None:
        label = str(release)
        stored = release.stored_file
        with transaction.atomic():
            release.delete()
            ReleaseService._discard_file(stored)
        AuditService.record(action='app_release_deleted', user=actor, detail=label)

    # -- device checks ---------------------------------------------------------------------

    @staticmethod
    def check(
        *,
        platform: str = Platform.ANDROID.value,
        channel: str = DEFAULT_CHANNEL,
        version_code: int | None = None,
        sdk_int: int | None = None,
        device_id: str = '',
    ) -> UpdateDecision:
        """What to tell one device. ``version_code`` None means "just show me the latest"."""
        published = list(ReleaseService.list_releases(platform, channel, published_only=True))
        minimum = max((r.version_code for r in published if r.mandatory), default=0)
        offered: AppRelease | None = None
        for release in published:
            if sdk_int and release.min_sdk and sdk_int < release.min_sdk:
                continue  # this build does not run on the device
            if release.mandatory or release.rollout_percent >= 100:
                offered = release
                break
            if device_id and (
                rollout_bucket(device_id, platform, channel, release.version_code)
                < release.rollout_percent
            ):
                offered = release
                break
        installed = version_code or 0
        available = bool(offered and offered.version_code > installed) and version_code is not None
        required = bool(version_code is not None and installed < minimum and available)
        return UpdateDecision(
            latest=offered,
            update_available=available,
            required=required,
            minimum_version_code=minimum,
        )

    @staticmethod
    def record_checkin(
        *,
        platform: str,
        device_id: str,
        channel: str,
        version_code: int,
        version_name: str = '',
        sdk_int: int = 0,
    ) -> None:
        """Best effort: a failure to write a statistic must never fail an update check."""
        device_id = (device_id or '').strip()[:64]
        if not device_id:
            return
        try:
            known = DeviceCheckin.objects.filter(platform=platform, device_id=device_id).exists()
            if not known and DeviceCheckin.objects.count() >= MAX_TRACKED_DEVICES:
                return
            row, created = DeviceCheckin.objects.get_or_create(
                platform=platform,
                device_id=device_id,
                defaults={
                    'channel': channel,
                    'version_code': version_code,
                    'version_name': version_name[:64],
                    'sdk_int': max(0, min(sdk_int, 32767)),
                    'checks': 1,
                },
            )
            if not created:
                row.channel = channel
                row.version_code = version_code
                row.version_name = version_name[:64]
                row.sdk_int = max(0, min(sdk_int, 32767))
                row.last_seen = timezone.now()
                row.checks += 1
                row.save()
        except DatabaseError:
            logger.exception('Failed to record an update check')

    # -- reporting -------------------------------------------------------------------------

    @staticmethod
    def adoption(platform: str = Platform.ANDROID.value) -> list[AdoptionRow]:
        """Active devices per version, newest first."""
        since = timezone.now() - timedelta(days=ACTIVE_DEVICE_DAYS)
        rows = (
            DeviceCheckin.objects.filter(platform=platform, last_seen__gte=since)
            .values('version_code')
            .annotate(devices=Count('id'), name=Max('version_name'))
            .order_by('-version_code')
        )
        return [
            AdoptionRow(
                version_code=int(r['version_code']),
                version_name=str(r['name'] or ''),
                devices=int(r['devices']),
            )
            for r in rows
        ]

    @staticmethod
    def active_device_count(platform: str = Platform.ANDROID.value) -> int:
        since = timezone.now() - timedelta(days=ACTIVE_DEVICE_DAYS)
        return DeviceCheckin.objects.filter(platform=platform, last_seen__gte=since).count()

    @staticmethod
    def prune_checkins(days: int = CHECKIN_RETENTION_DAYS) -> int:
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = DeviceCheckin.objects.filter(last_seen__lt=cutoff).delete()
        return int(deleted)


def manifest_for(
    decision: UpdateDecision,
    *,
    platform: str,
    channel: str,
    base_url: str = '',
) -> dict[str, Any]:
    """The JSON document devices read. ``base_url`` makes ``download_url`` absolute."""
    latest = decision.latest
    body: dict[str, Any] = {
        'schema': 1,
        'platform': platform,
        'channel': channel,
        'update_available': decision.update_available,
        'mandatory': decision.required,
        'minimum_version_code': decision.minimum_version_code,
        'latest': None,
    }
    if latest is not None:
        body['latest'] = {
            'version_code': latest.version_code,
            'version_name': latest.version_name,
            'released_at': latest.published_at.isoformat() if latest.published_at else None,
            'notes': latest.notes,
            'size_bytes': latest.size_bytes,
            'sha256': latest.sha256,
            'signing_cert_sha256': latest.signing_cert_sha256,
            'min_sdk': latest.min_sdk,
            'package': latest.package_name,
            'download_path': ReleaseService.download_path(latest),
            'download_url': f'{base_url.rstrip("/")}{ReleaseService.download_path(latest)}'
            if base_url
            else ReleaseService.download_path(latest),
        }
    return body


__all__ = [
    'AdoptionRow',
    'ReleaseService',
    'UpdateDecision',
    'manifest_for',
    'rollout_bucket',
]
