"""The MFA enrollment page must show a QR code, so its library must ship in the image."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from backend.apps.accounts.views.mfa import _qr_data_uri


class MFAQRCodeTests(SimpleTestCase):
    def test_enrollment_uri_renders_as_an_svg_qr_code(self) -> None:
        uri = _qr_data_uri('otpauth://totp/ifinmail:admin@ifinmail.test?secret=ABCDEF&issuer=ifinmail')
        self.assertTrue(uri.startswith('data:image/svg+xml;base64,'))

    def test_production_lock_installs_qrcode(self) -> None:
        # The view falls back silently without the package, so a missing pin is easy to miss:
        # the image installs requirements/prod.lock, not base.txt.
        lock = Path(settings.BASE_DIR, 'requirements', 'prod.lock').read_text(encoding='utf-8')
        self.assertRegex(lock, r'(?m)^qrcode==')
