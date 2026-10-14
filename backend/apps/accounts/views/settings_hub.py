"""Settings hub: overview plus the grouped settings pages without their own view."""

from __future__ import annotations

from collections.abc import Callable

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from ..services.effective_config import EffectiveConfig
from ..services.settings_catalogue import PAGE_SLUGS, SettingsCatalogue
from ..types.permissions import PermissionCode
from ..types.settings import ConfigSection
from .auth import require_perm

# slug -> read-only section builder. Pages with custom templates are listed in _TEMPLATES.
_BUILDERS: dict[str, Callable[[], list[ConfigSection]]] = {
    'mail': EffectiveConfig.mail,
    'deliverability': EffectiveConfig.deliverability,
    'security': EffectiveConfig.security,
    'monitoring': EffectiveConfig.monitoring,
    'storage': EffectiveConfig.storage,
    'backups': EffectiveConfig.backups,
    'language': EffectiveConfig.language,
    'about': EffectiveConfig.about,
}
_TEMPLATES: dict[str, str] = {
    'appearance': 'admin/settings_appearance.html',
    'maintenance': 'admin/settings_maintenance.html',
    'about': 'admin/settings_about.html',
}
_DEFAULT_TEMPLATE = 'admin/settings_config.html'


@login_required
@require_perm(PermissionCode.CONSOLE_ACCESS)
@require_GET
def settings_hub(request: HttpRequest) -> HttpResponse:
    """Overview of every settings area, grouped."""
    return render(
        request,
        'admin/settings_hub.html',
        {
            'active_section': 'settings',
            'header_search_placeholder': 'Search settings...',
            'show_settings_icon': True,
            'settings_groups': SettingsCatalogue.groups(),
        },
    )


@login_required
@require_perm(PermissionCode.CONSOLE_ACCESS)
@require_GET
def settings_page(request: HttpRequest, slug: str) -> HttpResponse:
    """Render one settings page that has no dedicated view."""
    if slug not in PAGE_SLUGS:
        raise Http404(slug)
    item = SettingsCatalogue.get(slug)
    builder = _BUILDERS.get(slug)
    return render(
        request,
        _TEMPLATES.get(slug, _DEFAULT_TEMPLATE),
        {
            'active_section': slug,
            'header_search_placeholder': 'Search settings...',
            'show_settings_icon': True,
            'settings_item': item,
            'config_sections': builder() if builder else [],
            **(_appearance_context(request) if slug == 'appearance' else {}),
        },
    )


def _appearance_context(request: HttpRequest) -> dict[str, object]:
    from ..services import appearance
    from ..services.roles import RoleService

    return {
        'default_theme': appearance.default_theme(),
        'can_set_default_theme': RoleService.has_perm(request.user, PermissionCode.SYSTEM_MANAGE),
    }


@login_required
@require_perm(PermissionCode.SYSTEM_MANAGE)
@require_POST
def appearance_default(request: HttpRequest) -> HttpResponse:
    """The look people get until they choose their own."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from ..services import appearance

    try:
        value = appearance.set_default_theme(request.POST.get('theme', ''), request.user.email)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f'People who have not chosen a look now get: {value}.')
    return redirect('accounts:settings_page', slug='appearance')
