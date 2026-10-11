"""devices — service and viewset tests."""

from django.test import TestCase

from backend.apps.devices.api import (
    list_devices,
    register_device,
    set_device_active,
    touch_device,
)
from backend.apps.devices.serializers import DeviceOut, DeviceRegisterIn
from backend.apps.devices.services import DeviceService


class DeviceServiceTests(TestCase):
    def test_register_is_idempotent_and_refreshes(self) -> None:
        first, created = DeviceService.register('Pixel', 'dev-1', 'android')
        self.assertTrue(created)
        second, created_again = DeviceService.register('Pixel 8', 'dev-1', 'android')
        self.assertFalse(created_again)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(second.name, 'Pixel 8')
        self.assertIsNotNone(second.last_seen)

    def test_register_validates_input(self) -> None:
        with self.assertRaises(ValueError):
            DeviceService.register('', 'dev-1')
        with self.assertRaises(ValueError):
            DeviceService.register('Pixel', '')

    def test_touch_and_deactivate(self) -> None:
        DeviceService.register('Pixel', 'dev-1', 'android')
        touched = DeviceService.touch('dev-1')
        self.assertIsNotNone(touched.last_seen)
        self.assertIsNone(DeviceService.touch('unknown'))
        DeviceService.set_active('dev-1', False)
        self.assertEqual(list(DeviceService.get_active()), [])
        self.assertEqual(DeviceService.get_count(), 1)

    def test_get_by_identifier_guards_empty(self) -> None:
        self.assertIsNone(DeviceService.get_by_identifier(''))


class DeviceViewsetTests(TestCase):
    def test_register_list_touch_flow_is_shaped(self) -> None:
        out, created = register_device(DeviceRegisterIn('Pixel', 'dev-1', 'android'))
        self.assertTrue(created)
        self.assertIsInstance(out, DeviceOut)
        self.assertEqual(out.name, 'Pixel')
        self.assertTrue(out.last_seen)
        self.assertEqual(len(list_devices()), 1)
        self.assertEqual(len(list_devices(active_only=True)), 1)
        set_device_active('dev-1', False)
        self.assertEqual(list_devices(active_only=True), [])
        self.assertEqual(len(list_devices()), 1)
        self.assertIsNone(touch_device('unknown'))
