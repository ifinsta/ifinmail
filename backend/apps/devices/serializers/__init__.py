"""devices — serializers: shaping for the API flow.

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.apps.devices.models import Device


@dataclass(frozen=True)
class DeviceRegisterIn:
    name: str
    identifier: str
    device_type: str = ''


@dataclass(frozen=True)
class DeviceOut:
    id: str
    name: str
    device_type: str
    identifier: str
    is_active: bool
    last_seen: str

    @classmethod
    def from_model(cls, device: Device) -> DeviceOut:
        return cls(
            id=str(device.id),
            name=device.name,
            device_type=device.device_type,
            identifier=device.identifier,
            is_active=bool(device.is_active),
            last_seen=device.last_seen.isoformat() if device.last_seen else '',
        )


__all__ = ['DeviceOut', 'DeviceRegisterIn']
