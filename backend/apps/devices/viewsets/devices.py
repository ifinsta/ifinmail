"""Device registry viewset — operations over DeviceService."""

from __future__ import annotations

from backend.apps.devices.serializers import DeviceOut, DeviceRegisterIn
from backend.apps.devices.services import DeviceService


def list_devices(*, active_only: bool = False) -> list[DeviceOut]:
    rows = DeviceService.get_active() if active_only else DeviceService.get_all()
    return [DeviceOut.from_model(d) for d in rows]


def register_device(payload: DeviceRegisterIn) -> tuple[DeviceOut, bool]:
    device, created = DeviceService.register(payload.name, payload.identifier, payload.device_type)
    return DeviceOut.from_model(device), created


def touch_device(identifier: str) -> DeviceOut | None:
    device = DeviceService.touch(identifier)
    return DeviceOut.from_model(device) if device is not None else None


def set_device_active(identifier: str, active: bool) -> DeviceOut | None:
    device = DeviceService.set_active(identifier, active)
    return DeviceOut.from_model(device) if device is not None else None


__all__ = ['list_devices', 'register_device', 'set_device_active', 'touch_device']
