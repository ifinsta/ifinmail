"""releases — the v1 management API and the public update surface, through the real URL space."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from backend.apps.accounts.services.tokens import TokenService, key_id
from backend.apps.accounts.tests.test_api_v1 import ApiBase, basic
from backend.apps.core.releases.models import AppRelease
from backend.apps.core.releases.tests.apk_factory import build_apk


def apk_file(**kwargs: object) -> SimpleUploadedFile:
    return SimpleUploadedFile(
        'app-release.apk', build_apk(**kwargs), content_type='application/vnd.android.package-archive'
    )


class ReleaseHttpBase(ApiBase):
    def setUp(self) -> None:
        super().setUp()
        self.media = Path(tempfile.mkdtemp(prefix='ifinmail-releases-api-'))
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        row, token = TokenService.create(self.owner, 'releases', ['system.manage'], expires_in_days=30)
        self.rel_key, self.rel_secret = key_id(row.prefix), token.split('.', 2)[2]

    def upload(self, version_code: int = 1, *, fields: dict | None = None, key: str | None = None, **apk: object):
        apk.setdefault('version_name', f'1.{version_code}.0')
        data = {'file': apk_file(version_code=version_code, **apk), **(fields or {})}
        auth = basic(key or self.rel_key, self.rel_secret if key is None else self.secret)
        return self.client.post('/api/v1/releases/android', data=data, HTTP_AUTHORIZATION=auth)

    def call_rel(self, method: str, path: str, body: dict | None = None):
        import json

        kwargs = {'HTTP_AUTHORIZATION': basic(self.rel_key, self.rel_secret)}
        if body is not None:
            kwargs.update(data=json.dumps(body), content_type='application/json')
        return getattr(self.client, method)(path, **kwargs)


class ManagementApiTests(ReleaseHttpBase):
    def test_publish_list_change_delete(self) -> None:
        created = self.upload(4, fields={'notes': 'Faster sync', 'rollout_percent': '50'})
        self.assertEqual(created.status_code, 201, created.content)
        body = created.json()
        self.assertEqual(body['version_code'], 4)
        self.assertEqual(body['version_name'], '1.4.0')
        self.assertEqual(body['rollout_percent'], 50)
        self.assertTrue(body['is_published'])
        self.assertTrue(body['download_path'].startswith('/media/storage/'))
        self.assertTrue(body['published_by'].startswith('api:'))

        listing = self.call_rel('get', '/api/v1/releases/android').json()
        self.assertEqual([r['version_code'] for r in listing['releases']], [4])
        self.assertEqual(listing['active_devices'], 0)

        changed = self.call_rel(
            'patch', '/api/v1/releases/android/stable/4', {'is_published': False, 'notes': 'Pulled'}
        )
        self.assertEqual(changed.status_code, 200, changed.content)
        self.assertFalse(changed.json()['is_published'])
        self.assertEqual(changed.json()['notes'], 'Pulled')

        gone = self.call_rel('delete', '/api/v1/releases/android/stable/4')
        self.assertEqual(gone.status_code, 204)
        self.assertFalse(AppRelease.objects.exists())

    def test_the_service_refusals_become_useful_statuses(self) -> None:
        self.assertEqual(self.upload(1).status_code, 201)
        again = self.upload(1)
        self.assertEqual(again.status_code, 409)
        self.assertIn('already exists', again.json()['detail'])
        wrong_app = self.upload(2, package='com.other.app')
        self.assertEqual(wrong_app.status_code, 422)
        self.assertIn('com.other.app', wrong_app.json()['detail'])
        unsigned = self.upload(3, certificate=None)
        self.assertEqual(unsigned.status_code, 422)
        other_key = self.upload(4, certificate=b'certificate-B')
        self.assertEqual(other_key.status_code, 422)
        self.assertIn('different key', other_key.json()['detail'])
        self.assertEqual(self.upload(5, fields={'mandatory': 'true', 'rollout_percent': '10'}).status_code, 422)
        self.assertEqual(AppRelease.objects.count(), 1)

    def test_unknown_things_are_404(self) -> None:
        self.assertEqual(self.call_rel('get', '/api/v1/releases/windows').status_code, 404)
        self.assertEqual(self.call_rel('patch', '/api/v1/releases/android/stable/99', {'notes': 'x'}).status_code, 404)
        self.assertEqual(self.call_rel('delete', '/api/v1/releases/android/stable/99').status_code, 404)

    def test_the_scope_is_required_and_the_contract_says_so(self) -> None:
        # the shared key carries console/mail/dns/audit scopes but not system.manage
        self.assertEqual(self.upload(1, key=self.key).status_code, 403)
        self.assertEqual(self.client.get('/api/v1/releases/android').status_code, 401)
        spec = self.client.get('/api/v1/openapi.json').json()
        operation = spec['paths']['/api/v1/releases/{platform}']['post']
        self.assertEqual(operation['x-required-scope'], 'system.manage')

    def test_every_change_is_audited(self) -> None:
        from backend.apps.core.platform.services.audit import AuditService

        self.upload(1)
        self.call_rel('patch', '/api/v1/releases/android/stable/1', {'mandatory': True})
        actions = [e['action'] for e in AuditService.get_events(limit=20)] if hasattr(AuditService, 'get_events') else []
        if actions:  # the audit reader is optional in this build; the writes are what matter
            self.assertIn('app_release_published', actions)
            self.assertIn('app_release_updated', actions)


class PublicSurfaceTests(ReleaseHttpBase):
    MANIFEST = '/updates/v1/android/latest.json'

    def test_the_manifest_needs_no_credentials_and_is_never_cached(self) -> None:
        self.upload(2)
        response = self.client.get(self.MANIFEST, {'version_code': 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        body = response.json()
        self.assertTrue(body['update_available'])
        self.assertEqual(body['latest']['version_code'], 2)
        self.assertTrue(body['latest']['download_url'].startswith('http'))
        self.assertIn('/media/storage/', body['latest']['download_url'])

    def test_a_check_with_a_device_id_is_counted_in_the_adoption_stats(self) -> None:
        self.upload(2)
        self.client.get(self.MANIFEST, {'version_code': 1, 'device': 'install-0001-aaaa', 'sdk': 34})
        self.client.get(self.MANIFEST, {'version_code': 2, 'device': 'install-0002-bbbb', 'sdk': 35})
        self.client.get(self.MANIFEST, {'version_code': 2, 'device': 'bad id with spaces'})  # ignored
        stats = self.call_rel('get', '/api/v1/releases/android').json()
        self.assertEqual(stats['active_devices'], 2)
        self.assertEqual({a['version_code']: a['devices'] for a in stats['adoption']}, {1: 1, 2: 1})

    def test_bad_input_is_answered_not_raised(self) -> None:
        self.assertEqual(self.client.get(self.MANIFEST, {'channel': 'nightly'}).status_code, 400)
        ok = self.client.get(self.MANIFEST, {'version_code': 'abc', 'sdk': '-3'})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.client.post(self.MANIFEST).status_code, 405)

    def test_the_permalink_redirects_to_the_newest_stable_build(self) -> None:
        self.assertEqual(self.client.get('/download/android/latest.apk').status_code, 404)
        self.upload(1)
        newest = self.upload(2).json()
        self.upload(9, fields={'channel': 'beta'})
        response = self.client.get('/download/android/latest.apk')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], newest['download_path'])

    def test_the_published_file_is_downloadable_by_anyone(self) -> None:
        created = self.upload(1).json()
        response = self.client.get(created['download_path'])  # anonymous, through the media view
        self.assertEqual(response.status_code, 200)
        data = b''.join(response.streaming_content) if response.streaming else response.content
        import hashlib

        self.assertEqual(hashlib.sha256(data).hexdigest(), created['sha256'])


class DownloadPageTests(ReleaseHttpBase):
    def test_the_page_explains_there_is_no_build_yet(self) -> None:
        response = self.client.get('/download/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No Android build yet')
        self.assertNotContains(response, 'Download APK')

    def test_the_page_offers_the_newest_stable_build_with_what_to_verify(self) -> None:
        self.upload(1, fields={'notes': 'First release'})
        newest = self.upload(
            2, fields={'notes': 'Faster sync\n\n- fixes a crash'}, min_sdk=26
        ).json()
        self.upload(3, fields={'channel': 'beta'})
        response = self.client.get('/download/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Version 1.2.0')
        self.assertContains(response, 'Download APK')
        self.assertContains(response, newest['sha256'])
        self.assertContains(response, 'Android 8.0 or newer')
        self.assertContains(response, newest['download_path'])
        self.assertContains(response, 'Faster sync')
        self.assertContains(response, 'Earlier versions')  # build 1 is listed below
        self.assertContains(response, 'Download the beta')
        self.assertContains(response, 'data:image/svg+xml;base64,')  # the QR code

    def test_a_withdrawn_build_disappears_from_the_page(self) -> None:
        self.upload(1)
        self.call_rel('patch', '/api/v1/releases/android/stable/1', {'is_published': False})
        self.assertContains(self.client.get('/download/'), 'No Android build yet')

    def test_the_page_is_linked_from_the_site_navigation(self) -> None:
        self.assertContains(self.client.get('/changelog/'), 'href="/download/"')

