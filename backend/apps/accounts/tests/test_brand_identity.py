"""The ifinmail house mark and two-weight wordmark.

The product's own identity appears only for the unrenamed brand without an uploaded
logo; an uploaded logo always wins and a renamed brand shows its name as text.
Also checks the shipped icon files, so a broken export fails the suite.
"""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.config.branding import (
    BrandingConfig,
    email_brand_context,
)

LOGO = '/media/branding/logo.png'
DEFAULT = BrandingConfig()
WITH_LOGO = BrandingConfig(logo_url=LOGO)
RENAMED = BrandingConfig(name='Acme Mail')
RENAMED_WITH_LOGO = BrandingConfig(name='Acme Mail', logo_url=LOGO)
ICONS = Path(settings.BASE_DIR) / 'frontend' / 'static' / 'icons'


class BrandingConfigIdentityTests(SimpleTestCase):
    def test_house_is_for_the_unrenamed_product_without_a_logo(self) -> None:
        self.assertTrue(DEFAULT.uses_default_mark)

    def test_an_uploaded_logo_replaces_the_house(self) -> None:
        self.assertFalse(WITH_LOGO.uses_default_mark)

    def test_a_renamed_brand_never_gets_the_house(self) -> None:
        self.assertFalse(RENAMED.uses_default_mark)
        self.assertFalse(RENAMED_WITH_LOGO.uses_default_mark)

    def test_product_name_is_split_into_two_weights(self) -> None:
        self.assertEqual((DEFAULT.name_lead, DEFAULT.name_tail), ('ifin', 'mail'))
        self.assertEqual(DEFAULT.name_lead + DEFAULT.name_tail, DEFAULT.name)

    def test_any_other_name_is_not_split(self) -> None:
        self.assertEqual((RENAMED.name_lead, RENAMED.name_tail), ('Acme Mail', ''))


class EmailLogoTests(SimpleTestCase):
    def _context(self, brand: BrandingConfig) -> dict[str, object]:
        with override_settings(BRAND_CONFIG=brand):
            return email_brand_context(lambda path: f'https://mail.example.test{path}')

    def test_product_emails_carry_the_png_lockup(self) -> None:
        url = str(self._context(DEFAULT)['brand_logo_url'])
        self.assertTrue(url.startswith('https://mail.example.test/'))
        self.assertTrue(url.endswith('icons/lockup-email.png'))

    def test_an_uploaded_logo_wins_in_emails(self) -> None:
        url = self._context(WITH_LOGO)['brand_logo_url']
        self.assertEqual(url, f'https://mail.example.test{LOGO}')

    def test_a_renamed_brand_has_no_logo_in_emails(self) -> None:
        self.assertEqual(self._context(RENAMED)['brand_logo_url'], '')


class PageIdentityTests(TestCase):
    def test_sign_in_card_shows_the_lockup_for_the_product(self) -> None:
        with override_settings(BRAND_CONFIG=DEFAULT):
            html = self.client.get(reverse('accounts:login')).content.decode()
        self.assertIn('ifinmail-house', html)
        self.assertIn('ifinmail-login-card__brand--lockup', html)
        self.assertIn(
            '<span class="ifinmail-brand-name">ifin'
            '<span class="ifinmail-brand-name__tail">mail</span></span>',
            html,
        )

    def test_sign_in_card_has_no_house_for_a_renamed_brand(self) -> None:
        with override_settings(BRAND_CONFIG=RENAMED):
            html = self.client.get(reverse('accounts:login')).content.decode()
        self.assertNotIn('ifinmail-house', html)
        self.assertIn('ifinmail-login-card__brand--name', html)

    def test_sign_in_card_prefers_an_uploaded_logo(self) -> None:
        with override_settings(BRAND_CONFIG=WITH_LOGO):
            html = self.client.get(reverse('accounts:login')).content.decode()
        self.assertIn(f'src="{LOGO}"', html)
        self.assertNotIn('ifinmail-house', html)
        self.assertNotIn('ifinmail-login-card__brand--lockup', html)

    def test_public_site_header_and_footer_show_the_house(self) -> None:
        with override_settings(BRAND_CONFIG=DEFAULT):
            html = self.client.get(reverse('landing')).content.decode()
        self.assertEqual(html.count('class="ifinmail-house ifinmail-site-brand__logo"'), 2)

    def test_public_site_has_no_house_for_a_renamed_brand(self) -> None:
        with override_settings(BRAND_CONFIG=RENAMED):
            html = self.client.get(reverse('landing')).content.decode()
        self.assertNotIn('ifinmail-house', html)

    def test_default_icons_are_linked_in_the_head(self) -> None:
        with override_settings(BRAND_CONFIG=DEFAULT):
            html = self.client.get(reverse('landing')).content.decode()
        for needle in ('icons/favicon.ico', 'icons/favicon.svg', 'icons/apple-touch-icon.png'):
            with self.subTest(icon=needle):
                self.assertIn(needle, html)

    def test_an_uploaded_favicon_replaces_every_default_icon(self) -> None:
        brand = BrandingConfig(favicon_url='/media/branding/favicon.ico')
        with override_settings(BRAND_CONFIG=brand):
            html = self.client.get(reverse('landing')).content.decode()
        self.assertEqual(html.count('/media/branding/favicon.ico'), 2)
        self.assertNotIn('icons/favicon.svg', html)
        self.assertNotIn('icons/apple-touch-icon.png', html)

    def test_manifest_lists_raster_maskable_and_vector_icons(self) -> None:
        with override_settings(BRAND_CONFIG=DEFAULT):
            icons = self.client.get(reverse('manifest')).json()['icons']
        by_purpose = {(i['type'], i['purpose']) for i in icons}
        self.assertIn(('image/png', 'any'), by_purpose)
        self.assertIn(('image/png', 'maskable'), by_purpose)
        self.assertIn(('image/svg+xml', 'any'), by_purpose)
        sizes = {i['sizes'] for i in icons if i['type'] == 'image/png'}
        self.assertEqual(sizes, {'192x192', '512x512'})


