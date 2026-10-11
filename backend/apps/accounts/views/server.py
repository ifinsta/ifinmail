"""Certificates and entry-point pages (web flow: views -> forms -> services)."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from backend.apps.dns.services.server import DNSServerConfig
from backend.apps.domains.services import DomainService
from backend.services.audit import AuditService
from backend.services.entrypoints import CATALOGUE, EntryPointService, NetworkError
from backend.services.tls import CertificateError, TLSAction, TLSService

from ..forms.server import (
    BlockForm,
    CertificateActionForm,
    CertificateUploadForm,
    EntryPointForm,
    RateForm,
    UnblockForm,
)
from .auth import _get_client_ip, _is_staff

_STAFF = user_passes_test(_is_staff, login_url='accounts:login')


def _actor(request: HttpRequest) -> str | None:
    return request.user.email if request.user.is_authenticated else None


def _first_error(form: object) -> str:
    for field, errors in form.errors.items():  # type: ignore[attr-defined]
        return f'{field.replace("_", " ").capitalize()}: {errors[0]}'
    return 'Please check the form.'


# -- certificates -----------------------------------------------------------
@login_required
@_STAFF
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
@_STAFF
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
        request, 'Request sent. It usually finishes within a minute; reload to see the result.'
    )
    return redirect('accounts:certificates')


@login_required
@_STAFF
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
        request, 'Certificate accepted. It is being installed; reload in a moment to confirm.'
    )
    return redirect('accounts:certificates')


# -- network ----------------------------------------------------------------
@login_required
@_STAFF
@require_GET
def network_page(request: HttpRequest) -> HttpResponse:
    probes = EntryPointService.probe_all()
    rows = []
    for entry in CATALOGUE:
        probe = probes[entry.key]
        rows.append(
            {
                'entry': entry,
                'ports': ', '.join(f'{port}/{proto.value}' for proto, port in entry.ports),
                'enabled': EntryPointService.is_enabled(entry.key),
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
            'blocklist': EntryPointService.blocklist(),
            'rate': EntryPointService.rate_per_minute(),
            'agent': EntryPointService.agent_status(),
            'client_ip': _get_client_ip(request),
        },
    )


@login_required
@_STAFF
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
            request, str(exc) if isinstance(exc, NetworkError) else 'Unknown entry point.'
        )
        return redirect('accounts:network')
    state = 'opened' if form.cleaned_data['enabled'] else 'closed'
    AuditService.record(
        action='entrypoint_toggle',
        user=_actor(request),
        detail=f'{form.cleaned_data["key"]} {state}',
    )
    messages.success(request, f'Port {state}. The firewall applies it within a few seconds.')
    return redirect('accounts:network')


@login_required
@_STAFF
@require_POST
def network_block(request: HttpRequest) -> HttpResponse:
    form = BlockForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect('accounts:network')
    protect = tuple(
        a
        for a in (
            _get_client_ip(request),
            request.META.get('REMOTE_ADDR', ''),
            request.META.get('HTTP_X_REAL_IP', ''),
            DNSServerConfig.server_ipv4(),
        )
        if a
    )
    try:
        text = EntryPointService.block(
            form.cleaned_data['cidr'], form.cleaned_data['note'] or '', protect=protect
        )
    except NetworkError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:network')
    AuditService.record(action='network_block', user=_actor(request), detail=text)
    messages.success(request, f'{text} is blocked.')
    return redirect('accounts:network')


@login_required
@_STAFF
@require_POST
def network_unblock(request: HttpRequest) -> HttpResponse:
    form = UnblockForm(request.POST)
    if form.is_valid() and EntryPointService.unblock(form.cleaned_data['cidr']):
        AuditService.record(
            action='network_unblock', user=_actor(request), detail=form.cleaned_data['cidr']
        )
        messages.success(request, f'{form.cleaned_data["cidr"]} is no longer blocked.')
    else:
        messages.error(request, 'That entry could not be found.')
    return redirect('accounts:network')


@login_required
@_STAFF
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
        request, 'Connection limit saved.' if value else 'Connection limit turned off.'
    )
    return redirect('accounts:network')
