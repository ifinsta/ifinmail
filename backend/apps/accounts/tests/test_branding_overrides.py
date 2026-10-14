"""The shared overrides file: branding settings live there, and spam settings used to.

Regression coverage for a resolution bug: ``BrandingConfig.from_env()`` ran while
the settings module was imported, where ``django.conf.settings`` is unusable, and
silently fell back to ``APP_DIR`` (``C:\\app`` on Windows) instead of the project
file. The spam view had its own copy of the same broken fallback.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings as django_settings
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.config.branding import DEFAULT_PRIMARY, BrandingConfig, branding_overrides_path

MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding='utf-8')


class BrandingOverridesPathTests(SimpleTestCase):
    def test_explicit_base_dir_beats_the_app_dir_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            _write_json(project / 'branding_overrides.json', {'primary_color': '#778899'})
            app_dir = project / 'app'
            app_dir.mkdir()
            _write_json(app_dir / 'branding_overrides.json', {'primary_color': '#445566'})
            env = {'BRANDING_OVERRIDES_PATH': '', 'APP_DIR': str(app_dir)}
            with patch.dict(os.environ, env):
                resolved = branding_overrides_path(project)
                config = BrandingConfig.from_env(project)
            self.assertEqual(resolved, str(project / 'branding_overrides.json'))
            self.assertEqual(config.color, '#778899')

    def test_env_path_overrides_the_base_dir_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'project'
            project.mkdir()
            _write_json(project / 'branding_overrides.json', {'primary_color': '#778899'})
            explicit = Path(tmp) / 'explicit.json'
            _write_json(explicit, {'primary_color': '#112233'})
            env = {'BRANDING_OVERRIDES_PATH': str(explicit), 'APP_DIR': ''}
            with patch.dict(os.environ, env):
                resolved = branding_overrides_path(project)
                config = BrandingConfig.from_env(project)
            self.assertEqual(resolved, str(explicit))
            self.assertEqual(config.color, '#112233')

    def test_missing_file_falls_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {'BRANDING_OVERRIDES_PATH': '', 'APP_DIR': ''}
            with patch.dict(os.environ, env):
                config = BrandingConfig.from_env(tmp)
        self.assertEqual(config.color, DEFAULT_PRIMARY)


class SpamSettingsShareTheOverridesFileTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        admin = MailUser.objects.create_user('root@ifinmail.test', 'Correct-Horse-9', is_staff=True)
        self.client.force_login(admin, backend=MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def test_spam_page_reads_the_project_overrides_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_json(
                Path(tmp) / 'branding_overrides.json',
                {
                    'spam': {
                        'providers': [
                            {
                                'host': 'rbl.example.net',
                                'type': 'CUSTOM',
                                'latency': '—',
                                'tone': 'neutral',
                            }
                        ],
                        'sensitivity': '4.0',
                    }
                },
            )
            with (
                patch.object(django_settings, 'BASE_DIR', Path(tmp)),
                patch.dict(os.environ, {'BRANDING_OVERRIDES_PATH': ''}),
            ):
                response = self.client.get(reverse('accounts:spam_filtering'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'rbl.example.net')

    def test_sensitivity_is_saved_in_the_database_and_leaves_the_overrides_file_alone(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'branding_overrides.json'
            _write_json(path, {'primary_color': '#112233'})
            with (
                patch.object(django_settings, 'BASE_DIR', Path(tmp)),
                patch.dict(os.environ, {'BRANDING_OVERRIDES_PATH': ''}),
                patch('backend.apps.mail.services.spam_policy._publish'),
            ):
                response = self.client.post(reverse('accounts:spam_sensitivity'), {'level': '3'})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(
                json.loads(path.read_text(encoding='utf-8')), {'primary_color': '#112233'}
            )
        from backend.apps.core.services import SystemSettings
        from backend.apps.core.types import SettingKey

        self.assertEqual(SystemSettings.get(SettingKey.SPAM_SENSITIVITY), 3)
