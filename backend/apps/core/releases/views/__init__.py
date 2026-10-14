"""releases — console views: publish and manage builds (web flow: web.py → views → forms → services).

The page lives under Settings (``system.manage``). Publishing and deleting re-ask for the
administrator's password: a build published here is installed on every device that updates.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from backend.apps.accounts.services.stepup import StepUpService
from backend.apps.accounts.types.permissions import PermissionCode
from backend.apps.accounts.views.auth import require_perm
from backend.apps.core.releases.forms import ReleaseActionForm, ReleasePublishForm
from backend.apps.core.releases.services import ReleaseService
from backend.apps.core.releases.types import (
    ACTIVE_DEVICE_DAYS,
    CHANNEL_VALUES,
    Platform,
)

_MANAGE = require_perm(PermissionCode.SYSTEM_MANAGE)
_PLATFORM = Platform.ANDROID.value


def _actor(request: HttpRequest) -> str:
    return getattr(request.user, 'email', '') or 'unknown'


@login_required
@_MANAGE
@require_GET
def releases_page(request: HttpRequest) -> HttpResponse:
    releases = list(ReleaseService.list_releases(_PLATFORM))
    latest = next((r for r in releases if r.is_published and r.channel == 'stable'), None)
    return render(
        request,
        'admin/settings_releases.html',
        {
            'active_section': 'releases',
            'show_settings_icon': True,
            'releases': releases,
            'latest': latest,
            'adoption': ReleaseService.adoption(_PLATFORM),
            'active_devices': ReleaseService.active_device_count(_PLATFORM),
            'active_days': ACTIVE_DEVICE_DAYS,
            'channels': CHANNEL_VALUES,
            'package': ReleaseService.expected_package(_PLATFORM),
        },
    )


@login_required
@_MANAGE
@require_POST
def release_publish(request: HttpRequest) -> HttpResponse:
    form = ReleasePublishForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, 'Choose an APK file and check the other fields.')
        return redirect('releases:console')
    problem = StepUpService.confirm(request)
    if problem:
        messages.error(request, problem)
        return redirect('releases:console')
    data = form.cleaned_data
    try:
        release = ReleaseService.publish(
            upload=data['file'],
            platform=_PLATFORM,
            channel=data['channel'],
            notes=data['notes'] or '',
            mandatory=bool(data['mandatory']),
            rollout_percent=data['rollout_percent'],
            publish=bool(data['publish']),
            actor=_actor(request),
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('releases:console')
    if release.is_published:
        messages.success(
            request,
            f'Version {release.version_name} is published on the {release.channel} channel. '
            f'Devices will be offered it within a day.',
        )
    else:
        messages.success(
            request, f'Version {release.version_name} was uploaded but is not offered to devices yet.'
        )
    return redirect('releases:console')


@login_required
@_MANAGE
@require_POST
def release_action(request: HttpRequest) -> HttpResponse:
    form = ReleaseActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'That request could not be read.')
        return redirect('releases:console')
    data = form.cleaned_data
    release = ReleaseService.get(data['platform'], data['channel'], data['version_code'])
    if release is None:
        messages.error(request, 'That release no longer exists.')
        return redirect('releases:console')
    action = data['action']
    if action in ('delete', 'mandatory_on'):
        problem = StepUpService.confirm(request)
        if problem:
            messages.error(request, problem)
            return redirect('releases:console')
    actor = _actor(request)
    label = release.version_name
    try:
        if action == 'delete':
            ReleaseService.delete(release, actor=actor)
            messages.success(request, f'Version {label} and its file were deleted.')
        elif action == 'withdraw':
            ReleaseService.update(release, is_published=False, actor=actor)
            messages.success(request, f'Version {label} is withdrawn. Devices will not be offered it.')
        elif action == 'restore':
            ReleaseService.update(release, is_published=True, actor=actor)
            messages.success(request, f'Version {label} is offered to devices again.')
        elif action == 'mandatory_on':
            ReleaseService.update(release, mandatory=True, rollout_percent=100, actor=actor)
            messages.success(request, f'Devices older than {label} must now update.')
        elif action == 'mandatory_off':
            ReleaseService.update(release, mandatory=False, actor=actor)
            messages.success(request, f'Version {label} is no longer mandatory.')
        elif action == 'rollout':
            share = data['rollout_percent']
            if share is None:
                raise ValueError('Enter the share of devices, from 0 to 100.')
            ReleaseService.update(release, rollout_percent=share, actor=actor)
            messages.success(request, f'Version {label} is offered to {share}% of devices.')
        elif action == 'notes':
            ReleaseService.update(release, notes=data['notes'] or '', actor=actor)
            messages.success(request, f'Notes for {label} saved.')
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect('releases:console')


__all__ = ['release_action', 'release_publish', 'releases_page']
