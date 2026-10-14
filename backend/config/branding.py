"""
Branding configuration for self-hosted deployments.
All values read from environment variables and JSON overrides.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass

# Defaults mirror the design system (see DESIGN.md): primary blue, brand navy, success green.
DEFAULT_PRIMARY = '#1a56db'
DEFAULT_SECONDARY = '#0f2b5b'
DEFAULT_ACCENT = '#059669'
# The product name shown wherever no brand name (and no logo) is configured. Templates only ever
# read ``brand.name``, which falls back to this; nothing else spells the default out.
DEFAULT_BRAND_NAME = 'ifinmail'
# The product wordmark is set in two weights, ``ifin`` bold and ``mail`` regular (DESIGN.md → Logo).
DEFAULT_NAME_LEAD = 'ifin'
DEFAULT_NAME_TAIL = 'mail'
# Shipped with the static files: the wordmark lockup PNG that system emails show when the product
# has no logo of its own (mail clients do not render SVG).
DEFAULT_EMAIL_LOGO = 'icons/lockup-email.png'


def branding_overrides_path(
    base_dir: str | os.PathLike[str] | None = None,
) -> str | None:
    """Return the one shared overrides file path (branding + spam settings).

    Precedence: ``BRANDING_OVERRIDES_PATH`` → ``<base_dir>/branding_overrides.json``
    → ``<APP_DIR>/branding_overrides.json``.

    Settings modules must pass ``BASE_DIR`` explicitly: ``django.conf.settings`` is
    not usable while the settings module itself is being imported, and the old
    implicit ``/app`` fallback then resolved to a stray ``C:\\app`` directory on
    Windows instead of the project file.
    """
    env_path = os.environ.get('BRANDING_OVERRIDES_PATH')
    if env_path:
        return env_path
    resolved: str | None = None
    if base_dir is not None:
        resolved = os.fspath(base_dir)
    else:
        try:
            from django.conf import settings as django_settings

            if django_settings.configured:
                resolved = os.fspath(getattr(django_settings, 'BASE_DIR', '') or '')
        except Exception:  # settings unusable here — fall through to APP_DIR
            resolved = None
    if resolved:
        return os.path.join(resolved, 'branding_overrides.json')
    app_dir = os.environ.get('APP_DIR')
    return os.path.join(app_dir, 'branding_overrides.json') if app_dir else None


def _media_root(base_dir: str | os.PathLike[str] | None) -> str | None:
    """Where uploaded branding files live (``MEDIA_ROOT`` or ``<base_dir>/media``)."""
    env_root = os.environ.get('MEDIA_ROOT')
    if env_root:
        return env_root
    if base_dir is None:
        try:
            from django.conf import settings as django_settings

            if django_settings.configured:
                return os.fspath(getattr(django_settings, 'MEDIA_ROOT', '') or '') or None
        except Exception:
            return None
        return None
    return os.path.join(os.fspath(base_dir), 'media')


def _existing_upload(url: str, base_dir: str | os.PathLike[str] | None) -> str:
    """``url`` unless it names an uploaded file (under MEDIA_URL) that is not there.

    A logo that points at a missing upload (a fresh install, a lost media volume, an overrides
    file copied from another server) would render as a broken image; with no logo the pages
    show the brand name instead.
    """
    media_url = os.environ.get('MEDIA_URL', '/media/')
    if not url or not url.startswith(media_url):
        return url
    root = _media_root(base_dir)
    if not root:
        return url
    relative = url[len(media_url) :].lstrip('/')
    path = os.path.normpath(os.path.join(root, relative))
    if not path.startswith(os.path.normpath(root) + os.sep):
        return ''
    if os.path.isfile(path):
        return url
    return url if _in_media_store(relative) else ''


def _in_media_store(key: str) -> bool:
    """True when media lives in an external store that holds ``key`` (never during start-up)."""
    try:
        from django.apps import apps

        if not apps.ready:
            return False
        from backend.apps.core.storage import config

        if config.external('media') is None:
            return False
        return config.store_for('media').exists(key)
    except Exception:  # an unreachable store must not take the console's pages down
        return False


@dataclass(frozen=True)
class BrandingConfig:
    name: str = DEFAULT_BRAND_NAME
    tagline: str = 'mail infrastructure'
    color: str = DEFAULT_PRIMARY  # primary accent (hex, no spaces)
    logo_url: str = ''  # uploaded logo; empty -> see uses_default_mark
    favicon_url: str = ''  # if empty, use default icon
    secondary_color: str = DEFAULT_SECONDARY
    accent_color: str = DEFAULT_ACCENT
    heading_font: str = 'Inter'
    body_font: str = 'Inter'

    @classmethod
    def from_env(cls, base_dir: str | os.PathLike[str] | None = None) -> BrandingConfig:
        # Load overrides from JSON file if it exists (project-local prioritized)
        overrides = {}
        try:
            path = branding_overrides_path(base_dir)
            if path and os.path.isfile(path):
                with open(path, encoding='utf-8') as f:
                    overrides = json.load(f)
        except Exception:
            pass

        def _brand(key: str, env: str, default: str) -> str:
            return (overrides.get(key) or os.environ.get(env, default)).strip() or default

        raw_color = _brand('primary_color', 'BRAND_COLOR', DEFAULT_PRIMARY)
        raw_secondary = _brand('secondary_color', 'BRAND_SECONDARY_COLOR', DEFAULT_SECONDARY)
        raw_accent = _brand('accent_color', 'BRAND_ACCENT_COLOR', DEFAULT_ACCENT)
        heading_font = _brand('heading_font', 'BRAND_HEADING_FONT', 'Inter')
        body_font = _brand('body_font', 'BRAND_BODY_FONT', 'Inter')

        return cls(
            name=_brand('name', 'BRAND_NAME', DEFAULT_BRAND_NAME),
            tagline=_brand('tagline', 'BRAND_TAGLINE', 'mail infrastructure'),
            color=cls._sanitize_hex_color(raw_color),
            logo_url=_existing_upload(_brand('logo_url', 'BRAND_LOGO_URL', ''), base_dir),
            favicon_url=_brand('favicon_url', 'BRAND_FAVICON_URL', ''),
            secondary_color=cls._sanitize_hex_color(raw_secondary),
            accent_color=cls._sanitize_hex_color(raw_accent),
            heading_font=heading_font,
            body_font=body_font,
        )

    @property
    def is_custom(self) -> bool:
        return self.name != DEFAULT_BRAND_NAME

    @property
    def uses_default_mark(self) -> bool:
        """True when pages draw the product's own house mark: no logo uploaded and the name is
        still the product's. A renamed brand without a logo shows its name only — the system
        never puts the ifinmail mark on someone else's brand."""
        return not self.logo_url and not self.is_custom

    @property
    def name_lead(self) -> str:
        """The bold part of the brand name: ``ifin`` of the product name, else the whole name."""
        return DEFAULT_NAME_LEAD if self.name == DEFAULT_BRAND_NAME else self.name

    @property
    def name_tail(self) -> str:
        """The light part of the brand name (``mail``); empty for any other name."""
        return DEFAULT_NAME_TAIL if self.name == DEFAULT_BRAND_NAME else ''

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
            imports.append(
                f"@import url('https://fonts.googleapis.com/css2?family={font_url}:wght@400;500;600;700&display=swap');"
            )

        # Primary color overrides
        safe_color = self._sanitize_hex_color(self.color)
        if safe_color != DEFAULT_PRIMARY:
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
        if safe_accent != DEFAULT_ACCENT:
            rgba_success_tint = self._hex_to_rgba(safe_accent, 0.1)
            styles.append(
                f'--ifinmail-success: {safe_accent} !important;\n'
                f'  --ifinmail-color-success: {safe_accent} !important;\n'
                f'  --ifinmail-color-success-tint: {rgba_success_tint} !important;\n'
                f'  --ifinmail-success-container: {rgba_success_tint} !important;'
            )

        # Font family overrides
        _system_stack = (
            'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", '
            'Helvetica, Arial, sans-serif !important;'
        )
        font_parts = []
        if self.body_font and self.body_font != 'Inter':
            if self.body_font == 'system-ui':
                font_parts.append(f'--ifinmail-font-ui: {_system_stack}')
            else:
                font_parts.append(
                    f'--ifinmail-font-ui: "{self.body_font}", "Inter", '
                    f'-apple-system, BlinkMacSystemFont, "Segoe UI", '
                    f'Helvetica, Arial, sans-serif !important;'
                )

        if font_parts:
            styles.append('\n  '.join(font_parts))

        if not styles and not imports:
            return ''

        import_str = '\n'.join(imports) + '\n' if imports else ''
        inner_style = '\n  '.join(styles)

        extra_rules = ''
        if self.heading_font and self.heading_font != 'Inter' and self.heading_font != 'system-ui':
            extra_rules = (
                f'\nh1, h2, h3, h4, h5, h6, .ifinmail-page-title, .ifinmail-panel-title {{\n'
                f'  font-family: "{self.heading_font}", var(--ifinmail-font-ui) !important;\n'
                f'}}\n'
            )

        return f'<style>\n{import_str}:root {{\n  {inner_style}\n}}\n{extra_rules}</style>'

    @staticmethod
    def _sanitize_hex_color(color: str) -> str:
        """Sanitize a hex color value to prevent XSS in inline styles."""
        h = color.lstrip('#').strip()
        if not h or len(h) not in (3, 6) or not all(c in '0123456789abcdefABCDEF' for c in h):
            return DEFAULT_PRIMARY
        return f'#{h.lower()}'

    @staticmethod
    def _hex_to_rgba(hex_color: str, alpha: float) -> str:
        h = hex_color.lstrip('#')
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f'rgba({r},{g},{b},{alpha})'


