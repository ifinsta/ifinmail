"""Spam filtering view."""

import json
import logging
import os

from django.conf import settings as django_settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from backend.apps.core.platform.services.audit import AuditService
from backend.config.branding import branding_overrides_path

from ..types.permissions import PermissionCode
from .auth import require_perm

logger = logging.getLogger('backend')


def _overrides_file() -> str:
    """The shared overrides file branding settings also live in."""
    base_dir = getattr(django_settings, 'BASE_DIR', None)
    return branding_overrides_path(base_dir) or os.path.join(
        os.environ.get('APP_DIR', '.'), 'branding_overrides.json'
    )


def _load_spam_settings() -> dict:
    """Load spam settings from shared overrides file."""
    path = _overrides_file()
    try:
        if os.path.isfile(path):
            with open(path) as f:
                data = json.load(f)
                return data.get('spam', {})
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_spam_settings(settings: dict) -> None:
    """Persist spam settings into shared overrides."""
    path = _overrides_file()
    data = {}
    if os.path.isfile(path):
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    data['spam'] = settings
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


@login_required
@require_perm(PermissionCode.SECURITY_MANAGE)
def spam_filtering(request: HttpRequest) -> HttpResponse:
    """Spam filtering controls screen."""
    spam_settings = _load_spam_settings()
    providers = spam_settings.get('providers', [])
    heuristic_level = spam_settings.get('sensitivity', '5.0')

    return render(
        request,
        'admin/spam_filtering.html',
        {
            'active_section': 'spam',
            'header_search_placeholder': 'Search logs...',
            'provider_headers': [_('Provider Host'), _('Type'), _('Latency')],
            'providers': providers,
            'blocked_spam': spam_settings.get('blocked_spam', '0'),
            'blocked_spam_trend': '',
            'false_positive_pct': '0%',
            'fp_trend': '',
            'filter_activity_bars': [],
            'heuristic_level': heuristic_level,
            'filter_engines': [
                {'name': 'Rspamd', 'detail': str(_('Configured in mail stack')), 'enabled': True},
            ],
        },
    )


@login_required
@require_perm(PermissionCode.SECURITY_MANAGE)
@require_POST
def spam_set_sensitivity(request: HttpRequest) -> JsonResponse:
    """Set global spam sensitivity level."""
    try:
        value = float(request.POST.get('value', '5.0'))
        value = max(1.0, min(10.0, value))
    except (ValueError, TypeError):
        return JsonResponse(
            {'status': 'err', 'error': 'Invalid sensitivity'},
            status=400,
            content_type='application/json; charset=utf-8',
        )
    spam_settings = _load_spam_settings()
    spam_settings['sensitivity'] = f'{value:.1f}'
    try:
        _save_spam_settings(spam_settings)
        AuditService.record(
            action='spam_sensitivity',
            user=request.user.email if request.user.is_authenticated else None,
            detail=f'Set sensitivity to {value:.1f}',
        )
    except OSError as e:
        return JsonResponse(
            {'status': 'err', 'error': str(e)},
            status=500,
            content_type='application/json; charset=utf-8',
        )
    return JsonResponse(
        {'status': 'ok', 'value': value},
        content_type='application/json; charset=utf-8',
    )


@login_required
@require_perm(PermissionCode.SECURITY_MANAGE)
@require_POST
def spam_add_provider(request: HttpRequest) -> JsonResponse:
    """Add a new DNSBL provider."""
    host = request.POST.get('host', '').strip()
    ptype = request.POST.get('type', '').strip().upper() or 'CUSTOM'
    if not host:
        return JsonResponse(
            {'status': 'err', 'error': 'Provider host required'},
            status=400,
            content_type='application/json; charset=utf-8',
        )
    spam_settings = _load_spam_settings()
    providers = spam_settings.get('providers', [])
    # Do not add a provider that is already listed (same host, case-insensitive).
    if any(str(p.get('host', '')).lower() == host.lower() for p in providers):
        return JsonResponse(
            {'status': 'err', 'error': 'Provider already listed'},
            status=409,
            content_type='application/json; charset=utf-8',
        )
    providers.append(
        {
            'host': host,
            'type': ptype,
            'latency': '—',
            'tone': 'neutral',
        }
    )
    spam_settings['providers'] = providers
    try:
        _save_spam_settings(spam_settings)
        AuditService.record(
            action='spam_provider_added',
            user=request.user.email if request.user.is_authenticated else None,
            detail=f'Added DNSBL provider: {host} ({ptype})',
        )
    except OSError as e:
        return JsonResponse(
            {'status': 'err', 'error': str(e)},
            status=500,
            content_type='application/json; charset=utf-8',
        )
    return JsonResponse(
        {'status': 'ok', 'host': host, 'type': ptype},
        content_type='application/json; charset=utf-8',
    )
