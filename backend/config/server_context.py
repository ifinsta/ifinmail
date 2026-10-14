"""
Server-level context processor — injects server metadata into every template.
Values read from environment variables with sensible fallbacks.
"""

from __future__ import annotations

import os

from django.conf import settings
from django.http import HttpRequest
from django.urls import reverse

from backend.config import site_url


def _default_theme() -> str:
    """The server's default look; never lets a settings hiccup break a page."""
    try:
        from backend.apps.accounts.services import appearance

        return appearance.default_theme()
    except Exception:
        return 'smooth'


class _PublicPages:
    """``site_pages.terms`` in a template: is that public page served? Read on first use."""

    def __getattr__(self, key: str) -> bool:
        from backend.apps.core.website.services import policy
        from backend.apps.core.website.types import Mode

        if key.startswith('_'):
            raise AttributeError(key)
        return policy.current().mode(key) != Mode.OFF


def server_context(request: HttpRequest) -> dict[str, object]:
    """Context processor — injects server metadata into every template context."""
    version = os.environ.get('APP_VERSION', 'dev')
    # Neither default names a domain that is not this server's. Without SUPPORT_EMAIL the
    # templates link to the documentation's troubleshooting section instead of a mailto:.
    support_email = os.environ.get('SUPPORT_EMAIL', '').strip()
    # Console links to public pages must not lead to a page the Website pages plugin switched off.
    pages = _PublicPages()
    docs_url = os.environ.get('DOCS_URL', '').strip() or (reverse('docs') if pages.docs else '')
    server_status = os.environ.get('SERVER_STATUS', 'Online')
    # Set USE_GOOGLE_FONTS=0 to serve without the Google Fonts CDN (air-gapped
    # installs); the CSS font stack falls back to the system UI fonts.
    use_google_fonts = os.environ.get('USE_GOOGLE_FONTS', '1').lower() not in ('0', 'false', 'no')
    from backend.apps.accounts.services.registration_policy import registration_open

    return {
        'site_origin': site_url.origin(request),
        'site_host': site_url.host(request),
        'registration_open': registration_open,  # callable: only evaluated if a template asks
        'server_version': version,
        'CSS_VERSION': settings.CSS_VERSION,
        'support_email': support_email,
        'docs_url': docs_url,
        'default_theme': _default_theme(),
        'site_pages': pages,
        'server_status': server_status,
        'notification_count': 0,
        'USE_GOOGLE_FONTS': use_google_fonts,
    }