def brand_name() -> str:
    """The configured product name (``DEFAULT_BRAND_NAME`` when none is set), for Python code."""
    from django.conf import settings

    brand = getattr(settings, 'BRAND_CONFIG', None)
    return (getattr(brand, 'name', '') or DEFAULT_BRAND_NAME).strip()


def brand_context(request: object) -> dict[str, object]:
    """Context processor — injects brand into every template context."""
    from django.conf import settings

    brand = getattr(settings, 'BRAND_CONFIG', None)
    if brand is None:
        brand = BrandingConfig()
    return {'brand': brand}


def email_brand_context(
    build_absolute_uri: Callable[[str], str] | None = None,
) -> dict[str, object]:
    """Template context for system emails.

    Emails render outside the request cycle, so the brand is not in their
    context automatically; callers pass this dict to ``render_to_string`` or
    Django's ``extra_email_context``. ``brand_logo_url`` is made absolute so
    mail clients can fetch an uploaded logo.
    """
    from django.conf import settings

    brand = getattr(settings, 'BRAND_CONFIG', None)
    if brand is None:
        brand = BrandingConfig()
    logo = brand.logo_url
    if not logo and brand.uses_default_mark:
        from django.templatetags.static import static

        logo = static(DEFAULT_EMAIL_LOGO)
    if logo and not logo.startswith(('http://', 'https://')) and build_absolute_uri:
        logo = build_absolute_uri(logo)
    return {'brand': brand, 'brand_logo_url': logo}
