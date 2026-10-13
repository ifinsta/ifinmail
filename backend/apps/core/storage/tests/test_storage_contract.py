"""The storage contract and the console's use of it: keys, the local driver, routing, retrieval,
branding, backups from the command line, the probe, the page."""

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from backend.apps.accounts.tests import test_assistant_views as base
from backend.apps.core.platform.models import AuditEvent
from backend.apps.core.storage import config, drivers, health
from backend.apps.core.storage.contract import (
    InvalidKeyError,
    ObjectNotFoundError,
    StorageRejectedError,
    check_key,
)
from backend.apps.core.storage.drivers.local import LocalStore
from backend.apps.core.storage.drivers.s3 import S3Store
from backend.apps.core.storage.tests.memory_store import MemoryStore


class KeyRuleTests(SimpleTestCase):
    def test_good_keys(self) -> None:
        for key in ('branding/logo.png', 'a', 'media/a b+c&d=é/ü (1).txt', 'x' * 400):
            self.assertEqual(check_key(key), key)

    def test_bad_keys(self) -> None:
        for key in (
            '',
            '/abs',
            'a/',
            'a//b',
            '../x',
            'a/../b',
            'a/./b',
            'back\\slash',
            'nul\x00',
            'x' * 600,
        ):
            with self.subTest(key=key), self.assertRaises(InvalidKeyError):
                check_key(key)


class LocalDriverTests(SimpleTestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix='ifm-store-'))
        self.store = LocalStore(self.root)

    def test_round_trip_list_delete_and_probe(self) -> None:
        info = self.store.put('branding/logo.png', b'\x89PNG data', content_type='image/png')
        self.assertEqual(info.size, 9)
        self.assertEqual(len(info.sha256), 64)
        self.assertEqual(self.store.get('branding/logo.png'), b'\x89PNG data')
        self.assertEqual(
            b''.join(self.store.open('branding/logo.png', chunk_size=3)), b'\x89PNG data'
        )
        self.assertEqual(self.store.head('branding/logo.png').content_type, 'image/png')
        self.assertEqual([o.key for o in self.store.list('branding/')], ['branding/logo.png'])
        self.store.delete('branding/logo.png')
        self.store.delete('branding/logo.png')  # idempotent
        with self.assertRaises(ObjectNotFoundError):
            self.store.get('branding/logo.png')
        self.assertTrue(self.store.probe().ok)
        self.assertEqual(list(self.root.rglob('.upload-*')), [])  # no temporary file left behind

    def test_it_cannot_leave_its_directory(self) -> None:
        with self.assertRaises(InvalidKeyError):
            self.store.put('../../etc/passwd', b'x')
        outside = self.root.parent / f'{self.root.name}-sibling'
        outside.mkdir()
        os.symlink(outside, self.root / 'link')
        with self.assertRaises(InvalidKeyError):
            self.store.put('link/escape.txt', b'x')

    def test_a_large_stream_is_written_without_holding_it(self) -> None:
        data = os.urandom(3 * 1024 * 1024 + 7)
        info = self.store.put_stream('backups/x.gpg', io.BytesIO(data))
        self.assertEqual(info.size, len(data))
        import hashlib

        self.assertEqual(info.sha256, hashlib.sha256(data).hexdigest())


class S3SettingsTests(SimpleTestCase):
    def test_settings_are_checked_before_any_request(self) -> None:
        good = {
            'endpoint': 'https://s3.example.test',
            'bucket': 'b1x',
            'access_key': 'AK',
            'secret_key': 'SK',
        }
        store = S3Store.from_settings(good)
        self.assertEqual((store.region, store.addressing, store.prefix), ('us-east-1', 'path', ''))
        for broken in (
            {'endpoint': 'ftp://x'},
            {'bucket': ''},
            {'secret_key': ''},
            {'prefix': '../up'},
        ):
            with self.subTest(broken), self.assertRaises((StorageRejectedError, InvalidKeyError)):
                S3Store.from_settings({**good, **broken})

    def test_the_secret_never_appears_in_its_repr(self) -> None:
        store = S3Store.from_settings(
            {
                'endpoint': 'https://s3.example.test',
                'bucket': 'b1x',
                'access_key': 'AK',
                'secret_key': 'TOPSECRET',
            }
        )
        self.assertNotIn('TOPSECRET', repr(store))

    def test_presigned_urls_address_path_and_virtual_style(self) -> None:
        base_settings = {
            'endpoint': 'https://s3.example.test',
            'bucket': 'media-bkt',
            'access_key': 'AK',
            'secret_key': 'SK',
            'prefix': 'srv1',
        }
        path_url = S3Store.from_settings(base_settings).retrieval_url(
            'branding/logo.png', expires=60
        )
        assert path_url is not None
        self.assertTrue(
            path_url.startswith('https://s3.example.test/media-bkt/srv1/branding/logo.png?')
        )
        self.assertIn('X-Amz-Expires=60', path_url)
        virtual = S3Store.from_settings({**base_settings, 'addressing': 'virtual'}).retrieval_url(
            'a.png'
        )
        assert virtual is not None
        self.assertTrue(virtual.startswith('https://media-bkt.s3.example.test/srv1/a.png?'))


