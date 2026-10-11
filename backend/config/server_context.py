"""
Server-level context processor — injects server metadata into every template.
Values read from environment variables with sensible fallbacks.
"""

from __future__ import annotations

import os

from django.conf import settings


def server_context(request: object) -> dict[str, object]:
    """Context processor — injects server metadata into every template context."""
    version = os.environ.get('APP_VERSION', 'v2.4.0-stable')
    support_email = os.environ.get('SUPPORT_EMAIL', 'support@ifinmail.io')
    docs_url = os.environ.get('DOCS_URL', 'https://ifinmail.dev/docs')
    server_status = os.environ.get('SERVER_STATUS', 'Online')
    # Set USE_GOOGLE_FONTS=0 to serve without the Google Fonts CDN (air-gapped
    # installs); the CSS font stack falls back to the system UI fonts.
    use_google_fonts = os.environ.get('USE_GOOGLE_FONTS', '1').lower() not in ('0', 'false', 'no')
    from backend.apps.accounts.services.registration_policy import registration_open

    return {
        'registration_open': registration_open,  # callable: only evaluated if a template asks
        'server_version': version,
        'CSS_VERSION': settings.CSS_VERSION,
        'support_email': support_email,
        'docs_url': docs_url,
        'server_status': server_status,
        'notification_count': 0,
        'USE_GOOGLE_FONTS': use_google_fonts,
    }
