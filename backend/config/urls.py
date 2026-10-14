"""
Root URL configuration for ifinmail.
"""

import logging

from django.conf import settings
from django.contrib import admin
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import include, path
from django.views.decorators.csrf import csrf_exempt

from backend.apps.core.storage.views.media import media as storage_media
from backend.apps.mail.web import autoconfig_mozilla, autoconfig_outlook, mta_sts_policy
from backend.config import api_versions, public_pages
from backend.config.branding import DEFAULT_BRAND_NAME

logger = logging.getLogger('backend')


@csrf_exempt
def csp_report(request: HttpRequest) -> JsonResponse:
    """CSP violation report endpoint — logs violations for analysis.

    Endpoint accepts JSON CSP reports from browsers.  Violations are
    logged so the policy can be tightened without breaking real users.
    Persisted to telemetry so CSP breakage is visible in the logs UI.
    """
    import json as _json
    import logging

    csp_logger = logging.getLogger('backend.csp')
    try:
        body = _json.loads(request.body)
        csp_report = body.get('csp-report', {})
        csp_logger.warning(
            'CSP violation: %s — %s — %s',
            csp_report.get('violated-directive', 'unknown'),
            csp_report.get('blocked-uri', 'unknown'),
            csp_report.get('document-uri', 'unknown'),
        )
        try:
            from backend.apps.core.telemetry.services.telemetry_service import TelemetryService
            from backend.apps.core.telemetry.types import ErrorSeverity, ErrorSource

            TelemetryService.capture(
                f'CSP violation: {csp_report.get("violated-directive", "unknown")}',
                severity=ErrorSeverity.WARNING,
                source=ErrorSource.CSP,
                request=request,
                extra={'csp-report': csp_report},
            )
        except Exception:
            pass
    except (_json.JSONDecodeError, Exception):
        csp_logger.warning('CSP report parse failure')
    return JsonResponse(
        {'status': 'ok'}, status=200, content_type='application/json; charset=utf-8'
    )


def health_check(request: HttpRequest) -> JsonResponse:
    """Liveness probe for Docker, nginx and the updater (same body as ``GET /api/v1/health``)."""
    from backend.apps.core.viewsets.health import liveness

    body, healthy = liveness()
    return JsonResponse(
        body.model_dump(),
        status=200 if healthy else 503,
        content_type='application/json; charset=utf-8',
    )


def legacy_accounts_redirect(request: HttpRequest, path: str = '') -> HttpResponse:
    # EC-44: Redirect /admin/ directly to dashboard (avoid double redirect chain)
    from django.urls import reverse

    target = reverse('accounts:dashboard') if not path else f'/accounts/{path}'
    return redirect(target, permanent=False)


def manifest(request: HttpRequest) -> JsonResponse:
    """Web app manifest, branded from ``BRAND_CONFIG``.

    When a favicon is uploaded it becomes the PWA icon too; otherwise the
    shipped default icons are listed (a manifest needs icons to be installable).
    """
    from django.templatetags.static import static as static_url

    brand = getattr(settings, 'BRAND_CONFIG', None)
    name = (getattr(brand, 'name', '') or DEFAULT_BRAND_NAME).strip()
    favicon = (getattr(brand, 'favicon_url', '') or '').strip()
    if favicon == static_url('icons/favicon.ico'):
        # The shipped default written into branding_overrides.json, not an upload: list the
        # whole icon set (PNG, maskable, SVG) instead of the one 48 px .ico.
        favicon = ''
    theme_color = getattr(brand, 'secondary_color', '') or '#0f2b5b'
    if favicon:
        ext = favicon.rsplit('.', 1)[-1].lower()
        mime = {
            'svg': 'image/svg+xml',
            'png': 'image/png',
            'ico': 'image/x-icon',
            'webp': 'image/webp',
        }.get(ext, 'image/png')
        icons = [{'src': favicon, 'sizes': 'any', 'type': mime, 'purpose': 'any'}]
    else:
        # PNG for installers that need raster icons (Android, Chrome), a separate maskable
        # icon with the safe-zone padding, and the SVG for everything that scales.
        icons = [
            {
                'src': static_url('icons/icon-192.png'),
                'sizes': '192x192',
                'type': 'image/png',
                'purpose': 'any',
            },
            {
                'src': static_url('icons/icon-512.png'),
                'sizes': '512x512',
                'type': 'image/png',
                'purpose': 'any',
            },
            {
                'src': static_url('icons/icon-maskable-512.png'),
                'sizes': '512x512',
                'type': 'image/png',
                'purpose': 'maskable',
            },
            {
                'src': static_url('icons/mark.svg'),
                'sizes': 'any',
                'type': 'image/svg+xml',
                'purpose': 'any',
            },
        ]
    return JsonResponse(
        {
            'name': f'{name} — Mail Server Admin',
            'short_name': name[:12],
            'description': 'Manage your self-hosted mail server',
            'start_url': '/accounts/dashboard/',
            'scope': '/',
            'display': 'standalone',
            'background_color': '#F9FAFB',
            'theme_color': theme_color,
            'orientation': 'any',
            'icons': icons,
        },
        content_type='application/manifest+json',
    )