class RoutedBase(base.AssistantBase):
    """Media routed to an in-memory store, as if the Object storage plugin were set up."""

    retrieval = 'redirect'

    def setUp(self) -> None:
        super().setUp()
        self.media_dir = Path(tempfile.mkdtemp(prefix='ifm-media-'))
        media = override_settings(MEDIA_ROOT=str(self.media_dir))
        media.enable()
        self.addCleanup(media.disable)
        self.memory = MemoryStore()
        drivers.register('memory', lambda s: self.memory)
        self.addCleanup(lambda: drivers._DRIVERS.pop('memory', None))  # noqa: SLF001
        config._cache.clear()  # noqa: SLF001

    def route(self, *purposes: str, retrieval: str = 'redirect', public: str = '') -> None:
        values = {
            'driver': 'memory',
            'endpoint': 'https://store.example.test',
            'bucket': 'b',
            'prefix': 'srv',
        }
        chosen = config.StoreSettings('memory', values, frozenset(purposes), retrieval, public, 120)
        patcher = patch.object(config, 'current', return_value=chosen)
        patcher.start()
        self.addCleanup(patcher.stop)
        config._cache.clear()  # noqa: SLF001


class RoutingTests(RoutedBase):
    def test_without_a_plugin_everything_is_on_the_disk(self) -> None:
        self.assertIsNone(config.current())
        self.assertIsInstance(config.store_for('media'), LocalStore)
        with self.assertRaises(StorageRejectedError):
            config.store_for('backups')  # backups never silently land in MEDIA_ROOT

    def test_django_storage_goes_to_the_routed_store(self) -> None:
        self.route('media')
        name = default_storage.save('storage/PRODUCT/a.txt', ContentFile(b'hello'))
        self.assertEqual(self.memory.get(name), b'hello')
        self.assertEqual(default_storage.url(name), f'/media/{name}')
        self.assertTrue(default_storage.exists(name))
        self.assertEqual(default_storage.size(name), 5)
        self.assertEqual(default_storage.open(name).read(), b'hello')
        default_storage.delete(name)
        self.assertFalse(self.memory.exists(name))
        self.assertEqual(list(self.media_dir.iterdir()), [])  # nothing touched the disk

    def test_the_plugin_values_build_an_s3_store_with_the_secret_decrypted(self) -> None:
        from backend.apps.core.plugins.services import InstallationService

        InstallationService.install(
            'object-storage',
            {
                'endpoint': 'https://s3.eu-central-1.amazonaws.com/',
                'region': 'eu-central-1',
                'bucket': 'ifinmail-media',
                'access_key': 'AKIAEXAMPLE',
                'secret_key': 'plain-secret-value',
                'store_media': True,
                'store_backups': True,
            },
            self.admin.email,
        )
        chosen = config.current()
        assert chosen is not None
        self.assertEqual(chosen.purposes, frozenset({'media', 'backups'}))
        self.assertEqual(chosen.values['endpoint'], 'https://s3.eu-central-1.amazonaws.com')
        self.assertEqual(chosen.values['secret_key'], 'plain-secret-value')
        self.assertNotIn('plain-secret-value', str(config.describe()))
        store = config.store_for('media')
        self.assertIsInstance(store, S3Store)
        self.assertEqual(
            (store.bucket, store.region, store.prefix),
            ('ifinmail-media', 'eu-central-1', 'ifinmail'),
        )
        self.assertIs(config.store_for('backups'), store)  # one configuration, one client

    def test_an_invalid_setting_is_refused_by_the_capability(self) -> None:
        from backend.apps.core.plugins.services import InstallationService
        from backend.apps.core.plugins.types import PluginError

        with self.assertRaises(PluginError):
            InstallationService.install(
                'object-storage',
                {
                    'endpoint': 'not a url',
                    'bucket': 'Bad_Bucket',
                    'access_key': 'AK',
                    'secret_key': 'x',
                },
                self.admin.email,
            )


