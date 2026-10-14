"""releases — the console page under Settings: who may use it, and what its forms do."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.roles import RoleService
from backend.apps.accounts.tests.test_api_v1 import GOOD, LOCMEM, MODEL_BACKEND
from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.releases.models import AppRelease
from backend.apps.core.releases.tests.apk_factory import build_apk
from backend.apps.core.tests.mail_base import MailTablesTestCase


def apk(version_code: int = 1, **kwargs: object) -> SimpleUploadedFile:
    return SimpleUploadedFile(
        'app-release.apk',
        build_apk(version_code=version_code, version_name=f'1.{version_code}.0', **kwargs),
        content_type='application/vnd.android.package-archive',
    )


def sign_in(client, user) -> None:
    client.force_login(user, backend=MODEL_BACKEND)
    session = client.session
    session['mfa_verified_at'] = timezone.now().isoformat()
    session.save()


@override_settings(CACHES=LOCMEM)
class ConsoleTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        from django.core.cache import cache

        cache.clear()
        RoleService.ensure_seed()
        self.media = Path(tempfile.mkdtemp(prefix='ifinmail-releases-console-'))
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.admin = MailUser.objects.create_user(
            'root@ifinmail.test', GOOD, is_staff=True, is_superuser=True
        )
        sign_in(self.client, self.admin)

    def publish(self, version_code: int = 1, **over: object):
        data = {
            'file': apk(version_code),
            'channel': 'stable',
            'notes': 'Faster sync',
            'rollout_percent': '100',
            'publish': '1',
            'confirm_password': GOOD,
        }
        data.update(over)
        return self.client.post(reverse('releases:console_publish'), data)

    def act(self, release: AppRelease, action: str, **over: object):
        data = {
            'platform': release.platform,
            'channel': release.channel,
            'version_code': str(release.version_code),
            'action': action,
        }
        data.update(over)
        return self.client.post(reverse('releases:console_action'), data)

    # -- access ----------------------------------------------------------------------------
    def test_the_page_needs_a_signed_in_administrator(self) -> None:
        self.client.logout()
        response = self.client.get(reverse('releases:console'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_people_without_system_manage_are_refused(self) -> None:
        helper = MailUser.objects.create_user('help@ifinmail.test', GOOD, is_staff=True)
        RoleService.assign(helper, 'support')
        sign_in(self.client, helper)
        self.assertIn(self.client.get(reverse('releases:console')).status_code, (302, 403))
        self.assertIn(self.publish().status_code, (302, 403))
        self.assertFalse(AppRelease.objects.exists())

    def test_the_page_is_in_the_settings_hub_and_renders_empty(self) -> None:
        hub = self.client.get(reverse('accounts:settings')).content.decode()
        self.assertIn(reverse('releases:console'), hub)
        page = self.client.get(reverse('releases:console'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'App releases')
        self.assertContains(page, 'No builds yet')
        self.assertContains(page, 'com.ifinmail')
        self.assertContains(page, '/api/v1/releases/android')

    # -- publishing ------------------------------------------------------------------------
    def test_publishing_through_the_form(self) -> None:
        response = self.publish(3)
        self.assertRedirects(response, reverse('releases:console'), fetch_redirect_response=False)
        release = AppRelease.objects.get()
        self.assertEqual(release.version_code, 3)
        self.assertEqual(release.published_by, 'root@ifinmail.test')
        page = self.client.get(reverse('releases:console')).content.decode()
        self.assertIn('1.3.0', page)
        self.assertIn(release.sha256, page)
        self.assertTrue(AuditService.has('app_release_published'))

    def test_a_wrong_password_publishes_nothing(self) -> None:
        self.publish(1, confirm_password='nope')
        self.assertFalse(AppRelease.objects.exists())

    def test_a_refused_build_says_why_and_leaves_nothing(self) -> None:
        response = self.client.post(
            reverse('releases:console_publish'),
            {'file': apk(1, package='com.other.app'), 'channel': 'stable', 'confirm_password': GOOD},
            follow=True,
        )
        self.assertContains(response, 'com.other.app')
        self.assertFalse(AppRelease.objects.exists())

    # -- managing --------------------------------------------------------------------------
    def test_withdraw_restore_and_rollout(self) -> None:
        self.publish(1)
        release = AppRelease.objects.get()
        self.act(release, 'withdraw')
        release.refresh_from_db()
        self.assertFalse(release.is_published)
        self.act(release, 'restore')
        release.refresh_from_db()
        self.assertTrue(release.is_published)
        self.act(release, 'rollout', rollout_percent='25')
        release.refresh_from_db()
        self.assertEqual(release.rollout_percent, 25)
        self.act(release, 'notes', notes='Rewritten')
        release.refresh_from_db()
        self.assertEqual(release.notes, 'Rewritten')

    def test_mandatory_and_delete_need_the_password(self) -> None:
        self.publish(1)
        release = AppRelease.objects.get()
        self.act(release, 'mandatory_on')  # no password
        release.refresh_from_db()
        self.assertFalse(release.mandatory)
        self.act(release, 'mandatory_on', confirm_password=GOOD)
        release.refresh_from_db()
        self.assertTrue(release.mandatory)
        self.act(release, 'delete')  # no password
        self.assertTrue(AppRelease.objects.filter(pk=release.pk).exists())
        self.act(release, 'delete', confirm_password=GOOD)
        self.assertFalse(AppRelease.objects.exists())
        self.assertTrue(AuditService.has('app_release_deleted'))
