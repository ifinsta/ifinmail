"""Marketplace: browse, install and manage plugins; submit and review new ones.

Web flow: views -> forms -> plugin services. Browsing and submitting need console access; changing
what is installed and reviewing submissions need ``system.manage``. Every POST redirects (PRG) on
success so a refresh never repeats an operation.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from backend.apps.core.plugins.services import (
    CatalogService,
    InstallationService,
    SubmissionService,
    registry,
)
from backend.apps.core.plugins.services import manifest as manifests
from backend.apps.core.plugins.services.catalog import is_compatible
from backend.apps.core.plugins.services.manifest import PluginManifest
from backend.apps.core.plugins.types import (
    ABSENT,
    ApplyStatus,
    InstallationState,
    ManifestError,
    Operation,
    PluginError,
    SettingsError,
    SubmissionState,
    allowed_operations,
)

from ..forms.marketplace import (
    SETTING_PREFIX,
    PluginActionForm,
    SubmissionActionForm,
    SubmitPluginForm,
)
from ..services.roles import RoleService
from ..types.permissions import PermissionCode
from .auth import require_perm

_VIEW = require_perm(PermissionCode.CONSOLE_ACCESS)
_MANAGE = require_perm(PermissionCode.SYSTEM_MANAGE)
_TABS = ('discover', 'installed', 'submissions')

_STATE_TONE = {
    InstallationState.ENABLED: 'success',
    InstallationState.DISABLED: 'neutral',
    InstallationState.FAILED: 'danger',
    InstallationState.INSTALLING: 'info',
    InstallationState.APPLYING: 'info',
    InstallationState.UNINSTALLING: 'info',
}
_SUBMISSION_TONE = {
    SubmissionState.SUBMITTED: 'info',
    SubmissionState.APPROVED: 'success',
    SubmissionState.REJECTED: 'danger',
    SubmissionState.WITHDRAWN: 'neutral',
    SubmissionState.RETIRED: 'neutral',
}
_APPLY_TONE = {
    ApplyStatus.APPLIED: 'success',
    ApplyStatus.APPLYING: 'info',
    ApplyStatus.NOT_APPLIED: 'warning',
    ApplyStatus.UNKNOWN: 'neutral',
}


def _actor(request: HttpRequest) -> str:
    return request.user.email


def _can_manage(request: HttpRequest) -> bool:
    return RoleService.has_perm(request.user, PermissionCode.SYSTEM_MANAGE)


def _fields(
    manifest: PluginManifest,
    values: dict | None,
    errors: dict[str, str] | None = None,
) -> list[dict]:
    """Template-ready setting fields (current value, or default, or what was just posted)."""
    values = values or {}
    errors = errors or {}
    out = []
    for spec in manifest.settings:
        value = values.get(spec.key, spec.default)
        out.append(
            {
                'name': f'{SETTING_PREFIX}{spec.key}',
                'id': f'pl-{spec.key}',
                'spec': spec,
                'kind': spec.base_type,
                'value': '' if value is None else value,
                'error': errors.get(spec.key, ''),
            }
        )
    return out


def _posted_settings(request: HttpRequest, manifest: PluginManifest) -> dict[str, object]:
    return {
        spec.key: request.POST.get(f'{SETTING_PREFIX}{spec.key}', '') for spec in manifest.settings
    }


def _changes(manifest: PluginManifest, settings: dict | None) -> list[dict]:
    """What the plugin writes, in words, with the values it would produce right now."""
    rows = []
    for contribution in manifest.contributes:
        point = registry.get_point(contribution.point)
        for key, template in contribution.values:
            value = manifests.expand(template, settings or {}) if settings else ''
            rows.append(
                {
                    'point': point.title if point else contribution.point,
                    'key': key,
                    'description': point.keys[key].description
                    if point and key in point.keys
                    else '',
                    'template': template,
                    'value': value,
                }
            )
    return rows


# ---------------------------------------------------------------------------------- pages


@login_required
@_VIEW
@require_GET
def marketplace(request: HttpRequest) -> HttpResponse:
    tab = request.GET.get('tab', 'discover')
    if tab not in _TABS:
        tab = 'discover'
    installed = {row.plugin_id: row for row in InstallationService.all()}
    entries = CatalogService.entries()
    catalog = [
        {
            'entry': e,
            'installed': installed.get(e.plugin_id),
            'update': InstallationService.update_available(installed[e.plugin_id], e)
            if e.plugin_id in installed
            else False,
            'compatible': is_compatible(e.manifest),
        }
        for e in entries
    ]
    by_id = {e.plugin_id: e for e in entries}
    installed_rows = [
        {
            'row': row,
            'name': _safe_name(row),
            'tone': _STATE_TONE.get(row.state, 'neutral'),
            'update': InstallationService.update_available(row, by_id.get(row.plugin_id)),
            'listed': row.plugin_id in by_id,
        }
        for row in installed.values()
    ]
    submissions = [
        {'row': s, 'tone': _SUBMISSION_TONE.get(s.state, 'neutral')}
        for s in SubmissionService.list()
    ]
    return render(
        request,
        'admin/marketplace.html',
        {
            'active_section': 'marketplace',
            'tab': tab,
            'catalog': catalog,
            'installed_rows': installed_rows,
            'submissions': submissions,
            'pending_count': sum(
                1 for s in submissions if s['row'].state == SubmissionState.SUBMITTED
            ),
            'can_manage': _can_manage(request),
            'bundled_errors': CatalogService.bundled_errors() if _can_manage(request) else (),
        },
    )


def _safe_name(row) -> str:
    try:
        return InstallationService.manifest_of(row).name
    except PluginError:
        return row.plugin_id


def _plugin_context(
    request: HttpRequest,
    plugin_id: str,
    *,
    posted: dict | None = None,
    errors: dict[str, str] | None = None,
) -> dict:
    entry = CatalogService.get(plugin_id)
    row = InstallationService.get(plugin_id)
    if entry is None and row is None:
        raise Http404('No such plugin')
    installed_manifest = None
    if row is not None:
        try:
            installed_manifest = InstallationService.manifest_of(row)
        except PluginError:
            installed_manifest = None
    manifest = installed_manifest or (entry.manifest if entry is not None else None)
    if manifest is None:
        raise Http404('This plugin can no longer be read')
    state = row.state if row is not None else ABSENT
    update = InstallationService.update_available(row, entry) if row is not None else False
    values = posted if posted is not None else (row.settings if row is not None else None)
    apply = InstallationService.apply_status()
    points = {c.point for c in manifest.contributes}
    statuses = [apply.get(p, ApplyStatus.UNKNOWN) for p in points]
    overall = (
        ApplyStatus.NOT_APPLIED
        if ApplyStatus.NOT_APPLIED in statuses
        else ApplyStatus.APPLYING
        if ApplyStatus.APPLYING in statuses
        else ApplyStatus.UNKNOWN
        if ApplyStatus.UNKNOWN in statuses
        else ApplyStatus.APPLIED
    )
    return {
        'active_section': 'marketplace',
        'manifest': manifest,
        'entry': entry,
        'row': row,
        'state': state,
        'state_tone': _STATE_TONE.get(state, 'neutral'),
        'operations': [op.value for op in allowed_operations(state)],
        'fields': _fields(manifest, values, errors),
        'changes': _changes(manifest, row.settings if row is not None else None),
        'update': update,
        'new_manifest': entry.manifest if update else None,
        'update_fields': _fields(entry.manifest, values, errors) if update else [],
        'compatible': is_compatible(entry.manifest) if entry else True,
        'apply_status': overall.value,
        'apply_tone': _APPLY_TONE[overall],
        'can_manage': _can_manage(request),
    }


@login_required
@_VIEW
@require_GET
def marketplace_plugin(request: HttpRequest, plugin_id: str) -> HttpResponse:
    return render(request, 'admin/marketplace_plugin.html', _plugin_context(request, plugin_id))


@login_required
@_MANAGE
@require_POST
def marketplace_plugin_action(request: HttpRequest, plugin_id: str) -> HttpResponse:
    form = PluginActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'That request could not be read. Reload the page and try again.')
        return redirect('accounts:marketplace_plugin', plugin_id=plugin_id)
    operation = Operation(form.cleaned_data['action'])
    revision = form.cleaned_data.get('revision')
    actor = _actor(request)
    posted = None
    try:
        if operation in (Operation.INSTALL, Operation.CONFIGURE, Operation.UPDATE):
            entry = CatalogService.get(plugin_id)
            row = InstallationService.get(plugin_id)
            if operation == Operation.UPDATE and entry is not None:
                target = entry.manifest
            elif row is not None:
                target = InstallationService.manifest_of(row)
            elif entry is not None:
                target = entry.manifest
            else:
                raise Http404('No such plugin')
            posted = _posted_settings(request, target)
        if operation == Operation.INSTALL:
            result = InstallationService.install(plugin_id, posted, actor)
        elif operation == Operation.CONFIGURE:
            result = InstallationService.configure(plugin_id, posted, actor, revision)
        elif operation == Operation.UPDATE:
            result = InstallationService.update(plugin_id, actor, revision, posted)
        elif operation == Operation.ENABLE:
            result = InstallationService.enable(plugin_id, actor, revision)
        elif operation == Operation.DISABLE:
            result = InstallationService.disable(plugin_id, actor, revision)
        elif operation == Operation.RETRY:
            result = InstallationService.retry(plugin_id, actor, revision)
        else:
            result = InstallationService.uninstall(plugin_id, actor, revision)
    except SettingsError as exc:
        context = _plugin_context(request, plugin_id, posted=posted, errors=exc.errors)
        context['form_error'] = 'Check the highlighted settings.'
        return render(request, 'admin/marketplace_plugin.html', context, status=400)
    except PluginError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:marketplace_plugin', plugin_id=plugin_id)
    messages.success(request, _done_message(result))
    if result.to_state == ABSENT:
        return redirect(f'{_url("accounts:marketplace")}?tab=installed')
    return redirect('accounts:marketplace_plugin', plugin_id=plugin_id)


def _url(name: str) -> str:
    from django.urls import reverse

    return reverse(name)


def _done_message(result) -> str:
    words = {
        Operation.INSTALL: 'installed and enabled',
        Operation.ENABLE: 'enabled',
        Operation.DISABLE: 'disabled',
        Operation.CONFIGURE: 'settings saved',
        Operation.UPDATE: 'updated',
        Operation.RETRY: 'applied',
        Operation.UNINSTALL: 'uninstalled',
    }
    tail = (
        '' if result.to_state == ABSENT else ' Postfix applies the change within about 10 seconds.'
    )
    return f'{result.plugin_id}: {words[result.operation]}.{tail}'


@login_required
@_VIEW
@require_http_methods(['GET', 'POST'])
def marketplace_submit(request: HttpRequest) -> HttpResponse:
    problems: list[tuple[str, str]] = []
    form = SubmitPluginForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        try:
            row = SubmissionService.submit(
                form.cleaned_data['manifest'], _actor(request), form.cleaned_data.get('note', '')
            )
        except ManifestError as exc:
            problems = exc.problems
        except PluginError as exc:
            problems = [('plugin', str(exc))]
        else:
            messages.success(
                request,
                f'{row.plugin_id} {row.version} submitted. A reviewer must approve it before it '
                'appears in the Marketplace.',
            )
            return redirect('accounts:marketplace_submission', submission_id=row.id)
    elif request.method == 'POST':
        problems = [('form', e) for e in form.non_field_errors()] + [
            (field, err[0]) for field, err in form.errors.items() if field != '__all__'
        ]
    return render(
        request,
        'admin/marketplace_submit.html',
        {
            'active_section': 'marketplace',
            'form': form,
            'problems': problems,
            'manifest_text': request.POST.get('manifest', '') if request.method == 'POST' else '',
        },
        status=400 if problems else 200,
    )


@login_required
@_VIEW
@require_GET
def marketplace_submission(request: HttpRequest, submission_id) -> HttpResponse:
    try:
        row = SubmissionService.get(str(submission_id))
    except PluginError:
        raise Http404('No such submission') from None
    manifest = SubmissionService.manifest_of(row)
    can_manage = _can_manage(request)
    actions = []
    if row.state == SubmissionState.SUBMITTED and can_manage:
        actions += ['approve', 'reject']
    if row.state == SubmissionState.SUBMITTED and (
        can_manage or row.submitted_by == _actor(request)
    ):
        actions.append('withdraw')
    if row.state == SubmissionState.APPROVED and can_manage:
        actions.append('retire')
    return render(
        request,
        'admin/marketplace_submission.html',
        {
            'active_section': 'marketplace',
            'submission': row,
            'tone': _SUBMISSION_TONE.get(row.state, 'neutral'),
            'manifest': manifest,
            'changes': _changes(manifest, None) if manifest else [],
            'actions': actions,
        },
    )


@login_required
@_VIEW
@require_POST
def marketplace_submission_action(request: HttpRequest, submission_id) -> HttpResponse:
    form = SubmissionActionForm(request.POST)
    target = redirect('accounts:marketplace_submission', submission_id=submission_id)
    if not form.is_valid():
        messages.error(request, 'That request could not be read.')
        return target
    action = form.cleaned_data['action']
    note = form.cleaned_data.get('note', '')
    actor = _actor(request)
    can_manage = _can_manage(request)
    if action in ('approve', 'reject', 'retire') and not can_manage:
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied('Reviewing needs the system.manage permission.')
    try:
        if action == 'approve':
            row = SubmissionService.approve(str(submission_id), actor, note)
            messages.success(request, f'{row.plugin_id} {row.version} is now in the Marketplace.')
        elif action == 'reject':
            row = SubmissionService.reject(str(submission_id), actor, note)
            messages.success(request, f'{row.plugin_id} {row.version} rejected.')
        elif action == 'withdraw':
            row = SubmissionService.withdraw(str(submission_id), actor, is_reviewer=can_manage)
            messages.success(request, f'{row.plugin_id} {row.version} withdrawn.')
        else:
            row = SubmissionService.retire(str(submission_id), actor, note)
            messages.success(
                request,
                f'{row.plugin_id} {row.version} retired. Existing installations keep working.',
            )
    except PluginError as exc:
        messages.error(request, str(exc))
    return target
