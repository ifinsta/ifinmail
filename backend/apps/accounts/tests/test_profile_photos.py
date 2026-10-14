"""Profile photos, the contact directory built from them, and the API that sets them.

The image tests use real pictures built with Pillow so the whole path (decode, rotate, crop,
re-encode) runs; the directory tests read the vCards it actually writes.
"""

from __future__ import annotations

import base64
import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from backend.apps.accounts.models import MailUser, UserProfile
from backend.apps.accounts.services import directory
from backend.apps.accounts.services.photos import (
    MAX_UPLOAD_BYTES,
    Crop,
    PhotoError,
    PhotoService,
    process,
)
from backend.apps.accounts.services.roles import RoleService
from backend.apps.core.tests.mail_base import MailTablesTestCase

GOOD = 'Correct-Horse-9'
MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'


def picture(
    size: tuple[int, int] = (200, 100),
    *,
    fmt: str = 'PNG',
    mode: str = 'RGB',
    left: tuple[int, ...] = (220, 30, 30),
    right: tuple[int, ...] = (30, 30, 220),
    exif_orientation: int | None = None,
) -> bytes:
    """Left half one colour, right half another, so a crop can be told apart by its pixels."""
    image = Image.new(mode, size)
    width, height = size
    for x in range(width):
        colour = left if x < width // 2 else right
        for y in range(height):
            image.putpixel((x, y), colour)
    buffer = io.BytesIO()
    kwargs: dict[str, object] = {}
    if exif_orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        kwargs['exif'] = exif
    image.save(buffer, fmt, **kwargs)
    return buffer.getvalue()


def decode(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def near(pixel: tuple[int, ...], expected: tuple[int, int, int], tolerance: int = 40) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(pixel[:3], expected, strict=True))


class CropTests(SimpleTestCase):
    def test_valid_crop(self) -> None:
        self.assertEqual(Crop.parse('0.1', '0.2', '0.5'), Crop(0.1, 0.2, 0.5))

    def test_rejects_garbage_and_out_of_range(self) -> None:
        for args in (
            ('', '', ''),
            ('a', '0', '0.5'),
            ('-0.1', '0', '0.5'),
            ('0', '0', '0.01'),
            ('0', '0', '1.5'),
            ('1.2', '0', '0.5'),
        ):
            with self.subTest(args=args):
                self.assertIsNone(Crop.parse(*args))


class ProcessTests(SimpleTestCase):
    def test_returns_two_square_jpegs(self) -> None:
        large, small = process(picture())
        for data, side in ((large, 256), (small, 96)):
            image = decode(data)
            self.assertEqual(image.format, 'JPEG')
            self.assertEqual(image.size, (side, side))

    def test_centre_square_by_default(self) -> None:
        # 200 x 100, red | blue halves: the centre square straddles the boundary equally.
        image = decode(process(picture())[0])
        self.assertTrue(near(image.getpixel((20, 128)), (220, 30, 30)))
        self.assertTrue(near(image.getpixel((235, 128)), (30, 30, 220)))

    def test_crop_chooses_the_square(self) -> None:
        # The left-most square of a 200 x 100 picture is entirely red.
        image = decode(process(picture(), Crop(0.0, 0.0, 1.0))[0])
        self.assertTrue(near(image.getpixel((10, 128)), (220, 30, 30)))
        self.assertTrue(near(image.getpixel((245, 128)), (220, 30, 30)))
        # The right-most is entirely blue.
        image = decode(process(picture(), Crop(0.5, 0.0, 1.0))[0])
        self.assertTrue(near(image.getpixel((10, 128)), (30, 30, 220)))

    def test_a_crop_beyond_the_edge_is_pulled_inside(self) -> None:
        image = decode(process(picture(), Crop(1.0, 1.0, 1.0))[0])
        self.assertEqual(image.size, (256, 256))

    def test_exif_rotation_is_applied(self) -> None:
        # Stored 200 x 100 with orientation 6 (rotate 90 CW) displays as 100 x 200: the red half
        # becomes the top, so the top of the square is red and the bottom blue.
        image = decode(process(picture(exif_orientation=6, fmt='JPEG'))[0])
        self.assertTrue(near(image.getpixel((128, 10)), (220, 30, 30), 60))
        self.assertTrue(near(image.getpixel((128, 245)), (30, 30, 220), 60))

    def test_metadata_does_not_survive(self) -> None:
        image = decode(process(picture(exif_orientation=3, fmt='JPEG'))[0])
        self.assertEqual(len(image.getexif()), 0)
        self.assertNotIn('icc_profile', image.info)

    def test_transparency_is_flattened_on_white(self) -> None:
        data = picture((100, 100), mode='RGBA', left=(0, 0, 0, 0), right=(0, 0, 0, 0))
        image = decode(process(data)[0])
        self.assertTrue(near(image.getpixel((128, 128)), (255, 255, 255), 8))

    def test_animated_gif_uses_its_first_frame(self) -> None:
        frames = [Image.new('RGB', (80, 80), c) for c in ((200, 0, 0), (0, 200, 0))]
        buffer = io.BytesIO()
        frames[0].save(buffer, 'GIF', save_all=True, append_images=frames[1:])
        image = decode(process(buffer.getvalue())[0])
        self.assertTrue(near(image.getpixel((128, 128)), (200, 0, 0), 60))

    def test_refusals(self) -> None:
        cases = {
            'empty': b'',
            'not an image': b'<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>',
            'too small': picture((40, 40)),
            'too big': b'\x00' * (MAX_UPLOAD_BYTES + 1),
            'truncated': picture((300, 300))[:200],
        }
        for label, data in cases.items():
            with self.subTest(case=label), self.assertRaises(PhotoError):
                process(data)

    def test_formats_outside_the_list_are_refused(self) -> None:
        buffer = io.BytesIO()
        Image.new('RGB', (100, 100)).save(buffer, 'BMP')
        with self.assertRaises(PhotoError):
            process(buffer.getvalue())

    def test_pixel_count_is_limited_before_decoding(self) -> None:
        with (
            patch('backend.apps.accounts.services.photos.MAX_SOURCE_PIXELS', 5_000),
            self.assertRaises(PhotoError),
        ):
            process(picture((200, 100)))