urlpatterns = [
    *public_pages.urlpatterns,
    path('manifest.webmanifest', manifest, name='manifest'),
    path('csp-report/', csp_report, name='csp-report'),
    path('health/', health_check, name='health-check'),
    # App releases: what devices poll, the newest-build permalink and the console page
    # (before accounts/, whose settings/<slug>/ catch-all would otherwise take the page)
    path('', include('backend.apps.core.releases.urls')),
    path('accounts/', include('backend.apps.accounts.urls')),
    *api_versions.urlpatterns,
    path('admin/', legacy_accounts_redirect),
    path('admin/<path:path>', legacy_accounts_redirect),
    path('manage-panel/', admin.site.urls),
    path('domains/', include('backend.apps.domains.urls')),
    path('devices/', include('backend.apps.devices.urls')),
    path('dns/', include('backend.apps.dns.urls')),
    # Email client autoconfiguration
    path(
        '.well-known/autoconfig/mail/config-v1.1.xml', autoconfig_mozilla, name='autoconfig-mozilla'
    ),
    path('mail/config-v1.1.xml', autoconfig_mozilla, name='autoconfig-mozilla-alt'),
    path('autodiscover/autodiscover.xml', autoconfig_outlook, name='autoconfig-outlook'),
    path('Autodiscover/Autodiscover.xml', autoconfig_outlook, name='autoconfig-outlook-ci'),
    path('.well-known/mta-sts.txt', mta_sts_policy, name='mta-sts-policy'),
]

# Uploaded media: nginx serves files on the disk itself; anything not there (media in object
# storage, or the dev server) reaches the console, which negotiates retrieval.
urlpatterns.append(path('media/<path:key>', storage_media, name='media'))

# Custom error handlers
ERROR_HANDLERS: dict[int, tuple[str, str, str, str, str]] = {
    400: ('400 Bad Request: %s', 'Bad request', 'Invalid request', 'warn', '400.html'),
    403: (
        '403 Forbidden: %s',
        'Forbidden',
        'You do not have permission to access this resource',
        'warn',
        '403.html',
    ),
    404: ('404 Not Found: %s', 'Not found', 'Resource not found', 'warn', '404.html'),
    500: (
        '500 Internal Server Error',
        'Internal server error',
        'An unexpected error occurred',
        'exception',
        '500.html',
    ),
    502: ('502 Bad Gateway: %s', 'Bad gateway', 'Invalid upstream response', 'warn', '502.html'),
    503: (
        '503 Service Unavailable: %s',
        'Service unavailable',
        'Temporarily unavailable',
        'warn',
        '503.html',
    ),
    504: ('504 Gateway Timeout: %s', 'Gateway timeout', 'Upstream timed out', 'warn', '504.html'),
}

for _code in (400, 403, 404, 500, 502, 503, 504):
    globals()[f'handler{_code}'] = f'backend.config.urls.custom_error_{_code}'


def _make_error_handler(status_code: int):
    log_msg, json_error, json_detail, log_level, template = ERROR_HANDLERS[status_code]

    def handler(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:
        path = request.path
        try:
            if log_level == 'exception':
                logger.exception(log_msg, path)
            else:
                logger.log(getattr(logging, log_level.upper(), logging.WARNING), log_msg, path)
        except Exception:
            # Never let logging failures cascade
            pass
        # Persist to telemetry so every error page is traceable (best-effort).
        try:
            from backend.apps.core.telemetry.services.telemetry_service import TelemetryService
            from backend.apps.core.telemetry.types import ErrorSeverity, ErrorSource

            if exception is not None:
                TelemetryService.capture(exception, source=ErrorSource.HTTP, request=request)
            elif status_code >= 500:
                TelemetryService.capture(
                    log_msg % path,
                    severity=ErrorSeverity.ERROR,
                    source=ErrorSource.HTTP,
                    request=request,
                )
        except Exception:
            pass

        if _wants_html(request):
            try:
                return render(
                    request,
                    template,
                    {
                        'error_code': str(status_code),
                        'error_title': json_error.title(),
                        'error_description': str(exception) if exception is not None else '',
                        'error_detail': json_detail,
                    },
                    status=status_code,
                )
            except Exception:
                # Fall back to JSON if template rendering fails
                pass

        return JsonResponse(
            {'error': json_error, 'detail': json_detail},
            status=status_code,
            content_type='application/json; charset=utf-8',
        )

    return handler


def _wants_html(request: HttpRequest) -> bool:
    accept = request.META.get('HTTP_ACCEPT', '')
    if 'text/html' in accept:
        return True
    # */* or empty accept means client accepts anything — prefer JSON for API safety
    # Most browsers explicitly send text/html; only API clients send bare */*
    if accept in ('', '*/*'):
        return False
    return False


for _code in ERROR_HANDLERS:
    globals()[f'custom_error_{_code}'] = _make_error_handler(_code)
