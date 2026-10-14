"""releases — publishing rules and what a device is told."""

from __future__ import annotations

import shutil
import tempfile
from collections import Counter
from datetime import timedelta
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from backend.apps.core.releases.models import AppRelease, DeviceCheckin
from backend.apps.core.releases.services import ReleaseService, manifest_for, rollout_bucket
from backend.apps.core.releases.tests.apk_factory import build_apk
from backend.apps.core.storage.models import StoredFile
from backend.apps.core.types.enums import StorageVisibility


def upload(**kwargs: object) -> SimpleUploadedFile:
    return SimpleUploadedFile(
        'app-release.apk', build_apk(**kwargs), content_type='application/octet-stream'
    )


class ReleaseTestCase(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.media = Path(tempfile.mkdtemp(prefix='ifinmail-releases-'))
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)

    def publish(self, version_code: int = 1, **kwargs: object) -> AppRelease:
        apk = {
            key: kwargs.pop(key)
            for key in list(kwargs)
            if key in ('package', 'version_name', 'min_sdk', 'certificate', 'v1_signature')
        }
        apk.setdefault('version_name', f'1.{version_code}.0')
        return ReleaseService.publish(upload=upload(version_code=version_code, **apk), **kwargs)


class PublishTests(ReleaseTestCase):
    def test_publishing_reads_the_apk_and_stores_a_public_file(self) -> None:
        release = self.publish(3, notes='  Faster sync  ', actor='api:ifm_x (a@b.test)')
        self.assertEqual(release.version_code, 3)
        self.assertEqual(release.version_name, '1.3.0')
        self.assertEqual(release.package_name, 'com.ifinmail')
        self.assertEqual(release.notes, 'Faster sync')
        self.assertTrue(release.is_published)
        self.assertIsNotNone(release.published_at)
        self.assertEqual(release.published_by, 'api:ifm_x (a@b.test)')
        self.assertEqual(len(release.sha256), 64)
        stored = StoredFile.objects.get(pk=release.stored_file_id)
        self.assertEqual(stored.visibility, StorageVisibility.PUBLIC.value)
        self.assertEqual(stored.entity_type, 'APP_RELEASE')
        self.assertEqual(stored.entity_id, release.id)
        self.assertEqual(stored.size_bytes, release.size_bytes)
        self.assertTrue(Path(self.media, stored.file.name).is_file())
        self.assertTrue(ReleaseService.download_path(release).startswith('/media/storage/'))

    def test_an_unpublished_upload_is_kept_but_not_offered(self) -> None:
        release = self.publish(1, publish=False)
        self.assertFalse(release.is_published)
        self.assertIsNone(release.published_at)
        self.assertIsNone(ReleaseService.latest_published())

    def test_another_application_is_refused(self) -> None:
        with self.assertRaisesMessage(ValueError, 'com.other.app'):
            self.publish(1, package='com.other.app')
        self.assertEqual(AppRelease.objects.count(), 0)
        self.assertEqual(StoredFile.objects.count(), 0)

    @override_settings(RELEASES_ANDROID_PACKAGE='org.example.mail')
    def test_a_white_label_package_can_be_configured(self) -> None:
        release = self.publish(1, package='org.example.mail')
        self.assertEqual(release.package_name, 'org.example.mail')

    def test_an_unsigned_apk_is_refused(self) -> None:
        with self.assertRaisesMessage(ValueError, 'not signed'):
            self.publish(1, certificate=None)

    def test_a_repeated_version_code_is_refused_per_channel(self) -> None:
        self.publish(5)
        with self.assertRaisesMessage(ValueError, 'already exists'):
            self.publish(5)
        beta = self.publish(5, channel='beta')  # the same code on another channel is fine
        self.assertEqual(beta.channel, 'beta')
        self.assertEqual(StoredFile.objects.count(), 2)  # the refused upload left no file behind

    def test_a_different_signing_key_is_refused(self) -> None:
        self.publish(1, certificate=b'certificate-A')
        with self.assertRaisesMessage(ValueError, 'different key'):
            self.publish(2, certificate=b'certificate-B')
        self.assertEqual(self.publish(2, certificate=b'certificate-A').version_code, 2)

    def test_a_certificate_that_cannot_be_read_is_refused_once_a_key_is_known(self) -> None:
        self.publish(1, certificate=b'certificate-A')
        with self.assertRaisesMessage(ValueError, 'Could not read the signing certificate'):
            self.publish(2, certificate=None, v1_signature=True)

    def test_rollout_and_mandatory_are_validated(self) -> None:
        with self.assertRaisesMessage(ValueError, 'between 0 and 100'):
            self.publish(1, rollout_percent=150)
        with self.assertRaisesMessage(ValueError, 'every device'):
            self.publish(1, mandatory=True, rollout_percent=20)
        with self.assertRaisesMessage(ValueError, 'Unknown channel'):
            self.publish(1, channel='nightly')

    def test_not_an_apk_is_refused_with_the_reason(self) -> None:
        junk = SimpleUploadedFile('x.apk', b'hello' * 500, content_type='application/octet-stream')
        with self.assertRaisesMessage(ValueError, 'not a ZIP'):
            ReleaseService.publish(upload=junk)

    def test_withdrawing_restoring_and_deleting(self) -> None:
        release = self.publish(1)
        path = Path(self.media, release.stored_file.file.name)
        ReleaseService.update(release, is_published=False, notes='Pulled: crash on start')
        self.assertIsNone(ReleaseService.latest_published())
        ReleaseService.update(release, is_published=True)
        self.assertEqual(ReleaseService.latest_published().pk, release.pk)
        ReleaseService.delete(release)
        self.assertFalse(AppRelease.objects.exists())
        self.assertFalse(StoredFile.objects.exists())
        self.assertFalse(path.exists())


