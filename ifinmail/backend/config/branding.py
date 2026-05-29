"""
Branding configuration for self-hosted deployments.
All values read from environment variables and JSON overrides.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BrandingConfig:
    name: str = 'ifinmail'
    tagline: str = 'mail infrastructure'
    color: str = '#0051d5'  # primary accent (hex, no spaces)
    logo_url: str = ''  # if empty, use inline SVG default
    favicon_url: str = ''  # if empty, use default icon
    secondary_color: str = '#ECEEF0'
    accent_color: str = '#4EDEA3'
    heading_font: str = 'Inter'
    body_font: str = 'Inter'

    @classmethod
    def from_env(cls) -> BrandingConfig:
        # Load overrides from JSON file if it exists (project-local prioritized)
        overrides = {}
        try:
            from django.conf import settings as django_settings
            base_dir = getattr(django_settings, 'BASE_DIR', None)
            paths = []
            if base_dir:
                paths.append(os.path.join(base_dir, 'branding_overrides.json'))
            env_path = os.environ.get('BRANDING_OVERRIDES_PATH')
            if env_path:
                paths.append(env_path)
            paths.append(os.path.join(os.environ.get('APP_DIR', '/app'), 'branding_overrides.json'))
            
            for p in paths:
                if os.path.isfile(p):
                    with open(p, "r", encoding="utf-8") as f:
                        overrides = json.load(f)
                        break
        except Exception:
            pass

        raw_color = overrides.get('primary_color') or os.environ.get('BRAND_COLOR', '#0051d5').strip() or '#0051d5'
        raw_secondary = overrides.get('secondary_color') or os.environ.get('BRAND_SECONDARY_COLOR', '#ECEEF0').strip()
        raw_accent = overrides.get('accent_color') or os.environ.get('BRAND_ACCENT_COLOR', '#4EDEA3').strip()
        heading_font = overrides.get('heading_font') or os.environ.get('BRAND_HEADING_FONT', 'Inter').strip()
        body_font = overrides.get('body_font') or os.environ.get('BRAND_BODY_FONT', 'Inter').strip()

        return cls(
            name=overrides.get('name') or os.environ.get('BRAND_NAME', 'ifinmail').strip() or 'ifinmail',
            tagline=overrides.get('tagline') or os.environ.get('BRAND_TAGLINE', 'mail infrastructure').strip(),
            color=cls._sanitize_hex_color(raw_color),
            logo_url=overrides.get('logo_url') or os.environ.get('BRAND_LOGO_URL', '').strip(),
            favicon_url=overrides.get('favicon_url') or os.environ.get('BRAND_FAVICON_URL', '').strip(),
            secondary_color=cls._sanitize_hex_color(raw_secondary),
            accent_color=cls._sanitize_hex_color(raw_accent),
            heading_font=heading_font,
            body_font=body_font,
        )

    @property
    def is_custom(self) -> bool:
        return self.name != 'ifinmail'

    @property
    def css_overrides(self) -> str:
        """Return a <style> block when brand configurations are customized."""
        styles = []
        imports = []
        
        # Determine fonts to load from Google Fonts
        fonts_to_load = set()
        if self.heading_font and self.heading_font != 'Inter' and self.heading_font != 'system-ui':
            fonts_to_load.add(self.heading_font)
        if self.body_font and self.body_font != 'Inter' and self.body_font != 'system-ui':
            fonts_to_load.add(self.body_font)
            
        for font in fonts_to_load:
            font_url = font.replace(' ', '+')
            imports.append(f"@import url('https://fonts.googleapis.com/css2?family={font_url}:wght@400;500;600;700&display=swap');")

        # Primary color overrides
        safe_color = self._sanitize_hex_color(self.color)
        if safe_color != '#0051d5':
            rgba_focus = self._hex_to_rgba(safe_color, 0.15)
            rgba_hover = self._hex_to_rgba(safe_color, 0.85)
            rgba_tint = self._hex_to_rgba(safe_color, 0.05)
            styles.append(
                f'--ifinmail-color-primary: {safe_color} !important;\n'
                f'  --ifinmail-primary: {safe_color} !important;\n'
                f'  --ifinmail-secondary: {safe_color} !important;\n'
                f'  --ifinmail-color-primary-hover: {rgba_hover} !important;\n'
                f'  --ifinmail-focus-ring-color: {rgba_focus} !important;\n'
                f'  --ifinmail-color-primary-tint: {rgba_tint} !important;\n'
                f'  --ifinmail-color-primary-subtle: {rgba_tint} !important;\n'
                f'  --ifinmail-sidebar-active-color: {safe_color} !important;\n'
                f'  --ifinmail-sidebar-active-bg: {rgba_tint} !important;'
            )
            
        # Accent color overrides
        safe_accent = self._sanitize_hex_color(self.accent_color)
        if safe_accent != '#4edea3':
            rgba_success_tint = self._hex_to_rgba(safe_accent, 0.1)
            styles.append(
                f'--ifinmail-success: {safe_accent} !important;\n'
                f'  --ifinmail-color-success: {safe_accent} !important;\n'
                f'  --ifinmail-color-success-tint: {rgba_success_tint} !important;\n'
                f'  --ifinmail-success-container: {rgba_success_tint} !important;'
            )
            
        # Font family overrides
        font_parts = []
        if self.body_font and self.body_font != 'Inter':
            if self.body_font == 'system-ui':
                font_parts.append('--ifinmail-font-ui: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif !important;')
            else:
                font_parts.append(f'--ifinmail-font-ui: "{self.body_font}", "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif !important;')
        
        if font_parts:
            styles.append('\n  '.join(font_parts))
            
        if not styles and not imports:
            return ''
            
        import_str = '\n'.join(imports) + '\n' if imports else ''
        inner_style = '\n  '.join(styles)
        
        extra_rules = ""
        if self.heading_font and self.heading_font != 'Inter' and self.heading_font != 'system-ui':
            extra_rules = (
                f"\nh1, h2, h3, h4, h5, h6, .ifinmail-page-title, .ifinmail-panel-title {{\n"
                f"  font-family: \"{self.heading_font}\", var(--ifinmail-font-ui) !important;\n"
                f"}}\n"
            )
            
        return (
            f'<style>\n'
            f'{import_str}'
            f':root {{\n'
            f'  {inner_style}\n'
            f'}}\n'
            f'{extra_rules}'
            f'</style>'
        )

    @property
    def logo_svg(self) -> str:
        """Inline SVG logo icon using the brand color."""
        c = self.color
        return (
            f'<svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true"'
            f' style="vertical-align:middle;margin-right:6px;">'
            f'<rect width="32" height="32" rx="6" fill="{c}"/>'
            f'<text x="16" y="21" text-anchor="middle"'
            f' font-family="Inter,-apple-system,BlinkMacSystemFont,sans-serif"'
            f' font-size="17" font-weight="700" fill="white">i</text>'
            f'</svg>'
        )

    @property
    def sidebar_logo_svg(self) -> str:
        """Larger inline SVG for the admin sidebar brand bar."""
        c = self.color
        return (
            f'<svg class="ifinmail-admin-brand-icon" width="32" height="32"'
            f' viewBox="0 0 32 32" aria-hidden="true">'
            f'<rect width="32" height="32" rx="6" fill="{c}"/>'
            f'<text x="16" y="21" text-anchor="middle"'
            f' font-family="Inter,-apple-system,BlinkMacSystemFont,sans-serif"'
            f' font-size="17" font-weight="700" fill="white">i</text>'
            f'</svg>'
        )

    @staticmethod
    def _sanitize_hex_color(color: str) -> str:
        """Sanitize a hex color value to prevent XSS in inline styles."""
        h = color.lstrip('#').strip()
        if not h or len(h) not in (3, 6) or not all(c in '0123456789abcdefABCDEF' for c in h):
            return '#0051d5'
        return f'#{h.lower()}'

    @staticmethod
    def _hex_to_rgba(hex_color: str, alpha: float) -> str:
        h = hex_color.lstrip('#')
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f'rgba({r},{g},{b},{alpha})'


def brand_context(request: object) -> dict[str, object]:
    """Context processor — injects brand into every template context."""
    from django.conf import settings

    brand = getattr(settings, 'BRAND_CONFIG', None)
    if brand is None:
        brand = BrandingConfig()
    return {'brand': brand}