class RetrievalTests(RoutedBase):
    def test_local_media_is_served_when_nginx_falls_through(self) -> None:
        (self.media_dir / 'branding').mkdir()
        (self.media_dir / 'branding' / 'logo.png').write_bytes(b'\x89PNG')
        response = self.client.get('/media/branding/logo.png')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'\x89PNG')
        self.assertEqual(self.client.get('/media/branding/missing.png').status_code, 404)

    def test_redirect_to_a_short_lived_link(self) -> None:
        self.route('media', retrieval='redirect')
        self.memory.put('branding/logo.png', b'x', content_type='image/png')
        response = self.client.get('/media/branding/logo.png')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response['Location'], 'https://store.example.test/branding/logo.png?signed=120'
        )
        self.assertEqual(response['Cache-Control'], 'private, max-age=90')

    def test_public_address(self) -> None:
        self.route('media', retrieval='public', public='https://cdn.example.test')
        response = self.client.get('/media/branding/logo.png')
        self.assertEqual(response['Location'], 'https://cdn.example.test/srv/branding/logo.png')

    def test_proxy_streams_the_object(self) -> None:
        self.route('media', retrieval='proxy')
        self.memory.put('branding/logo.svg', b'<svg/>', content_type='image/svg+xml')
        response = self.client.get('/media/branding/logo.svg')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/svg+xml')
        self.assertEqual(b''.join(response.streaming_content), b'<svg/>')
        self.assertEqual(self.client.get('/media/branding/none.svg').status_code, 404)

    def test_a_down_store_is_a_503_not_a_crash(self) -> None:
        self.route('media', retrieval='proxy')
        self.memory.put('branding/logo.svg', b'<svg/>')
        self.memory.fail = True
        self.assertEqual(self.client.get('/media/branding/logo.svg').status_code, 503)

    def test_private_files_need_an_administrator_and_others_get_a_plain_404(self) -> None:
        self.route('media', retrieval='redirect')
        self.memory.put('storage/PRODUCT/secret.pdf', b'%PDF')
        self.assertEqual(
            self.client.get('/media/storage/PRODUCT/secret.pdf').status_code, 302
        )  # admin
        self.client.logout()
        self.assertEqual(self.client.get('/media/storage/PRODUCT/secret.pdf').status_code, 404)
        self.assertEqual(self.client.get('/media/branding/logo.png').status_code, 302)  # public
        self.assertEqual(self.client.get('/media/a/../../etc/passwd').status_code, 404)


