"""Layout rules that broke on phones once and must not break again.

These read the stylesheets and templates as text (there is no browser in the test run), so they
guard the specific mistakes found in the mobile review: an element that is also
``.ifinmail-site-wrap`` losing its side gutter to a ``padding: x 0`` shorthand, and the header
running past the screen on a tablet.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

STATIC = Path(settings.BASE_DIR) / 'frontend' / 'static' / 'css'
TEMPLATES = Path(settings.BASE_DIR) / 'frontend' / 'templates' / 'site'


def rule_blocks(css: str) -> list[tuple[str, str]]:
    """``(selector list, declarations)`` for every simple rule, media queries flattened."""
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', css)]


class SiteWrapGutterTests(SimpleTestCase):
    def wrap_companions(self) -> set[str]:
        found: set[str] = set()
        for path in TEMPLATES.glob('*.html'):
            for match in re.finditer(
                r'class="([^"]*\bifinmail-site-wrap\b[^"]*)"', path.read_text()
            ):
                found |= {c for c in match.group(1).split() if c != 'ifinmail-site-wrap'}
        return found

    def test_elements_that_are_also_the_page_wrap_keep_their_side_padding(self) -> None:
        companions = self.wrap_companions()
        self.assertIn('ifinmail-site-docs', companions)  # the case that regressed
        bad: list[str] = []
        for selector, body in rule_blocks((STATIC / 'ifinmail-site.css').read_text()):
            names = set(re.findall(r'\.([A-Za-z0-9_-]+)', selector))
            if not names & companions or len(selector.split(',')) > 1 and ' ' in selector:
                continue
            if ' ' in selector.strip():  # a descendant rule styles something inside, not the wrap
                continue
            for decl in re.findall(r'(?<![-\w])padding\s*:\s*([^;]+);', body):
                parts = decl.split()
                horizontal = parts[1] if len(parts) >= 2 else parts[0]
                if re.fullmatch(r'0(px|rem)?', horizontal):
                    bad.append(f'{selector} {{ padding: {decl.strip()} }}')
            if re.search(r'padding-(left|right|inline)[^:]*:\s*0\b', body):
                bad.append(f'{selector} zeroes a side padding')
        self.assertEqual(
            bad, [], 'these elements are .ifinmail-site-wrap too: use padding-top/bottom instead'
        )


class HeaderBreakpointTests(SimpleTestCase):
    def test_the_menu_button_takes_over_before_the_links_overflow(self) -> None:
        css = (STATIC / 'ifinmail-site.css').read_text()
        widths = [
            int(m.group(1))
            for m in re.finditer(r'@media \(max-width:\s*(\d+)px\)\s*\{\s*\.ifinmail-site-nav', css)
        ]
        self.assertTrue(widths, 'nav is never collapsed')
        # Five links and two buttons need about 860px; collapse must start at or above that.
        self.assertGreaterEqual(max(widths), 859)


class AuthPageHeightTests(SimpleTestCase):
    def test_phone_auth_pages_are_one_viewport_and_the_card_only_as_tall_as_its_content(
        self,
    ) -> None:
        css = (STATIC / 'ifinmail-redesign.css').read_text()
        marker = 'Phone: auth, registration, setup and error pages fit the viewport'
        self.assertIn(marker, css)
        block = css[css.index(marker) :]
        card_rule = r'ifinmail-login-card,\s*html\.ifinmail-shell \.ifinmail-reg-card\s*\{[^}]*'
        self.assertRegex(block, card_rule + r'min-height:\s*0\s*!important')
        self.assertIn('min-height: 100dvh !important', block)

    def test_phone_auth_card_headers_are_centred_together(self) -> None:
        css = (STATIC / 'ifinmail-redesign.css').read_text()
        block = css[
            css.index('Phone: auth, registration, setup and error pages fit the viewport') :
        ]
        for selector in (
            '.ifinmail-login-card__brand',
            '.ifinmail-login-card__title',
            '.ifinmail-login-card__subtitle',
            '.ifinmail-reg-card__title',
            '.ifinmail-reg-card__subtitle',
        ):
            self.assertIn(f'html.ifinmail-shell {selector}', block)
        self.assertIn('text-align: center !important', block)
        self.assertNotIn('text-align: left !important', block)


class ViewportUnitTests(SimpleTestCase):
    def test_every_full_height_rule_has_a_dvh_partner(self) -> None:
        """``100vh`` is the viewport with the browser's bars hidden: on a phone it is taller than
        what is visible, so a short page scrolls by the address-bar height. Each ``100vh`` height
        must be followed, in the same rule, by the ``100dvh`` that tracks the visible area."""
        missing: list[str] = []
        for path in sorted(STATIC.glob('*.css')):
            css = re.sub(r'/\*.*?\*/', '', path.read_text(), flags=re.S)
            for selector, body in rule_blocks(css):
                declarations = [d.strip() for d in body.split(';') if d.strip()]
                for index, decl in enumerate(declarations):
                    match = re.fullmatch(
                        r'((?:min-|max-)?height)\s*:\s*100vh(\s*!important)?', decl
                    )
                    if not match:
                        continue
                    partner = f'{match.group(1)}: 100dvh{match.group(2) or ""}'
                    following = [d.replace('  ', ' ') for d in declarations[index + 1 :]]
                    if partner not in following:
                        missing.append(
                            f'{path.name}: {selector.splitlines()[-1].strip()} {{ {decl} }}'
                        )
        self.assertEqual(missing, [], 'add the 100dvh partner right after each 100vh height')
