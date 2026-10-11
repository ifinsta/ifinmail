"""devices — types: device classification."""

from __future__ import annotations

from enum import StrEnum


class DeviceType(StrEnum):
    """Known client families. Free-form values are accepted and stored as-is."""

    ANDROID = 'android'
    IOS = 'ios'
    DESKTOP = 'desktop'
    WEB = 'web'
    OTHER = 'other'


__all__ = ['DeviceType']