class BrandingTests(RoutedBase):
    def setUp(self) -> None:
        super().setUp()
        # The views write and remove the overrides file; never the one shipped in the repo.
        overrides = Path(tempfile.mkdtemp()) / 'branding_overrides.json'
        patcher = patch(
            'backend.apps.accounts.views.branding._BRANDING_OVERRIDES_FILE', str(overrides)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_uploads_and_reset_go_through_the_store(self) -> None:
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.route('media')
        logo = SimpleUploadedFile('logo.png', b'\x89PNG logo', content_type='image/png')
        response = self.client.post(reverse('accounts:branding_save'), {'logo': logo})
        self.assertEqual(response.json()['status'], 'ok')
        self.assertEqual(self.memory.get('branding/logo.png'), b'\x89PNG logo')
        self.assertFalse((self.media_dir / 'branding').exists())
        self.client.post(reverse('accounts:branding_reset'))
        self.assertFalse(self.memory.exists('branding/logo.png'))

    def test_a_failing_store_is_reported_not_a_server_error(self) -> None:
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.route('media')
        self.memory.fail = True
        logo = SimpleUploadedFile('logo.png', b'\x89PNG', content_type='image/png')
        response = self.client.post(reverse('accounts:branding_save'), {'logo': logo})
        self.assertEqual(response.status_code, 502)
        self.assertIn('could not be stored', response.json()['error'])


class CommandTests(RoutedBase):
    def run_command(self, *args: str, stdin: bytes = b'') -> str:
        out = io.StringIO()
        with patch('sys.stdin', io.TextIOWrapper(io.BytesIO(stdin))):
            call_command('storage', *args, stdout=out)
        return out.getvalue()

    def test_backups_upload_prune_list_and_refuse_plaintext(self) -> None:
        import hashlib

        self.route('media', 'backups')
        archive = os.urandom(5000)
        out = self.run_command(
            'upload', '--purpose', 'backups', 'ifinmail_backup_1.tar.gz.gpg', stdin=archive
        )
        self.assertIn(hashlib.sha256(archive).hexdigest(), out)
        self.assertEqual(self.memory.get('backups/ifinmail_backup_1.tar.gz.gpg'), archive)
        with self.assertRaises(CommandError):
            self.run_command('upload', '--purpose', 'backups', 'plain.tar.gz', stdin=b'x')
        self.assertIn(
            'backups/ifinmail_backup_1.tar.gz.gpg', self.run_command('list', '--purpose', 'backups')
        )
        from datetime import UTC, datetime, timedelta

        data, kind, _ = self.memory.objects['backups/ifinmail_backup_1.tar.gz.gpg']
        self.memory.objects['backups/ifinmail_backup_1.tar.gz.gpg'] = (
            data,
            kind,
            datetime.now(UTC) - timedelta(days=40),
        )
        self.memory.put('backups/ifinmail_backup_2.tar.gz.gpg', b'new')
        self.assertIn(
            'Removed 1', self.run_command('prune', '--purpose', 'backups', '--days', '30')
        )
        self.assertEqual(
            [o.key for o in self.memory.list('backups/')], ['backups/ifinmail_backup_2.tar.gz.gpg']
        )

    def test_check_and_status(self) -> None:
        self.route('media')
        self.assertIn('OK', self.run_command('check'))
        self.assertIn('media: memory', self.run_command('status'))
        self.memory.fail = True
        with self.assertRaises(CommandError):
            self.run_command('check')

    def test_sync_copies_what_is_on_the_disk(self) -> None:
        (self.media_dir / 'branding').mkdir()
        (self.media_dir / 'branding' / 'logo.png').write_bytes(b'old logo')
        with self.assertRaises(CommandError):
            self.run_command('sync-media')  # nowhere to copy to yet
        self.route('media')
        self.memory.put('branding/favicon.ico', b'kept')
        (self.media_dir / 'branding' / 'favicon.ico').write_bytes(b'disk')
        self.assertIn('Copied 1 file(s); 1 were already there.', self.run_command('sync-media'))
        self.assertEqual(self.memory.get('branding/logo.png'), b'old logo')
        self.assertEqual(self.memory.get('branding/favicon.ico'), b'kept')


class HealthAndPageTests(RoutedBase):
    def test_the_probe_is_remembered_and_changes_are_audited_once(self) -> None:
        self.route('media')
        self.assertTrue(health.run_probe()['ok'])
        self.memory.fail = True
        health.run_probe()
        health.run_probe()
        self.assertFalse(health.last()['ok'])
        self.assertEqual(AuditEvent.objects.filter(action='storage_probe_failed').count(), 1)
        self.memory.fail = False
        health.run_probe()
        self.assertEqual(AuditEvent.objects.filter(action='storage_probe_ok').count(), 2)

    def test_system_health(self) -> None:
        from backend.apps.accounts.services import system_health

        self.assertIn('this server’s disk', system_health._file_storage().summary)  # noqa: SLF001
        self.route('media', 'backups')
        self.assertEqual(system_health._file_storage().state, 'waiting')  # noqa: SLF001
        health.run_probe()
        self.assertEqual(system_health._file_storage().state, 'ok')  # noqa: SLF001
        self.memory.fail = True
        health.run_probe()
        self.assertEqual(system_health._file_storage().state, 'error')  # noqa: SLF001

    def test_the_page_test_and_copy(self) -> None:
        page = self.client.get(reverse('accounts:file_storage'))
        self.assertContains(page, 'File storage')
        self.assertContains(page, 'This server')
        self.route('media')
        page = self.client.get(reverse('accounts:file_storage'))
        self.assertContains(page, 'Object storage')
        self.assertContains(page, 'Copy media to object storage')
        tested = self.client.post(reverse('accounts:file_storage_probe'), follow=True)
        self.assertContains(tested, 'Wrote, read back')
        (self.media_dir / 'branding').mkdir()
        (self.media_dir / 'branding' / 'logo.png').write_bytes(b'x')
        copied = self.client.post(reverse('accounts:file_storage_sync'), follow=True)
        self.assertContains(copied, 'Copied 1 file(s)')
        self.assertTrue(AuditEvent.objects.filter(action='storage_media_copied').exists())

    def test_it_is_in_the_settings_hub_and_needs_system_manage(self) -> None:
        self.assertIn(
            reverse('accounts:file_storage'),
            self.client.get(reverse('accounts:settings')).content.decode(),
        )
        self.login('support@ifinmail.test', role='support')
        self.assertEqual(self.client.get(reverse('accounts:file_storage')).status_code, 403)
