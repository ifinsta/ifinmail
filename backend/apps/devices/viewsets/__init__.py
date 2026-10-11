"""devices — viewsets: API operation handlers (API flow).

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
"""

from backend.apps.devices.viewsets.devices import (
    list_devices,
    register_device,
    set_device_active,
    touch_device,
)

__all__ = ['list_devices', 'register_device', 'set_device_active', 'touch_device']
