"""Branding and identity view."""

import json
import logging
import os

from django.conf import settings as django_settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.storage.contract import StorageError
from backend.apps.core.storage.services import StorageService
from backend.config.branding import (
    DEFAULT_ACCENT,
    DEFAULT_PRIMARY,
    DEFAULT_SECONDARY,
    branding_overrides_path,
)

from ..types.permissions import PermissionCode
from .auth import require_perm

logger = logging.getLogger('backend')


def _get_overrides_file_path() -> str:
    base_dir = getattr(django_settings, 'BASE_DIR', None)
    return branding_overrides_path(base_dir) or os.path.join(
        base_dir or '.', 'branding_overrides.json'
    )


_BRANDING_OVERRIDES_FILE = _get_overrides_file_path()

# Available web-safe fonts for the selector
_WEB_FONTS = [
    ('Inter', 'Inter (System Default)'),
    ('system-ui', 'System UI'),
    ('Helvetica Neue', 'Helvetica Neue'),
    ('Arial', 'Arial'),
    ('Georgia', 'Georgia'),
    ('Roboto', 'Roboto'),
    ('Open Sans', 'Open Sans'),
    ('Lato', 'Lato'),
    ('Montserrat', 'Montserrat'),
    ('Source Sans Pro', 'Source Sans Pro'),
    ('Merriweather', 'Merriweather'),
    ('PT Sans', 'PT Sans'),
    ('Noto Sans', 'Noto Sans'),
]


def _store_failed(exc: Exception) -> JsonResponse:
    logger.warning('Branding upload could not be stored: %s', exc)
    return JsonResponse(
        {'status': 'err', 'error': f'The file could not be stored: {exc}'},
        status=502,
        content_type='application/json; charset=utf-8',
    )


def _load_overrides() -> dict:
    """Load branding overrides from JSON file."""
    try:
        if os.path.isfile(_BRANDING_OVERRIDES_FILE):
            with open(_BRANDING_OVERRIDES_FILE) as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning('Failed to read branding overrides: %s', e)
    return {}


def _save_overrides(data: dict) -> None:
    """Persist branding overrides to JSON file."""
    os.makedirs(os.path.dirname(_BRANDING_OVERRIDES_FILE) or '.', exist_ok=True)
    with open(_BRANDING_OVERRIDES_FILE, 'w') as f:
        json.dump(data, f, indent=2)


@login_required
@require_perm(PermissionCode.SYSTEM_MANAGE)
def branding_identity(request: HttpRequest) -> HttpResponse:
    """Branding and identity settings screen."""
    overrides = _load_overrides()
    primary_color = overrides.get('primary_color') or os.environ.get('BRAND_COLOR', DEFAULT_PRIMARY)
    secondary_color = overrides.get('secondary_color') or os.environ.get(
        'BRAND_SECONDARY_COLOR', DEFAULT_SECONDARY
    )
    accent_color = overrides.get('accent_color') or os.environ.get(
        'BRAND_ACCENT_COLOR', DEFAULT_ACCENT
    )
    heading_font = overrides.get('heading_font', 'Inter')
    body_font = overrides.get('body_font', 'Inter')
    favicon_url = overrides.get('favicon_url', '')

    # Current logo filename derived from brand config or environment
    brand = getattr(django_settings, 'BRAND_CONFIG', None)
    logo_url = overrides.get('logo_url') or (brand.logo_url if brand else '') or ''
    if not logo_url:
        logo_url = os.environ.get('BRAND_LOGO_URL', '')
    current_logo = logo_url or os.environ.get('BRAND_LOGO_FILENAME', 'header_logo_v2.png')
    logo_filename = current_logo.rsplit('/', 1)[-1] if current_logo else 'header_logo_v2.png'

    return render(
        request,
        'admin/branding_identity.html',
        {
            'active_section': 'general',
            'header_search_placeholder': 'Search settings...',
            'show_settings_icon': True,
            'primary_color': primary_color,
            'secondary_color': secondary_color,
            'accent_color': accent_color,
            'current_logo_filename': logo_filename,
            'current_logo_url': logo_url,
            'heading_font': heading_font,
            'body_font': body_font,
            'favicon_url': favicon_url,
            'web_fonts': _WEB_FONTS,
            'MEDIA_URL': getattr(django_settings, 'MEDIA_URL', '/media/'),
        },
    )


