"""The Oceanic theme: Smooth's shapes in a light sea-blue palette, legible by measurement."""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
CSS = ROOT / 'frontend' / 'static' / 'css'


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r'(--ifinmail-[\w-]+):\s*(#[0-9A-Fa-f]{6})\s*;', block))


def _luminance(colour: str) -> float:
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class OceanicThemeTests(SimpleTestCase):
    def setUp(self) -> None:
        css = (CSS / 'ifinmail-variables.css').read_text()
        match = re.search(r'\nhtml\[data-scheme="oceanic"\]\s*\{(.*?)\n\}', css, re.S)
        assert match, 'oceanic block missing'
        self.oceanic = match.group(1)
        self.root = _tokens(re.search(r':root\s*\{(.*?)\n\}', css, re.S).group(1))  # type: ignore[union-attr]
        self.tokens = {**self.root, **_tokens(self.oceanic)}

    def test_it_is_a_light_scheme(self) -> None:
        self.assertNotIn('color-scheme: dark', self.oceanic)
        self.assertGreater(_luminance(self.tokens['--ifinmail-color-surface-1']), 0.8)

    def test_text_and_accent_stay_legible_on_every_surface(self) -> None:
        t = self.tokens
        surfaces = ('--ifinmail-color-surface-1', '--ifinmail-color-surface-2', '--ifinmail-surface-container-lowest')
        for surface in surfaces:
            for name in ('--ifinmail-color-text-primary', '--ifinmail-color-text-secondary', '--ifinmail-color-text-muted'):
                self.assertGreaterEqual(_ratio(t[name], t[surface]), 4.5, f'{name} on {surface}')
            self.assertGreaterEqual(_ratio(t['--ifinmail-color-primary'], t[surface]), 4.5, surface)

    def test_primary_buttons_and_selected_items_are_legible(self) -> None:
        t = self.tokens
        self.assertGreaterEqual(_ratio(t['--ifinmail-on-primary'], t['--ifinmail-color-primary']), 4.5)
        self.assertGreaterEqual(_ratio(t['--ifinmail-on-primary'], t['--ifinmail-color-primary-hover']), 4.5)
        self.assertGreaterEqual(_ratio(t['--ifinmail-color-primary'], t['--ifinmail-color-primary-tint']), 4.5)
        self.assertGreaterEqual(_ratio(t['--ifinmail-sidebar-active-color'], t['--ifinmail-sidebar-active-bg']), 4.5)
        self.assertGreaterEqual(_ratio(t['--ifinmail-sidebar-text'], t['--ifinmail-sidebar-hover-bg']), 4.5)
        self.assertGreaterEqual(_ratio(t['--ifinmail-sidebar-text-muted'], t['--ifinmail-color-surface-1']), 4.5)

    def test_status_colours_are_not_replaced(self) -> None:
        """Success, warning and danger keep their meaning: green, amber, red."""
        for name in ('success', 'warning', 'danger'):
            self.assertNotIn(f'--ifinmail-color-{name}', self.oceanic)

    def test_the_brand_band_carries_white_text(self) -> None:
        t = self.tokens
        self.assertGreaterEqual(_ratio(t['--ifinmail-on-band'], t['--ifinmail-band-bg']), 7)

    def test_borders_are_visible_but_soft(self) -> None:
        t = self.tokens
        ratio = _ratio(t['--ifinmail-color-border'], t['--ifinmail-surface-container-lowest'])
        self.assertGreater(ratio, 1.2)
        self.assertLess(ratio, 3)

    def test_the_picker_and_the_bootstrap_know_it(self) -> None:
        init = (ROOT / 'frontend' / 'static' / 'js' / 'ifinmail-theme-init.js').read_text()
        self.assertIn("'oceanic'", init)
        # Only "auto" looks at the operating system: oceanic never goes dark.
        resolve = re.search(r'function resolve\(choice\) \{(.*?)\n    \}', init, re.S)
        assert resolve is not None
        self.assertNotIn('oceanic', resolve.group(1))
        css = (CSS / 'ifinmail-redesign.css').read_text()
        self.assertIn('.ifinmail-theme-card__preview--oceanic', css)
        self.assertIn('--ifinmail-preview-oceanic-bg', (CSS / 'ifinmail-variables.css').read_text())
