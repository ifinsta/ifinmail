"""The Smooth theme: the default look. Light only, soft edges, scoped so no other theme changes."""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

CSS = Path(settings.BASE_DIR) / 'frontend' / 'static' / 'css'
JS = Path(settings.BASE_DIR) / 'frontend' / 'static' / 'js'


def rules(css: str) -> list[tuple[str, str]]:
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r'([^{}@]+)\{([^{}]*)\}', css)]


class SmoothStylesheetTests(SimpleTestCase):
    def test_every_rule_is_scoped_to_the_smooth_scheme(self) -> None:
        """Otherwise Light, Dark and High contrast would change with it. Oceanic shares the look."""
        unscoped = []
        scope = 'html:is([data-scheme="smooth"], [data-scheme="oceanic"])'
        for selector, _ in rules((CSS / 'ifinmail-smooth.css').read_text()):
            for part in selector.replace(scope, 'SCOPE').split(','):
                if not part.strip().startswith('SCOPE'):
                    unscoped.append(part.strip())
        self.assertEqual(unscoped, [])

    def test_no_gradients_literal_colours_or_important_glow(self) -> None:
        css = re.sub(r'/\*.*?\*/', '', (CSS / 'ifinmail-smooth.css').read_text(), flags=re.S)
        self.assertNotRegex(css, r'(linear|radial|conic)-gradient')
        self.assertNotRegex(css, r'#[0-9a-fA-F]{3,8}\b', 'use tokens, not literal colours')
        self.assertNotRegex(css, r'rgba?\(\s*\d', 'colours come from tokens (alpha of a token is ok)')

    def test_no_dark_scheme_in_the_smooth_look(self) -> None:
        css = (CSS / 'ifinmail-smooth.css').read_text()
        self.assertNotIn('prefers-color-scheme', css)
        block = re.search(r'html\[data-scheme="smooth"\],\s*html\[data-scheme="oceanic"\]\s*\{(.*?)\n\}', (CSS / 'ifinmail-variables.css').read_text(), re.S)
        assert block is not None
        self.assertIn('color-scheme: light', block.group(1))

    def test_the_brand_colour_is_left_to_the_organisation(self) -> None:
        block = re.search(r'html\[data-scheme="smooth"\],\s*html\[data-scheme="oceanic"\]\s*\{(.*?)\n\}', (CSS / 'ifinmail-variables.css').read_text(), re.S)
        assert block is not None
        for token in ('--ifinmail-color-primary:', '--ifinmail-color-brand:', '--ifinmail-on-primary:'):
            self.assertNotIn(token, block.group(1))

    def test_radii_are_softer_than_the_standard_look(self) -> None:
        css = (CSS / 'ifinmail-variables.css').read_text()
        root = re.search(r':root\s*\{(.*?)\n\}', css, re.S).group(1)  # type: ignore[union-attr]
        smooth = re.search(r'html\[data-scheme="smooth"\],\s*html\[data-scheme="oceanic"\]\s*\{(.*?)\n\}', css, re.S).group(1)  # type: ignore[union-attr]

        def rem(block: str, name: str) -> float:
            return float(re.search(rf'--ifinmail-{name}:\s*([\d.]+)rem', block).group(1))  # type: ignore[union-attr]

        for name in ('radius', 'radius-lg', 'radius-dialog'):
            self.assertGreater(rem(smooth, name), rem(root, name), name)

    def test_keyboard_focus_stays_visible(self) -> None:
        css = (CSS / 'ifinmail-smooth.css').read_text()
        self.assertNotRegex(css, r'outline:\s*(none|0)\b')


class ThemeBootstrapTests(SimpleTestCase):
    def test_smooth_is_the_default_and_never_resolves_to_dark(self) -> None:
        source = (JS / 'ifinmail-theme-init.js').read_text()
        self.assertIn("CHOICES = ['smooth',", source)
        self.assertIn(": configured;", source)
        self.assertIn("'smooth' : configured", source)
        # Only "auto" looks at the operating system.
        resolve = re.search(r'function resolve\(choice\) \{(.*?)\n    \}', source, re.S)
        assert resolve is not None
        self.assertIn("choice === 'auto'", resolve.group(1))
        self.assertNotIn('smooth', resolve.group(1))

    def test_the_picker_offers_smooth_first(self) -> None:
        html = (Path(settings.BASE_DIR) / 'frontend' / 'templates' / 'admin' / 'settings_appearance.html').read_text()
        values = re.findall(r'name="ifinmail-theme" value="(\w+)"', html)
        self.assertEqual(values, ['smooth', 'oceanic', 'light', 'dark', 'auto', 'contrast'])


class PhoneTablesTests(SimpleTestCase):
    def test_tables_become_labelled_cards_on_a_phone(self) -> None:
        script = (JS / 'ifinmail-tables.js').read_text()
        self.assertIn("'data-label'", script)
        self.assertIn("classList.add('is-stacked')", script)
        self.assertIn('MutationObserver', script)  # tables filled in by other scripts
        base = (Path(settings.BASE_DIR) / 'frontend' / 'templates' / 'base.html').read_text()
        self.assertIn("js/ifinmail-tables.js", base)
        css = (CSS / 'ifinmail-smooth.css').read_text()
        self.assertIn('.ifinmail-admin-table.is-stacked td::before', css)
        self.assertIn('content: attr(data-label)', css)
        self.assertIn('td:empty::after', css)  # an empty value must not let labels overlap

    def test_an_unlabelled_table_scrolls_in_its_card_and_is_never_clipped(self) -> None:
        css = (CSS / 'ifinmail-smooth.css').read_text()
        self.assertIn('.ifinmail-admin-table:not(.is-stacked)', css)
        panel = [
            body
            for sel, body in rules(css)
            if sel.strip() == 'html:is([data-scheme="smooth"], [data-scheme="oceanic"]) .ifinmail-table-panel'
        ]
        self.assertTrue(any('overflow-x: auto' in b for b in panel))
        self.assertFalse(any('overflow: hidden' in b for b in panel))
