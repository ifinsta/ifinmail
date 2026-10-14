"""Tests for the pure parts of release.py.  Run: python -m unittest clients/android/scripts/test_release.py"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release  # noqa: E402


class VersionTests(unittest.TestCase):
    def test_the_build_number_rises_with_the_version(self) -> None:
        order = ['1.0.0', '1.0.1', '1.1.0', '1.9.9', '2.0.0', '10.0.0']
        codes = [release.version_code(release.parse_version(v)) for v in order]
        self.assertEqual(codes, sorted(codes))
        self.assertEqual(len(set(codes)), len(codes))
        self.assertEqual(release.version_code(release.parse_version('1.4.2')), 10402)

    def test_the_original_two_part_version_is_read(self) -> None:
        self.assertEqual(release.parse_version('1.0'), (1, 0, 0))

    def test_nonsense_is_refused(self) -> None:
        for bad in ('', 'v1.2.3', '1.2.3.4', '1.100.0', 'latest'):
            with self.assertRaises(release.ToolError, msg=bad):
                release.parse_version(bad)


class PropertiesTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'gradle.properties'
        patcher = mock.patch.object(release, 'PROPS', self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_value_is_replaced_and_everything_else_is_kept(self) -> None:
        self.path.write_bytes(b'# note\r\nifinmail.versionCode=1\r\nother=x\r\nifinmail.versionName=1.0\r\n')
        release.set_prop('ifinmail.versionCode', '10100')
        text = self.path.read_bytes().decode()
        self.assertEqual(text, '# note\r\nifinmail.versionCode=10100\r\nother=x\r\nifinmail.versionName=1.0\r\n')

    def test_a_missing_value_is_appended(self) -> None:
        self.path.write_text('a=1\n', encoding='utf-8')
        release.set_prop('b', '2')
        self.assertEqual(release.read_props(), {'a': '1', 'b': '2'})


class UploadTests(unittest.TestCase):
    def test_the_multipart_body_carries_fields_and_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            apk = Path(tmp) / 'app.apk'
            apk.write_bytes(b'PK\x03\x04binary')
            body, ctype = release.multipart({'channel': 'beta', 'notes': 'Hi'}, 'file', apk)
        boundary = ctype.split('boundary=')[1].encode()
        self.assertIn(b'name="channel"\r\n\r\nbeta', body)
        self.assertIn(b'name="file"; filename="app.apk"', body)
        self.assertIn(b'PK\x03\x04binary', body)
        self.assertTrue(body.endswith(b'--' + boundary + b'--\r\n'))


class ServerAddressTests(unittest.TestCase):
    def _args(self, server: str):
        return mock.Mock(server=server)

    def test_plain_http_is_only_for_this_machine(self) -> None:
        self.assertEqual(release.server_url(self._args('http://127.0.0.1:8000/')), 'http://127.0.0.1:8000')
        for bad in ('http://mail.example.org', 'ftp://x', 'mail.example.org'):
            with self.assertRaises(release.ToolError, msg=bad):
                release.server_url(self._args(bad))


if __name__ == '__main__':
    unittest.main()
