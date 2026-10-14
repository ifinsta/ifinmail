"""releases — viewsets: API operation handlers (API flow).

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
"""

from __future__ import annotations

from django.core.files.uploadedfile import UploadedFile

from backend.apps.core.releases.serializers import (
    AdoptionV1,
    ReleaseChangeV1,
    ReleaseOverviewV1,
    ReleasePublishV1,
    ReleaseV1,
)
from backend.apps.core.releases.services import ReleaseService
from backend.apps.core.releases.types import PLATFORM_VALUES


def _platform(value: str) -> str:
    platform = (value or '').strip().lower()
    if platform not in PLATFORM_VALUES:
        # "does not exist" is what turns a service error into a 404 for the caller.
        raise ValueError(f'Platform {value!r} does not exist. Use: {", ".join(PLATFORM_VALUES)}.')
    return platform


def _code(value: str, channel: str) -> int:
    """The path carries the version code as text so authorization answers before parsing does."""
    try:
        code = int(value)
    except (TypeError, ValueError):
        code = 0
    if code < 1:
        raise ValueError(f'Release {value!r} does not exist on the {channel} channel.')
    return code


def overview(platform: str, channel: str | None = None) -> ReleaseOverviewV1:
    platform = _platform(platform)
    rows = ReleaseService.list_releases(platform, channel or None)
    return ReleaseOverviewV1(
        releases=[ReleaseV1.from_model(r) for r in rows],
        adoption=[AdoptionV1.from_row(a) for a in ReleaseService.adoption(platform)],
        active_devices=ReleaseService.active_device_count(platform),
    )


def publish(platform: str, upload: UploadedFile, form: ReleasePublishV1, *, actor: str) -> ReleaseV1:
    release = ReleaseService.publish(
        upload=upload,
        platform=_platform(platform),
        channel=form.channel,
        notes=form.notes,
        mandatory=form.mandatory,
        rollout_percent=form.rollout_percent,
        publish=form.publish,
        actor=actor,
    )
    return ReleaseV1.from_model(release)


def change(
    platform: str, channel: str, version_code: str, body: ReleaseChangeV1, *, actor: str
) -> ReleaseV1:
    release = ReleaseService.get(_platform(platform), channel, _code(version_code, channel))
    if release is None:
        raise ValueError(f'Release {version_code} does not exist on the {channel} channel.')
    updated = ReleaseService.update(
        release,
        notes=body.notes,
        is_published=body.is_published,
        mandatory=body.mandatory,
        rollout_percent=body.rollout_percent,
        actor=actor,
    )
    return ReleaseV1.from_model(updated)


def remove(platform: str, channel: str, version_code: str, *, actor: str) -> None:
    release = ReleaseService.get(_platform(platform), channel, _code(version_code, channel))
    if release is None:
        raise ValueError(f'Release {version_code} does not exist on the {channel} channel.')
    ReleaseService.delete(release, actor=actor)


__all__ = ['change', 'overview', 'publish', 'remove']
