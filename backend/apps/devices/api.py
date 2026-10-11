"""devices — api.py: re-export layer for urls.py → api.py → viewsets/ contract."""

from .viewsets import list_devices, register_device, set_device_active, touch_device

__all__ = ['list_devices', 'register_device', 'set_device_active', 'touch_device']
