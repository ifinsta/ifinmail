"""core viewsets — api.py → viewsets/ → serializers/ → services/ layer tests."""

from django.test import TestCase

from backend.apps.core.api import delete_setting, get_setting, set_setting
from backend.apps.core.serializers import SettingNotFoundError, SettingOut
from backend.apps.core.types import SettingKey


class SettingViewsetTests(TestCase):
    def test_set_get_delete_round_trip(self) -> None:
        out = set_setting('registration.open', True)
        self.assertIsInstance(out, SettingOut)
        self.assertTrue(get_setting('registration.open').value)
        delete_setting('registration.open')
        self.assertFalse(get_setting('registration.open').value or False)

    def test_keys_are_validated_against_the_catalogue(self) -> None:
        with self.assertRaises(SettingNotFoundError):
            get_setting('not.a.real.key')
        with self.assertRaises(SettingNotFoundError):
            set_setting('not.a.real.key', 1)

    def test_enum_keys_accepted(self) -> None:
        set_setting(SettingKey.MAX_HOPS, 10)
        self.assertEqual(get_setting('mail.max_hops').value, 10)

    def test_missing_value_returns_none(self) -> None:
        self.assertIsNone(get_setting('ops.last_backup_at').value)