class PhotoBase(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._runtime = tempfile.TemporaryDirectory()
        self.addCleanup(self._runtime.cleanup)
        patcher = patch.dict(os.environ, {'IFINMAIL_RUNTIME_DIR': self._runtime.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        RoleService.ensure_seed()
        self.alice = MailUser.objects.create_user(
            'alice@ifinmail.test', GOOD, is_staff=True, full_name='Alice Adams'
        )
        self.bob = MailUser.objects.create_user('bob@ifinmail.test', GOOD, full_name='Bob')

    def runtime(self, *parts: str) -> Path:
        return Path(self._runtime.name).joinpath(*parts)

    def login(self, user: MailUser) -> None:
        self.client.force_login(user, backend=MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def upload(self, data: bytes | None = None, **extra: str):
        file = SimpleUploadedFile('me.png', data or picture(), content_type='image/png')
        return self.client.post(reverse('accounts:account_photo'), {'photo': file, **extra})


class PhotoServiceTests(PhotoBase):
    def test_set_get_and_remove(self) -> None:
        self.assertIsNone(PhotoService.get(self.alice.pk, 'large'))
        PhotoService.set_photo(self.alice, picture())
        large, sha = PhotoService.get(self.alice.pk, 'large')  # type: ignore[misc]
        self.assertEqual(decode(large).size, (256, 256))
        self.assertEqual(len(sha), 64)
        self.assertEqual(decode(PhotoService.get(self.alice.pk, 'small')[0]).size, (96, 96))  # type: ignore[index]
        self.assertEqual(PhotoService.photo_version(self.alice), sha[:12])
        self.assertTrue(PhotoService.remove_photo(self.alice))
        self.assertIsNone(PhotoService.get(self.alice.pk))
        self.assertFalse(PhotoService.remove_photo(self.alice))

    def test_a_new_photo_changes_the_version(self) -> None:
        PhotoService.set_photo(self.alice, picture())
        first = PhotoService.photo_version(self.alice)
        PhotoService.set_photo(self.alice, picture(left=(10, 200, 10)))
        self.assertNotEqual(first, PhotoService.photo_version(self.alice))

    def test_deleting_the_login_deletes_the_photo(self) -> None:
        PhotoService.set_photo(self.bob, picture())
        self.bob.delete()
        self.assertFalse(UserProfile.objects.filter(user_id=self.bob.pk).exists())


class PhotoViewTests(PhotoBase):
    def test_upload_then_it_shows_in_the_header(self) -> None:
        self.login(self.alice)
        response = self.upload()
        self.assertRedirects(response, reverse('accounts:account'))
        self.assertIsNotNone(PhotoService.get(self.alice.pk))
        page = self.client.get(reverse('accounts:dashboard')).content.decode()
        self.assertIn('ifinmail-avatar--photo', page)
        self.assertIn(f'/accounts/photo/{self.alice.pk}/small/?v=', page)

    def test_the_account_page_offers_the_upload(self) -> None:
        self.login(self.alice)
        page = self.client.get(reverse('accounts:account')).content.decode()
        self.assertIn('data-photo-form', page)
        self.assertIn('ifinmail-photo.js', page)

    def test_a_bad_file_changes_nothing_and_says_why(self) -> None:
        self.login(self.alice)
        response = self.upload(
            b'not a picture',
        )
        self.assertRedirects(response, reverse('accounts:account'))
        self.assertIsNone(PhotoService.get(self.alice.pk))
        shown = [str(m) for m in response.wsgi_request._messages]  # type: ignore[attr-defined]
        self.assertTrue(any('picture' in m for m in shown))

    def test_crop_fields_are_used(self) -> None:
        self.login(self.alice)
        self.upload(crop_x='0.5', crop_y='0', crop_size='1')
        image = decode(PhotoService.get(self.alice.pk, 'large')[0])  # type: ignore[index]
        self.assertTrue(near(image.getpixel((10, 128)), (30, 30, 220)))

    def test_the_image_is_served_with_caching_headers(self) -> None:
        PhotoService.set_photo(self.alice, picture())
        self.login(self.alice)
        url = reverse('accounts:photo', args=[self.alice.pk, 'small'])
        first = self.client.get(url)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first['Content-Type'], 'image/jpeg')
        self.assertEqual(first['X-Content-Type-Options'], 'nosniff')
        self.assertIn('private', first['Cache-Control'])
        again = self.client.get(url, HTTP_IF_NONE_MATCH=first['ETag'])
        self.assertEqual(again.status_code, 304)

    def test_other_people_cannot_fetch_it_unless_they_manage_mailboxes(self) -> None:
        PhotoService.set_photo(self.bob, picture())
        url = reverse('accounts:photo', args=[self.bob.pk, 'small'])
        self.login(self.alice)  # staff but without mail.manage
        with patch('backend.apps.accounts.views.photos._sees_others', return_value=False):
            self.assertEqual(self.client.get(url).status_code, 404)
        with patch('backend.apps.accounts.views.photos._sees_others', return_value=True):
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_anonymous_gets_nothing_and_unknown_sizes_404(self) -> None:
        PhotoService.set_photo(self.alice, picture())
        url = reverse('accounts:photo', args=[self.alice.pk, 'small'])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.login(self.alice)
        bad = reverse('accounts:photo', args=[self.alice.pk, 'huge'])
        self.assertEqual(self.client.get(bad).status_code, 404)

    def test_remove(self) -> None:
        PhotoService.set_photo(self.alice, picture())
        self.login(self.alice)
        self.client.post(reverse('accounts:account_photo_remove'))
        self.assertIsNone(PhotoService.get(self.alice.pk))

    def test_get_is_not_allowed_on_changing_endpoints(self) -> None:
        self.login(self.alice)
        for name in ('account_photo', 'account_photo_remove', 'account_directory_visibility'):
            with self.subTest(view=name):
                self.assertEqual(self.client.get(reverse(f'accounts:{name}')).status_code, 405)


class DirectoryTests(PhotoBase):
    def setUp(self) -> None:
        super().setUp()
        self.carol = MailUser.objects.create_user(
            'carol@ifinmail.test', GOOD, full_name='Carol; "C," O\'Neil'
        )

    def vcards(self) -> dict[str, str]:
        folder = self.runtime('directory', 'people')
        return {p.name: p.read_bytes().decode('utf-8') for p in folder.glob('*.vcf')}

    def manifest(self) -> dict[str, object]:
        return json.loads(self.runtime('directory', 'manifest.json').read_text())

    def test_off_by_default_and_publishes_nothing(self) -> None:
        summary = directory.publish()
        self.assertFalse(summary['enabled'])
        self.assertEqual(self.vcards(), {})
        self.assertEqual(self.manifest()['enabled'], False)

    def test_enabled_lists_active_visible_mailboxes(self) -> None:
        MailUser.objects.filter(pk=self.bob.pk).update(is_active=False)
        PhotoService.set_directory_hidden(self.carol, True)
        directory.set_enabled(True)
        summary = directory.publish()
        self.assertEqual(summary['count'], 1)
        manifest = self.manifest()
        self.assertEqual(manifest['users'], ['alice@ifinmail.test'])
        self.assertTrue(manifest['enabled'])
        self.assertEqual(list(self.vcards()), [f'{self.alice.pk}.vcf'])

    def test_vcard_content(self) -> None:
        PhotoService.set_photo(self.alice, picture())
        directory.set_enabled(True)
        directory.publish()
        card = self.vcards()[f'{self.alice.pk}.vcf']
        self.assertTrue(card.startswith('BEGIN:VCARD\r\nVERSION:3.0\r\n'))
        self.assertIn(f'UID:ifinmail-{self.alice.pk}', card)
        self.assertIn('FN:Alice Adams', card)
        self.assertIn('N:Adams;Alice;;;', card)
        self.assertIn('EMAIL;TYPE=INTERNET,PREF:alice@ifinmail.test', card)
        self.assertIn('ORG:ifinmail.test', card)
        self.assertTrue(card.endswith('END:VCARD\r\n'))
        for line in card.split('\r\n'):
            self.assertLessEqual(len(line.encode()), 75, line[:40])
        unfolded = card.replace('\r\n ', '')
        encoded = unfolded.split('PHOTO;ENCODING=b;TYPE=JPEG:')[1].split('\r\n')[0]
        self.assertEqual(decode(base64.b64decode(encoded)).size, (256, 256))

    def test_names_are_escaped(self) -> None:
        directory.set_enabled(True)
        directory.publish()
        card = self.vcards()[f'{self.carol.pk}.vcf']
        self.assertIn('FN:Carol\\; "C\\," O\'Neil', card)

    def test_a_person_without_a_name_is_listed_by_their_address(self) -> None:
        MailUser.objects.filter(pk=self.bob.pk).update(full_name='')
        directory.set_enabled(True)
        directory.publish()
        self.assertIn('FN:bob', self.vcards()[f'{self.bob.pk}.vcf'])

    def test_republishing_unchanged_data_writes_nothing(self) -> None:
        directory.set_enabled(True)
        first = directory.publish()
        second = directory.publish()
        self.assertEqual(first['written'], 3)
        self.assertEqual((second['written'], second['removed']), (0, 0))

    def test_switching_off_withdraws_everything(self) -> None:
        directory.set_enabled(True)
        directory.publish()
        self.assertEqual(len(self.vcards()), 3)
        directory.set_enabled(False)
        summary = directory.publish()
        self.assertEqual(summary['removed'], 3)
        self.assertEqual(self.vcards(), {})
        self.assertFalse(self.manifest()['enabled'])

    def test_manifest_digest_ignores_the_timestamp(self) -> None:
        directory.set_enabled(True)
        directory.publish()
        first = self.manifest()['sha256']
        directory.publish()
        self.assertEqual(first, self.manifest()['sha256'])

    def test_hiding_yourself_removes_your_card(self) -> None:
        directory.set_enabled(True)
        directory.publish()
        self.login(self.bob)
        self.client.post(reverse('accounts:account_directory_visibility'))  # unchecked = hidden
        directory.publish()
        self.assertNotIn(f'{self.bob.pk}.vcf', self.vcards())

    def test_admin_toggle_needs_mail_manage_and_queues_a_publish(self) -> None:
        self.login(self.bob)  # a plain mailbox: no console access
        self.client.post(reverse('accounts:directory_toggle'), {'enabled': 'on'})
        self.assertFalse(directory.enabled())
        admin = MailUser.objects.create_user(
            'root@ifinmail.test', GOOD, is_staff=True, is_superuser=True
        )
        self.login(admin)
        with patch.object(directory.DirectoryService, '_queue') as queued:
            self.client.post(reverse('accounts:directory_toggle'), {'enabled': 'on'})
        self.assertTrue(directory.enabled())
        queued.assert_called_once()
        with patch.object(directory.DirectoryService, '_queue') as queued:
            self.client.post(reverse('accounts:directory_toggle'), {})
        self.assertFalse(directory.enabled())
        queued.assert_called_once()

    def test_a_photo_change_queues_a_publish_only_when_enabled(self) -> None:
        with patch.object(directory.DirectoryService, '_queue') as queued:
            PhotoService.set_photo(self.alice, picture())
            queued.assert_not_called()
            directory.set_enabled(True)  # the service flag only; the toggle view queues itself
            PhotoService.set_photo(self.alice, picture(left=(0, 200, 0)))
            queued.assert_called_once()

    def test_the_mailboxes_page_shows_the_panel(self) -> None:
        admin = MailUser.objects.create_user(
            'root@ifinmail.test', GOOD, is_staff=True, is_superuser=True
        )
        self.login(admin)
        page = self.client.get(reverse('accounts:mailboxes')).content.decode()
        self.assertIn('Contact directory', page)
        self.assertIn(reverse('accounts:directory_toggle'), page)


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class PhotoApiTests(PhotoBase):
    def setUp(self) -> None:
        super().setUp()
        from backend.apps.accounts.services.tokens import TokenService, key_id
        from backend.apps.domains.models import Domain
        from backend.apps.mail.services import MailboxService

        Domain.objects.create(name='ifinmail.test') if not Domain.objects.exists() else None
        MailboxService.create('ifinmail.test', 'sales', GOOD)
        self.owner = MailUser.objects.create_user(
            'root@ifinmail.test', GOOD, is_staff=True, is_superuser=True
        )
        row, token = TokenService.create(
            self.owner, 'integration', ['console.access', 'mail.manage'], expires_in_days=30
        )
        self.key, self.secret = key_id(row.prefix), token.split('.', 2)[2]
        auth = base64.b64encode(f'{self.key}:{self.secret}'.encode()).decode()
        self.auth = {'HTTP_AUTHORIZATION': f'Basic {auth}'}
        self.url = '/api/v1/mailboxes/sales@ifinmail.test/photo'

    def test_set_get_delete_round_trip(self) -> None:
        self.assertEqual(self.client.get(self.url, **self.auth).status_code, 404)
        file = SimpleUploadedFile('p.png', picture(), content_type='image/png')
        response = self.client.post(self.url, {'photo': file}, **self.auth)
        self.assertEqual(response.status_code, 200, response.content)
        got = self.client.get(self.url, **self.auth)
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got['Content-Type'], 'image/jpeg')
        self.assertEqual(decode(got.content).size, (256, 256))
        self.assertEqual(self.client.delete(self.url, **self.auth).status_code, 204)
        self.assertEqual(self.client.get(self.url, **self.auth).status_code, 404)

    def test_crop_parameters(self) -> None:
        file = SimpleUploadedFile('p.png', picture(), content_type='image/png')
        self.client.post(
            self.url, {'photo': file, 'crop_x': '0.5', 'crop_y': '0', 'crop_size': '1'}, **self.auth
        )
        image = decode(self.client.get(self.url, **self.auth).content)
        self.assertTrue(near(image.getpixel((10, 128)), (30, 30, 220)))

    def test_a_bad_crop_and_a_bad_file_are_422(self) -> None:
        good = SimpleUploadedFile('p.png', picture(), content_type='image/png')
        bad_crop = self.client.post(
            self.url, {'photo': good, 'crop_x': '2', 'crop_y': '0', 'crop_size': '1'}, **self.auth
        )
        self.assertEqual(bad_crop.status_code, 422)
        junk = SimpleUploadedFile('p.png', b'nope', content_type='image/png')
        self.assertEqual(self.client.post(self.url, {'photo': junk}, **self.auth).status_code, 422)

    def test_unknown_mailbox_and_missing_credentials(self) -> None:
        file = SimpleUploadedFile('p.png', picture(), content_type='image/png')
        missing = self.client.post(
            '/api/v1/mailboxes/ghost@ifinmail.test/photo', {'photo': file}, **self.auth
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_a_console_login_cannot_be_changed_through_a_key(self) -> None:
        file = SimpleUploadedFile('p.png', picture(), content_type='image/png')
        response = self.client.post(
            '/api/v1/mailboxes/root@ifinmail.test/photo', {'photo': file}, **self.auth
        )
        self.assertIn(response.status_code, (403, 404, 422))
        self.assertIsNone(PhotoService.get(self.owner.pk))
