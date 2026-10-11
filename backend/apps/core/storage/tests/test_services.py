"""storage — StorageService upload tests (single source of truth)."""

import os
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from backend.apps.accounts.models import MailUser
from backend.apps.core.storage.models.stored_file import StoredFile
from backend.apps.core.storage.services import StorageService
from backend.apps.core.tests.mail_base import MailTablesTestCase

_PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x02\x00\x00\x00\x90wS\xde'
)


def _png(name: str = 'logo.png') -> SimpleUploadedFile:
    return SimpleUploadedFile(name, _PNG, content_type='image/png')


class StorageUploadTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.media = os.path.join(self.tmp, 'media')
        os.makedirs(self.media, exist_ok=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.user = MailUser.objects.create_user('u@ifinmail.test', 'Correct-Horse-9')

    def _upload(self, **kwargs):
        args = {'file': _png(), 'user': self.user, 'entity_type': 'PRODUCT'}
        args.update(kwargs)
        return StorageService.upload(**args)

    def test_valid_upload_persists_metadata(self) -> None:
        stored = self._upload()
        self.assertIsInstance(stored, StoredFile)
        self.assertEqual(stored.original_filename, 'logo.png')
        self.assertEqual(stored.content_type, 'image/png')
        self.assertEqual(stored.size_bytes, len(_PNG))
        self.assertEqual(stored.visibility, 'PRIVATE')
        self.assertTrue(stored.file.name.startswith('storage/PRODUCT/'))
        self.assertTrue(os.path.exists(stored.file.path))

    def test_upload_paths_are_unique(self) -> None:
        first = self._upload()
        second = self._upload()
        self.assertNotEqual(first.file.name, second.file.name)

    def test_unset_entity_id_stores_null(self) -> None:
        stored = self._upload()
        stored.refresh_from_db()
        self.assertIsNone(stored.entity_id)

    def test_forbidden_extension_is_rejected(self) -> None:
        bad = SimpleUploadedFile('run.exe', b'MZ', content_type='application/octet-stream')
        with self.assertRaises(ValidationError):
            StorageService.upload(file=bad, user=self.user, entity_type='PRODUCT')

    def test_mime_mismatch_is_rejected(self) -> None:
        bad = SimpleUploadedFile('logo.png', _PNG, content_type='text/plain')
        with self.assertRaises(ValidationError):
            StorageService.upload(file=bad, user=self.user, entity_type='PRODUCT')

    def test_oversize_is_rejected(self) -> None:
        with (
            patch('backend.apps.core.storage.services._MAX_UPLOAD_SIZE', 10),
            self.assertRaises(ValidationError),
        ):
            self._upload()
