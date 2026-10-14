"""releases — serializers: shaping for the API flow.

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
Serializers never touch the database; viewsets feed them service results.
"""

from __future__ import annotations

from ninja import Schema

from backend.apps.core.releases.models import AppRelease
from backend.apps.core.releases.services import AdoptionRow


class ReleaseV1(Schema):
    """One release as an administrator sees it."""

    platform: str
    channel: str
    version_code: int
    version_name: str
    package: str
    min_sdk: int
    notes: str
    size_bytes: int
    sha256: str
    signing_cert_sha256: str
    is_published: bool
    mandatory: bool
    rollout_percent: int
    published_at: str | None
    published_by: str
    download_path: str

    @classmethod
    def from_model(cls, release: AppRelease) -> ReleaseV1:
        return cls(
            platform=release.platform,
            channel=release.channel,
            version_code=release.version_code,
            version_name=release.version_name,
            package=release.package_name,
            min_sdk=release.min_sdk,
            notes=release.notes,
            size_bytes=int(release.size_bytes),
            sha256=release.sha256,
            signing_cert_sha256=release.signing_cert_sha256,
            is_published=release.is_published,
            mandatory=release.mandatory,
            rollout_percent=release.rollout_percent,
            published_at=release.published_at.isoformat() if release.published_at else None,
            published_by=release.published_by,
            download_path=str(release.stored_file.file.url),
        )


class ReleasePublishV1(Schema):
    """The form fields sent with the APK (multipart)."""

    channel: str = 'stable'
    notes: str = ''
    mandatory: bool = False
    rollout_percent: int = 100
    publish: bool = True


class ReleaseChangeV1(Schema):
    """Fields a release lets you change after upload; omitted fields stay as they are."""

    notes: str | None = None
    is_published: bool | None = None
    mandatory: bool | None = None
    rollout_percent: int | None = None


class AdoptionV1(Schema):
    version_code: int
    version_name: str
    devices: int

    @classmethod
    def from_row(cls, row: AdoptionRow) -> AdoptionV1:
        return cls(version_code=row.version_code, version_name=row.version_name, devices=row.devices)


class ReleaseOverviewV1(Schema):
    releases: list[ReleaseV1]
    adoption: list[AdoptionV1]
    active_devices: int


__all__ = [
    'AdoptionV1',
    'ReleaseChangeV1',
    'ReleaseOverviewV1',
    'ReleasePublishV1',
    'ReleaseV1',
]
