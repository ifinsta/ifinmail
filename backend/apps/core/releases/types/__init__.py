"""releases — types: enums and constants shared by services, the API and the public pages."""

from __future__ import annotations

from enum import StrEnum


class Platform(StrEnum):
    ANDROID = 'android'


class Channel(StrEnum):
    STABLE = 'stable'
    BETA = 'beta'


PLATFORM_VALUES: tuple[str, ...] = tuple(p.value for p in Platform)
CHANNEL_VALUES: tuple[str, ...] = tuple(c.value for c in Channel)
DEFAULT_CHANNEL: str = Channel.STABLE.value

# The application id every uploaded Android build must carry, unless the install overrides it
# with ``RELEASES_ANDROID_PACKAGE`` (a white-label build of the client).
DEFAULT_ANDROID_PACKAGE = 'com.ifinmail'

APK_CONTENT_TYPE = 'application/vnd.android.package-archive'

# Version of the JSON document devices read. Fields are only ever added within one version.
MANIFEST_SCHEMA = 1

# A device that has not asked for this long no longer counts as "in the field" in adoption stats.
ACTIVE_DEVICE_DAYS = 30
CHECKIN_RETENTION_DAYS = 180

__all__ = [
    'ACTIVE_DEVICE_DAYS',
    'APK_CONTENT_TYPE',
    'CHANNEL_VALUES',
    'CHECKIN_RETENTION_DAYS',
    'DEFAULT_ANDROID_PACKAGE',
    'DEFAULT_CHANNEL',
    'MANIFEST_SCHEMA',
    'PLATFORM_VALUES',
    'Channel',
    'Platform',
]
