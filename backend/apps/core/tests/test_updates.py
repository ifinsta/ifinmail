"""Update check: is a newer release tag published than the installed APP_VERSION?"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.core.platform.services.updates import UpdateService, UpdateStatus, parse_version
from backend.apps.core.tests.mail_base import MailTablesTestCase


class VersionParsingTests(SimpleTestCase):
    def test_tags_and_git_describe_output(self) -> None:
        self.assertEqual(parse_version('v0.0.3'), (0, 0, 3, 0))
        self.assertEqual(parse_version('v0.0.3-2-gabc1234'), (0, 0, 3, 2))
        self.assertEqual(parse_version('0.1.0'), (0, 1, 0, 0))
        self.assertIsNone(parse_version('dev'))
        self.assertIsNone(parse_version('abc1234'))

    def test_available_only_for_a_newer_release(self) -> None:
        def status(current: str, latest: str) -> UpdateStatus:
            return UpdateStatus(enabled=True, current=current, latest=latest, repo='ifinsta/ifinmail')

        self.assertTrue(status('v0.0.3', 'v0.0.4').available)
        self.assertTrue(status('v0.0.3-5-gabc1234', 'v0.1.0').available)
        self.assertFalse(status('v0.0.4', 'v0.0.4').available)
        self.assertFalse(status('v0.0.4-1-gabc1234', 'v0.0.4').available)  # ahead of the tag
        self.assertFalse(status('dev', 'v0.0.4').available)  # unknown build: never nag
        self.assertEqual(
            status('v0.0.3-2-gabc1234', 'v0.0.4').changes_url,
            'https://github.com/ifinsta/ifinmail/compare/v0.0.3...v0.0.4',
        )


class UpdateCheckTests(MailTablesTestCase):
    env = {'APP_VERSION': 'v0.0.3', 'UPDATE_REPO': 'ifinsta/ifinmail'}

    def _github(self, names: list[str]) -> MagicMock:
        response = MagicMock()
        response.json.return_value = [{'name': n} for n in names]
        response.raise_for_status.return_value = None
        return response

    def test_check_picks_the_highest_release_tag_and_remembers_it(self) -> None:
        with patch('requests.get', return_value=self._github(['v0.0.2', 'v0.0.10', 'v0.0.4', 'nightly'])):
            status = UpdateService.check()
        self.assertEqual(status.latest, 'v0.0.10')
        self.assertTrue(status.available)
        self.assertEqual(UpdateService.status().latest, 'v0.0.10')  # stored, no network needed

    def test_a_failed_check_keeps_the_last_good_answer(self) -> None:
        with patch('requests.get', return_value=self._github(['v0.0.4'])):
            UpdateService.check()
        with patch('requests.get', side_effect=OSError('offline')):
            status = UpdateService.check()
        self.assertEqual(status.latest, 'v0.0.4')
        self.assertIn('Could not reach GitHub', status.error)

    def test_switched_off_means_no_request(self) -> None:
        UpdateService.set_enabled(False)
        with patch('requests.get', side_effect=AssertionError('must not ask GitHub')):
            status = UpdateService.check()
        self.assertFalse(status.enabled)
        with patch.dict(os.environ, {'UPDATE_CHECK_ENABLED': '0'}):
            UpdateService.set_enabled(True)
            self.assertFalse(UpdateService.enabled())


class UpdateBannerTests(MailTablesTestCase):
    env = {'APP_VERSION': 'v0.0.3'}

    def setUp(self) -> None:
        super().setUp()
        from backend.apps.accounts.services.setup_state import SetupState

        SetupState.mark_complete()
        admin = MailUser.objects.create_superuser('admin@ifinmail.test', 'Correct-Horse-9')
        self.client.force_login(admin)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def test_dashboard_announces_a_newer_release_without_asking_github(self) -> None:
        with patch('requests.get', return_value=UpdateCheckTests._github(self, ['v0.0.4'])):
            UpdateService.check()
        with patch('requests.get', side_effect=AssertionError('dashboard must not ask GitHub')):
            response = self.client.get(reverse('accounts:dashboard'))
        self.assertContains(response, '<strong>v0.0.4</strong> is available')
        self.assertContains(response, 'compare/v0.0.3...v0.0.4')

    def test_no_banner_when_up_to_date(self) -> None:
        with patch('requests.get', return_value=UpdateCheckTests._github(self, ['v0.0.3'])):
            UpdateService.check()
        response = self.client.get(reverse('accounts:dashboard'))
        self.assertNotContains(response, 'is available')

    def test_admins_can_switch_the_check_off(self) -> None:
        response = self.client.post(reverse('accounts:system_health_updates'), {'enabled': '0'})
        self.assertRedirects(response, reverse('accounts:system_health'), fetch_redirect_response=False)
        self.assertFalse(UpdateService.enabled())
