"""Certificates and entry-point pages (web flow: views -> forms -> services)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.platform.services.entrypoints import (
    CATALOGUE,
    FLOOD_WEB_PER_MINUTE,
    MAIL_CONCURRENT,
    PENALTY_MINUTES,
    SCAN_BAN_THRESHOLD,
    WEB_CONCURRENT,
    WEB_GUARD_PER_MINUTE,
    EntryPointService,
    NetworkError,
)
from backend.apps.core.platform.services.tls import CertificateError, TLSAction, TLSService
from backend.apps.core.telemetry.threats import autoblock
from backend.apps.dns.services.server import DNSServerConfig
from backend.apps.domains.services import DomainService

from ..forms.server import (
    AutoProtectForm,
    BlockForm,
    CertificateActionForm,
    CertificateUploadForm,
    EntryPointForm,
    RateForm,
    UnblockForm,
)
from ..services.stepup import StepUpService
from ..types.permissions import PermissionCode
from .auth import _get_client_ip, require_perm

_SECURITY = require_perm(PermissionCode.SECURITY_MANAGE)


def _actor(request: HttpRequest) -> str | None:
    return request.user.email if request.user.is_authenticated else None


def protected_addresses(request: HttpRequest) -> tuple[str, ...]:
    """Addresses a block must never cover: the person clicking, and this server itself."""
    return tuple(
        a
        for a in (
            _get_client_ip(request),
            request.META.get('REMOTE_ADDR', ''),
            request.META.get('HTTP_X_REAL_IP', ''),
            DNSServerConfig.server_ipv4(),
            DNSServerConfig.server_ipv6(),
        )
        if a
    )


def blocklist_row(row: dict[str, str]) -> dict[str, Any]:
    """A blocklist row for the page, with its expiry as a date (``None`` = until removed)."""
    try:
        until = datetime.fromisoformat(row['expires']) if row.get('expires') else None
    except ValueError:
        until = None
    return {**row, 'until': until}


def _first_error(form: object) -> str:
    for field, errors in form.errors.items():  # type: ignore[attr-defined]
        label = _(field.replace('_', ' ').capitalize())
        return _('{label}: {error}').format(label=label, error=errors[0])
    return _('Please check the form.')


# -- certificates -----------------------------------------------------------
@login_required
@_SECURITY
@require_GET
def certificates_page(request: HttpRequest) -> HttpResponse:
    names = [d.name for d in DomainService.get_all_domains()]
    status = TLSService.status(names)
    return render(
        request,
        'admin/settings_certificates.html',
        {
            'active_section': 'certificates',
            'show_settings_icon': True,
            'tls': status,
            'cert': status.active,
            'custom': status.mode.value == 'custom',
            'last': status.last_request,
            'mail_hostname': DNSServerConfig.mail_hostname(),
            'missing': [c for c in status.coverage if not c.covered],
        },
    )


@login_required
@_SECURITY
@require_POST
def certificates_action(request: HttpRequest) -> HttpResponse:
    form = CertificateActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect('accounts:certificates')
    action = TLSAction(form.cleaned_data['action'])
    TLSService.request(action)
    AuditService.record(
        action=f'certificate_{action.value}', user=_actor(request), detail='requested'
    )
    messages.success(
        request,
        _('Request sent. It usually finishes within a minute; reload to see the result.'),
    )
    return redirect('accounts:certificates')


@login_required
@_SECURITY
@require_POST
def certificates_upload(request: HttpRequest) -> HttpResponse:
    form = CertificateUploadForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect('accounts:certificates')
    try:
        info = TLSService.install_custom(
            form.cleaned_data['certificate'], form.cleaned_data['private_key']
        )
    except CertificateError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:certificates')
    AuditService.record(
        action='certificate_uploaded',
        user=_actor(request),
        detail=f'{info.subject} {info.fingerprint[:16]}',
    )
    messages.success(
        request,
        _('Certificate accepted. It is being installed; reload in a moment to confirm.'),
    )
    return redirect('accounts:certificates')


# -- network ----------------------------------------------------------------
@login_required
@_SECURITY
@require_GET
def network_page(request: HttpRequest) -> HttpResponse:
    probes = EntryPointService.probe_all()
    enabled = EntryPointService.enabled_map()
    rows = []
    for entry in CATALOGUE:
        probe = probes[entry.key]
        rows.append(
            {
                'entry': entry,
                'ports': ', '.join(f'{port}/{proto.value}' for proto, port in entry.ports),
                'enabled': enabled.get(entry.key, True),
                'up': probe.up,
                'millis': probe.millis,
            }
        )
    return render(
        request,
        'admin/settings_network.html',
        {
            'active_section': 'network',
            'show_settings_icon': True,
            'entries': rows,
            'blocklist': [blocklist_row(r) for r in EntryPointService.active_blocklist()],
            'rate': EntryPointService.rate_per_minute(),
            'auto': autoblock.config(),
            'auto_hours': autoblock.HOURS,
            'auto_max': autoblock.MAX_AUTO,
            'auto_allow_text': '\n'.join(autoblock.config().allow),
            'flood_until': EntryPointService.flood_until(),
            'flood_mail': EntryPointService.effective_rate(True),
            'flood_web': FLOOD_WEB_PER_MINUTE,
            'penalty_minutes': PENALTY_MINUTES,
            'web_guard': WEB_GUARD_PER_MINUTE,
            'mail_concurrent': MAIL_CONCURRENT,
            'web_concurrent': WEB_CONCURRENT,
            'scan_ban': SCAN_BAN_THRESHOLD,
            'agent': EntryPointService.agent_status(),
            'client_ip': _get_client_ip(request),
        },
    )


@login_required
@_SECURITY
@require_POST
def network_toggle(request: HttpRequest) -> HttpResponse:
    form = EntryPointForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect('accounts:network')
    try:
        EntryPointService.set_enabled(form.cleaned_data['key'], form.cleaned_data['enabled'])
    except (NetworkError, KeyError) as exc:
        messages.error(
            request, str(exc) if isinstance(exc, NetworkError) else _('Unknown entry point.')
        )
        return redirect('accounts:network')
    state = 'opened' if form.cleaned_data['enabled'] else 'closed'
    AuditService.record(
        action='entrypoint_toggle',
        user=_actor(request),
        detail=f'{form.cleaned_data["key"]} {state}',
    )
    messages.success(
        request,
        _('Port opened. The firewall applies it within a few seconds.')
        if form.cleaned_data['enabled']
        else _('Port closed. The firewall applies it within a few seconds.'),
    )
    return redirect('accounts:network')


@login_required
@_SECURITY
@require_POST
def network_block(request: HttpRequest) -> HttpResponse:
    form = BlockForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect('accounts:network')
    try:
        text = EntryPointService.block(
            form.cleaned_data['cidr'],
            form.cleaned_data['note'] or '',
            protect=protected_addresses(request),
        )
    except NetworkError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:network')
    AuditService.record(action='network_block', user=_actor(request), detail=text)
    messages.success(request, _('{net} is blocked.').format(net=text))
    return redirect('accounts:network')


@login_required
@_SECURITY
@require_POST
def network_auto(request: HttpRequest) -> HttpResponse:
    """Turn automatic blocking and flood mode on or off (password again; both start off)."""
    form = AutoProtectForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect('accounts:network')
    problem = StepUpService.confirm(request)
    if problem:
        messages.error(request, _(problem))
        return redirect('accounts:network')
    data = form.cleaned_data
    try:
        cfg = autoblock.save(
            block=data['block'],
            flood=data['flood'],
            hours=data['hours'],
            allow_text=data['allow'] or '',
        )
    except NetworkError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:network')
    if not cfg.flood:
        EntryPointService.end_flood()
    detail = (
        f'block={"on" if cfg.block else "off"} flood={"on" if cfg.flood else "off"} '
        f'hours={cfg.hours} allow={len(cfg.allow)}'
    )
    AuditService.record(action='network_auto_config', user=_actor(request), detail=detail)
    messages.success(request, _('Automatic protection saved.'))
    return redirect('accounts:network')


@login_required
@_SECURITY
@require_POST
def network_unblock(request: HttpRequest) -> HttpResponse:
    form = UnblockForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect('accounts:network')
    cidr = form.cleaned_data['cidr']
    if EntryPointService.unblock(cidr):
        AuditService.record(action='network_unblock', user=_actor(request), detail=cidr)
        messages.success(request, _('{net} is no longer blocked.').format(net=cidr))
    else:
        messages.error(request, _('That entry could not be found.'))
    return redirect('accounts:network')


@login_required
@_SECURITY
@require_POST
def network_rate(request: HttpRequest) -> HttpResponse:
    form = RateForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect('accounts:network')
    try:
        value = EntryPointService.set_rate_per_minute(form.cleaned_data['per_minute'])
    except NetworkError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:network')
    AuditService.record(action='network_rate', user=_actor(request), detail=str(value))
    messages.success(
        request,
        _('Connection limit saved.') if value else _('Connection limit turned off.'),
    )
    return redirect('accounts:network')
