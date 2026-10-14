"""Anonymous update checks cannot grow the device table without bound."""

from __future__ import annotations

from unittest.mock import patch

from backend.apps.core.releases.models import DeviceCheckin
from backend.apps.core.releases.services import ReleaseService
from backend.apps.core.releases.tests.test_service import ReleaseTestCase


class CheckinCapTests(ReleaseTestCase):
    def check(self, device: str, code: int = 1) -> None:
        ReleaseService.record_checkin(
            platform='android', device_id=device, channel='stable', version_code=code
        )

    def test_new_devices_stop_being_recorded_at_the_cap(self) -> None:
        with patch('backend.apps.core.releases.services.release_service.MAX_TRACKED_DEVICES', 2):
            for device in ('device-aaaa1', 'device-bbbb2', 'device-cccc3', 'device-dddd4'):
                self.check(device)
        self.assertEqual(
            sorted(DeviceCheckin.objects.values_list('device_id', flat=True)),
            ['device-aaaa1', 'device-bbbb2'],
        )

    def test_a_known_device_is_still_updated_at_the_cap(self) -> None:
        with patch('backend.apps.core.releases.services.release_service.MAX_TRACKED_DEVICES', 1):
            self.check('device-aaaa1', 1)
            self.check('device-aaaa1', 7)
            self.check('device-bbbb2', 7)
        row = DeviceCheckin.objects.get()
        self.assertEqual((row.device_id, row.version_code, row.checks), ('device-aaaa1', 7, 2))
