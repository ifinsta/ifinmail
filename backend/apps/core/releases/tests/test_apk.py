"""releases — the APK inspector: what it reads, and what it refuses."""

from __future__ import annotations

import hashlib
import io
import struct
import zipfile

from django.test import SimpleTestCase

from backend.apps.core.releases.services.apk import ApkError, inspect_apk, parse_manifest
from backend.apps.core.releases.tests.apk_factory import build_apk, manifest_xml


def inspect(data: bytes):
    return inspect_apk(io.BytesIO(data))


class ManifestTests(SimpleTestCase):
    def test_reads_package_version_and_sdk_levels(self) -> None:
        found = parse_manifest(
            manifest_xml(
                package='com.ifinmail', version_code=42, version_name='2.1.0', min_sdk=24, target_sdk=36
            )
        )
        self.assertEqual(found['manifest.package'], 'com.ifinmail')
        self.assertEqual(found['manifest.versionCode'], 42)
        self.assertEqual(found['manifest.versionName'], '2.1.0')
        self.assertEqual(found['uses-sdk.minSdkVersion'], 24)
        self.assertEqual(found['uses-sdk.targetSdkVersion'], 36)

    def test_truncated_or_foreign_data_is_refused_not_crashed_on(self) -> None:
        good = manifest_xml(
            package='com.ifinmail', version_code=1, version_name='1', min_sdk=24, target_sdk=36
        )
        for bad in (b'', b'not xml at all', good[:20], good[: len(good) // 2], b'\x03\x00' * 40):
            with self.subTest(length=len(bad)), self.assertRaises(ApkError):
                parse_manifest(bad)


class InspectTests(SimpleTestCase):
    def test_a_signed_apk_is_described_completely(self) -> None:
        data = build_apk(version_code=7, version_name='1.4.0', certificate=b'certificate-A')
        info = inspect(data)
        self.assertEqual(info.package, 'com.ifinmail')
        self.assertEqual(info.version_code, 7)
        self.assertEqual(info.version_name, '1.4.0')
        self.assertEqual(info.min_sdk, 24)
        self.assertTrue(info.signed)
        self.assertEqual(info.signing_cert_sha256, hashlib.sha256(b'certificate-A').hexdigest())
        self.assertEqual(info.sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(info.size_bytes, len(data))

    def test_different_keys_give_different_certificate_digests(self) -> None:
        one = inspect(build_apk(certificate=b'certificate-A')).signing_cert_sha256
        two = inspect(build_apk(certificate=b'certificate-B')).signing_cert_sha256
        self.assertNotEqual(one, two)

    def test_an_unsigned_apk_is_reported_unsigned(self) -> None:
        info = inspect(build_apk(certificate=None))
        self.assertFalse(info.signed)
        self.assertEqual(info.signing_cert_sha256, '')

    def test_a_v1_only_signature_counts_as_signed_without_a_certificate_digest(self) -> None:
        info = inspect(build_apk(certificate=None, v1_signature=True))
        self.assertTrue(info.signed)
        self.assertEqual(info.signing_cert_sha256, '')

    def test_files_that_are_not_apks_say_why(self) -> None:
        with self.assertRaisesMessage(ApkError, 'too small'):
            inspect(b'MZ' + b'\x00' * 100)
        with self.assertRaisesMessage(ApkError, 'not a ZIP'):
            inspect(b'This is a text file. ' * 100)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('readme.txt', 'x' * 2000)
        with self.assertRaisesMessage(ApkError, 'AndroidManifest.xml'):
            inspect(buffer.getvalue())

    def test_a_manifest_that_is_plain_text_is_refused(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('AndroidManifest.xml', '<manifest package="x"/>' + ' ' * 2000)
        with self.assertRaisesMessage(ApkError, 'compiled'):
            inspect(buffer.getvalue())

    def test_a_damaged_signing_block_does_not_crash_the_inspector(self) -> None:
        data = bytearray(build_apk(certificate=b'certificate-A'))
        magic = data.find(b'APK Sig Block 42')
        # Corrupt the signer length so the nested structure points past its parent.
        struct.pack_into('<I', data, magic - 60, 0xFFFFFF)
        try:
            info = inspect(bytes(data))
        except ApkError:
            return  # refused with a clear message: fine
        self.assertTrue(info.signed)  # or read what could be read: never an unhandled exception
