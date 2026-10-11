"""devices — service layer (single interface for all Device access).

Minimal registry for future client management (mobile sessions, push
endpoints). Push delivery and per-device sessions arrive separately.
"""

from __future__ import annotations

import logging

from django.db.models import QuerySet
from django.db.utils import OperationalError
from django.utils import timezone

from backend.apps.devices.models import Device

logger = logging.getLogger('backend')


class DeviceService:
    @staticmethod
    def get_all() -> QuerySet[Device]:
        return Device.objects.order_by('-last_seen', 'name')

    @staticmethod
    def get_active() -> QuerySet[Device]:
        return Device.objects.filter(is_active=True).order_by('-last_seen', 'name')

    @staticmethod
    def get_by_identifier(identifier: str) -> Device | None:
        if not identifier:
            return None
        try:
            return Device.objects.filter(identifier=identifier).first()
        except OperationalError:
            logger.exception('Failed to fetch device')
            return None

    @staticmethod
    def register(name: str, identifier: str, device_type: str = '') -> tuple[Device, bool]:
        """Register a device or refresh the existing row (idempotent)."""
        if not name or not name.strip():
            raise ValueError('Device name must not be empty.')
        if not identifier or not identifier.strip():
            raise ValueError('Device identifier must not be empty.')
        device, created = Device.objects.update_or_create(
            identifier=identifier.strip(),
            defaults={
                'name': name.strip(),
                'device_type': (device_type or '').strip(),
                'is_active': True,
                'last_seen': timezone.now(),
            },
        )
        return device, created

    @staticmethod
    def touch(identifier: str) -> Device | None:
        """Record a sighting; None when the device is unknown."""
        device = DeviceService.get_by_identifier(identifier)
        if device is None:
            return None
        device.last_seen = timezone.now()
        device.save(update_fields=['last_seen'])
        return device

    @staticmethod
    def set_active(identifier: str, active: bool) -> Device | None:
        device = DeviceService.get_by_identifier(identifier)
        if device is None:
            return None
        device.is_active = active
        device.save(update_fields=['is_active'])
        return device

    @staticmethod
    def get_count() -> int:
        try:
            return Device.objects.count()
        except OperationalError:
            return 0


__all__ = ['DeviceService']