class CheckTests(ReleaseTestCase):
    def test_a_device_on_the_latest_build_has_nothing_to_do(self) -> None:
        self.publish(2)
        decision = ReleaseService.check(version_code=2)
        self.assertFalse(decision.update_available)
        self.assertFalse(decision.required)
        self.assertEqual(decision.latest.version_code, 2)

    def test_an_older_device_is_offered_the_newest_build(self) -> None:
        self.publish(1)
        self.publish(2)
        self.publish(3)
        decision = ReleaseService.check(version_code=1)
        self.assertTrue(decision.update_available)
        self.assertFalse(decision.required)
        self.assertEqual(decision.latest.version_code, 3)

    def test_without_an_installed_version_only_the_latest_is_described(self) -> None:
        self.publish(4)
        decision = ReleaseService.check(version_code=None)
        self.assertFalse(decision.update_available)
        self.assertEqual(decision.latest.version_code, 4)

    def test_no_releases_means_nothing_to_offer(self) -> None:
        decision = ReleaseService.check(version_code=1)
        self.assertIsNone(decision.latest)
        self.assertFalse(decision.update_available)

    def test_a_mandatory_release_forces_everything_below_it(self) -> None:
        self.publish(1)
        self.publish(2, mandatory=True)
        self.publish(3)
        below = ReleaseService.check(version_code=1)
        self.assertTrue(below.required)
        self.assertEqual(below.minimum_version_code, 2)
        at_floor = ReleaseService.check(version_code=2)
        self.assertFalse(at_floor.required)
        self.assertTrue(at_floor.update_available)  # 3 is offered but optional

    def test_unpublished_and_other_channel_builds_are_never_offered(self) -> None:
        self.publish(1)
        self.publish(2, publish=False)
        self.publish(9, channel='beta')
        decision = ReleaseService.check(version_code=1)
        self.assertFalse(decision.update_available)
        beta = ReleaseService.check(channel='beta', version_code=1)
        self.assertEqual(beta.latest.version_code, 9)

    def test_a_build_the_device_cannot_run_is_skipped(self) -> None:
        self.publish(1, min_sdk=24)
        self.publish(2, min_sdk=34)
        old_phone = ReleaseService.check(version_code=1, sdk_int=30)
        self.assertFalse(old_phone.update_available)
        new_phone = ReleaseService.check(version_code=1, sdk_int=35)
        self.assertEqual(new_phone.latest.version_code, 2)

    def test_staged_rollout_is_stable_per_device_and_roughly_the_right_share(self) -> None:
        self.publish(1)
        self.publish(2, rollout_percent=30)
        offered = 0
        for n in range(400):
            device = f'device-{n:05d}'
            first = ReleaseService.check(version_code=1, device_id=device)
            again = ReleaseService.check(version_code=1, device_id=device)
            self.assertEqual(first.update_available, again.update_available)  # stable
            offered += first.update_available
        self.assertGreater(offered, 400 * 0.30 * 0.7)
        self.assertLess(offered, 400 * 0.30 * 1.3)
        # a device that does not identify itself only ever gets fully rolled-out builds
        anonymous = ReleaseService.check(version_code=1)
        self.assertEqual(anonymous.latest.version_code, 1)
        self.assertFalse(anonymous.update_available)

    def test_widening_a_rollout_only_adds_devices(self) -> None:
        release = self.publish(2, rollout_percent=10)
        devices = [f'device-{n:05d}' for n in range(300)]
        small = {d for d in devices if ReleaseService.check(version_code=1, device_id=d).update_available}
        ReleaseService.update(release, rollout_percent=50)
        wider = {d for d in devices if ReleaseService.check(version_code=1, device_id=d).update_available}
        self.assertTrue(small <= wider)
        self.assertGreater(len(wider), len(small))

    def test_buckets_are_spread_and_deterministic(self) -> None:
        counts = Counter(rollout_bucket(f'd{n}', 'android', 'stable', 7) // 10 for n in range(2000))
        self.assertEqual(set(counts), set(range(10)))
        self.assertEqual(rollout_bucket('abc', 'android', 'stable', 7), rollout_bucket('abc', 'android', 'stable', 7))


class ManifestTests(ReleaseTestCase):
    def test_the_manifest_carries_what_a_device_must_verify(self) -> None:
        release = self.publish(3, notes='Notes')
        body = manifest_for(
            ReleaseService.check(version_code=1),
            platform='android',
            channel='stable',
            base_url='https://mail.example.org/',
        )
        latest = body['latest']
        self.assertTrue(body['update_available'])
        self.assertEqual(body['schema'], 1)
        self.assertEqual(latest['version_code'], 3)
        self.assertEqual(latest['sha256'], release.sha256)
        self.assertEqual(latest['size_bytes'], release.size_bytes)
        self.assertEqual(latest['signing_cert_sha256'], release.signing_cert_sha256)
        self.assertEqual(latest['package'], 'com.ifinmail')
        self.assertTrue(latest['download_url'].startswith('https://mail.example.org/media/storage/'))

    def test_an_empty_manifest_is_well_formed(self) -> None:
        body = manifest_for(ReleaseService.check(version_code=1), platform='android', channel='stable')
        self.assertIsNone(body['latest'])
        self.assertFalse(body['update_available'])


class CheckinTests(ReleaseTestCase):
    def test_checkins_are_upserted_and_counted_per_version(self) -> None:
        for device, code in (('device-aaaa1', 1), ('device-bbbb2', 1), ('device-cccc3', 2)):
            ReleaseService.record_checkin(
                platform='android', device_id=device, channel='stable', version_code=code,
                version_name=f'1.{code}.0', sdk_int=34,
            )
        ReleaseService.record_checkin(
            platform='android', device_id='device-aaaa1', channel='stable', version_code=2,
            version_name='1.2.0', sdk_int=34,
        )
        self.assertEqual(DeviceCheckin.objects.count(), 3)
        self.assertEqual(DeviceCheckin.objects.get(device_id='device-aaaa1').checks, 2)
        rows = {r.version_code: r.devices for r in ReleaseService.adoption()}
        self.assertEqual(rows, {2: 2, 1: 1})
        self.assertEqual(ReleaseService.active_device_count(), 3)

    def test_a_missing_device_id_records_nothing(self) -> None:
        ReleaseService.record_checkin(platform='android', device_id='', channel='stable', version_code=1)
        self.assertEqual(DeviceCheckin.objects.count(), 0)

    def test_silent_devices_leave_the_active_count_and_are_pruned(self) -> None:
        ReleaseService.record_checkin(platform='android', device_id='device-old-1', channel='stable', version_code=1)
        DeviceCheckin.objects.update(last_seen=timezone.now() - timedelta(days=45))
        self.assertEqual(ReleaseService.active_device_count(), 0)
        self.assertEqual(ReleaseService.prune_checkins(days=30), 1)
        self.assertEqual(DeviceCheckin.objects.count(), 0)


class CommandTests(ReleaseTestCase):
    def test_the_command_publishes_a_file_and_lists_it(self) -> None:
        import io

        from django.core.management import call_command
        from django.core.management.base import CommandError

        apk = Path(self.media, 'build.apk')
        apk.write_bytes(build_apk(version_code=9, version_name='2.0.0'))
        out = io.StringIO()
        call_command('publish_release', str(apk), '--notes', 'From CI', '--rollout', '40', stdout=out)
        self.assertIn('2.0.0', out.getvalue())
        release = AppRelease.objects.get()
        self.assertEqual((release.version_code, release.rollout_percent, release.notes), (9, 40, 'From CI'))
        listing = io.StringIO()
        call_command('publish_release', '--list', stdout=listing)
        self.assertIn('2.0.0', listing.getvalue())
        self.assertIn('40%', listing.getvalue())
        with self.assertRaises(CommandError):
            call_command('publish_release', str(apk))  # same version code again
        with self.assertRaises(CommandError):
            call_command('publish_release', str(Path(self.media, 'missing.apk')))


class TaskTests(ReleaseTestCase):
    def test_the_prune_task_is_registered_and_scheduled(self) -> None:
        from django.conf import settings

        from backend.apps.core.releases.tasks import prune_checkins

        ReleaseService.record_checkin(
            platform='android', device_id='device-stale-1', channel='stable', version_code=1
        )
        DeviceCheckin.objects.update(last_seen=timezone.now() - timedelta(days=400))
        self.assertEqual(prune_checkins(), 1)
        scheduled = {entry['task'] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
        self.assertIn('releases.prune_checkins', scheduled)