@login_required
@require_perm(PermissionCode.SYSTEM_MANAGE)
@require_POST
def branding_save(request: HttpRequest) -> HttpResponse:
    """Save branding overrides (colors, fonts) and optional favicon upload."""
    overrides = _load_overrides()
    changed = False

    # Color fields
    for field in ('primary_color', 'secondary_color', 'accent_color'):
        val = request.POST.get(field, '').strip()
        if val:
            h = val.lstrip('#').strip()
            if h and len(h) in (3, 6) and all(c in '0123456789abcdefABCDEF' for c in h):
                overrides[field] = f'#{h}'
                changed = True

    # Font fields
    for field in ('heading_font', 'body_font'):
        val = request.POST.get(field, '').strip()
        if val:
            overrides[field] = val
            changed = True

    # Favicon upload
    uploaded = request.FILES.get('favicon')
    if uploaded:
        # Through core.storage: the disk, or the object store the Object storage plugin set up.
        try:
            StorageService.put_asset('branding/favicon.ico', uploaded, content_type='image/x-icon')
        except StorageError as exc:
            return _store_failed(exc)
        overrides['favicon_url'] = (
            f'{getattr(django_settings, "MEDIA_URL", "/media/")}branding/favicon.ico'
        )
        changed = True

    # Logo upload (PNG/SVG/JPG/WebP), stored under media/branding/
    uploaded_logo = request.FILES.get('logo')
    if uploaded_logo:
        ext = os.path.splitext(uploaded_logo.name)[1].lower()
        if ext in {'.png', '.svg', '.jpg', '.jpeg', '.webp'}:
            logo_name = f'logo{ext}'
            try:
                StorageService.put_asset(
                    f'branding/{logo_name}',
                    uploaded_logo,
                    content_type=uploaded_logo.content_type or '',
                )
            except StorageError as exc:
                return _store_failed(exc)
            overrides['logo_url'] = (
                f'{getattr(django_settings, "MEDIA_URL", "/media/")}branding/{logo_name}'
            )
            changed = True

    if changed:
        try:
            _save_overrides(overrides)
            # Dynamic hot-reload of branding config
            from backend.config.branding import BrandingConfig

            django_settings.BRAND_CONFIG = BrandingConfig.from_env()

            AuditService.record(
                action='branding_saved',
                user=request.user.email if request.user.is_authenticated else None,
                detail='Branding overrides updated',
            )
        except OSError as e:
            logger.exception('Failed to save branding overrides: %s', e)
            return JsonResponse(
                {'status': 'err', 'error': str(e)},
                status=500,
                content_type='application/json; charset=utf-8',
            )

    return JsonResponse(
        {'status': 'ok', 'saved': changed},
        content_type='application/json; charset=utf-8',
    )


@login_required
@require_perm(PermissionCode.SYSTEM_MANAGE)
@require_POST
def branding_reset(request: HttpRequest) -> HttpResponse:
    """Reset all branding overrides to system defaults."""
    try:
        if os.path.isfile(_BRANDING_OVERRIDES_FILE):
            os.remove(_BRANDING_OVERRIDES_FILE)
        # Also remove uploaded favicon and logo assets
        for name in ('favicon.ico', 'logo.png', 'logo.svg', 'logo.jpg', 'logo.jpeg', 'logo.webp'):
            StorageService.delete_asset(f'branding/{name}')

        # Dynamic hot-reload of branding config to reset defaults
        from backend.config.branding import BrandingConfig

        django_settings.BRAND_CONFIG = BrandingConfig.from_env()

        AuditService.record(
            action='branding_reset',
            user=request.user.email if request.user.is_authenticated else None,
            detail='Branding overrides cleared',
        )
    except (OSError, StorageError) as e:
        logger.exception('Failed to reset branding: %s', e)
        return JsonResponse(
            {'status': 'err', 'error': str(e)},
            status=500,
            content_type='application/json; charset=utf-8',
        )

    return JsonResponse(
        {'status': 'ok'},
        content_type='application/json; charset=utf-8',
    )