class ConsoleIdentityTests(MailTablesTestCase):
    def _login_console(self) -> None:
        admin = MailUser.objects.create_user('root@ifinmail.test', 'Correct-Horse-9', is_staff=True)
        self.client.force_login(admin, backend='django.contrib.auth.backends.ModelBackend')
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def test_sidebar_shows_the_house_and_two_weight_name(self) -> None:
        self._login_console()
        with override_settings(BRAND_CONFIG=DEFAULT):
            html = self.client.get(reverse('accounts:dashboard')).content.decode()
        self.assertIn('class="ifinmail-house ifinmail-admin-brand-icon"', html)
        self.assertIn('ifinmail-brand-name__tail', html)

    def test_sidebar_has_no_house_for_a_renamed_brand(self) -> None:
        self._login_console()
        with override_settings(BRAND_CONFIG=RENAMED):
            html = self.client.get(reverse('accounts:dashboard')).content.decode()
        self.assertNotIn('ifinmail-house', html)
        self.assertNotIn('ifinmail-brand-name__tail', html)


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', f'{path.name} is not a PNG'
    return struct.unpack('>II', data[16:24])  # type: ignore[return-value]


class ShippedIconTests(SimpleTestCase):
    def test_png_icons_have_the_sizes_the_manifest_declares(self) -> None:
        expected = {
            'icon-192.png': (192, 192),
            'icon-512.png': (512, 512),
            'icon-maskable-512.png': (512, 512),
            'apple-touch-icon.png': (180, 180),
            'lockup-email.png': (444, 112),
        }
        for name, size in expected.items():
            with self.subTest(icon=name):
                self.assertEqual(_png_size(ICONS / name), size)

    def test_favicon_ico_holds_16_32_and_48(self) -> None:
        data = (ICONS / 'favicon.ico').read_bytes()
        reserved, kind, count = struct.unpack('<HHH', data[:6])
        self.assertEqual((reserved, kind), (0, 1))
        sizes = sorted(data[6 + 16 * i] for i in range(count))
        self.assertEqual(sizes, [16, 32, 48])

    def test_svg_icons_are_well_formed(self) -> None:
        for path in sorted(ICONS.glob('*.svg')):
            with self.subTest(icon=path.name):
                root = ET.fromstring(path.read_text(encoding='utf-8'))
                self.assertTrue(root.tag.endswith('svg'))
                self.assertIn('viewBox', root.attrib)

    def test_wordmarks_are_outlined_so_they_need_no_font(self) -> None:
        for name in ('wordmark-light', 'wordmark-dark', 'lockup-light', 'lockup-dark'):
            with self.subTest(icon=name):
                svg = (ICONS / f'{name}.svg').read_text(encoding='utf-8')
                self.assertNotIn('<text', svg)
                self.assertNotIn('font-family', svg)

    def test_glyph_only_mark_takes_the_ink_of_its_surroundings(self) -> None:
        svg = (ICONS / 'mark-glyph.svg').read_text(encoding='utf-8')
        self.assertIn('currentColor', svg)
        self.assertNotIn('#1a56db', svg)

    def test_the_inline_house_and_the_file_draw_the_same_shape(self) -> None:
        # The inline partial writes the two strokes in shorthand; the file in absolute commands.
        # Both must carry the same coordinates, or the page and the favicon would drift apart.
        inline = (
            Path(settings.BASE_DIR) / 'frontend/templates/includes/brand_house.html'
        ).read_text(encoding='utf-8')
        for fragment in ('M44 86 96 44l52 42v62H44z', 'm52 98 44 32 44-32'):
            self.assertIn(fragment, inline)
        file_svg = (ICONS / 'mark.svg').read_text(encoding='utf-8')
        for fragment in ('M44 86 L96 44 L148 86 V148 H44 Z', 'M52 98 L96 130 L140 98'):
            self.assertIn(fragment, file_svg)


class ShippedFaviconOverrideTests(TestCase):
    """branding_overrides.json ships ``favicon_url`` = the default .ico; that is not an upload."""

    BRAND = BrandingConfig(favicon_url='/static/icons/favicon.ico')

    def test_head_still_gets_the_full_default_icon_set(self) -> None:
        with override_settings(BRAND_CONFIG=self.BRAND):
            html = self.client.get(reverse('landing')).content.decode()
        self.assertIn('icons/favicon.svg', html)
        self.assertIn('icons/apple-touch-icon.png', html)

    def test_manifest_still_lists_the_full_icon_set(self) -> None:
        with override_settings(BRAND_CONFIG=self.BRAND):
            icons = self.client.get(reverse('manifest')).json()['icons']
        self.assertGreaterEqual(len(icons), 3)
