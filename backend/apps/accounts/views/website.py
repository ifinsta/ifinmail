"""Settings → Website: the words on the public pages, and what each page is doing.

Whether a page is shown (standard, custom or off) is a setting of the "Website pages" plugin; the
text of a custom page is written here, because a plugin's settings are short values and a page is
prose. Nothing here reads or changes anything outside the public site.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from backend.apps.core.plugins.services import InstallationService
from backend.apps.core.website.services import content, policy, starter
from backend.apps.core.website.types import BY_KEY, LIMITS, PAGES, PLUGIN_ID, ContentError, Mode

from ..types.permissions import PermissionCode
from .auth import require_perm

MODE_WORDS = {
    Mode.STANDARD: ('neutral', 'Standard text'),
    Mode.CUSTOM: ('info', 'Your text'),
    Mode.OFF: ('warning', 'Off'),
}


def _actor(request: HttpRequest) -> str:
    return request.user.email if request.user.is_authenticated else ''


def _plugin_state() -> dict[str, object]:
    row = InstallationService.get(PLUGIN_ID)
    return {
        'installed': row is not None,
        'url': reverse('accounts:marketplace_plugin', args=[PLUGIN_ID]),
        'state': getattr(row, 'state', ''),
    }


@login_required
@require_perm(PermissionCode.SYSTEM_MANAGE)
def website_pages(request: HttpRequest) -> HttpResponse:
    current = policy.current()
    written = content.has_text()
    rows = []
    for page in PAGES:
        mode = current.mode(page.key)
        tone, word = MODE_WORDS[Mode(mode)]
        rows.append(
            {
                'page': page,
                'url': reverse(page.key),
                'edit_url': reverse('accounts:website_page', args=[page.key]),
                'mode': mode,
                'tone': tone,
                'word': word,
                'written': page.key in written,
                # Custom with nothing written still shows the standard text.
                'empty_custom': mode == Mode.CUSTOM and page.key not in written,
            }
        )
    return render(
        request,
        'admin/website_pages.html',
        {
            'active_section': 'website',
            'rows': rows,
            'plugin': _plugin_state(),
            'policy': current,
        },
    )


@login_required
@require_perm(PermissionCode.SYSTEM_MANAGE)
@require_http_methods(['GET', 'POST'])
def website_page(request: HttpRequest, key: str) -> HttpResponse:
    page = BY_KEY.get(key)
    if page is None:
        raise Http404(key)
    values = content.get(key).as_dict()
    errors: dict[str, str] = {}
    if request.method == 'POST':
        action = request.POST.get('action', 'save')
        posted = {name: request.POST.get(name, '') for name in LIMITS}
        if action == 'starter':
            from backend.config import public_pages

            try:
                start = starter.convert(public_pages.standard_html(request, key))
            except Exception:  # a page that cannot render must not break the editor
                messages.error(request, _('The standard text of this page could not be read.'))
                values = posted
            else:
                values = {
                    **posted,
                    'title': start.title,
                    'description': start.description,
                    'heading': start.heading,
                    'lede': start.lede,
                    'body': start.body,
                }
                messages.success(
                    request,
                    _('The standard text is loaded below. Change it, then save.'),
                )
        elif action == 'clear':
            content.clear(key, _actor(request))
            messages.success(request, _('Your text for this page was removed.'))
            return redirect('accounts:website_page', key=key)
        else:
            try:
                content.save(key, posted, _actor(request))
            except ContentError as exc:
                errors = exc.errors
                values = posted
            else:
                messages.success(request, _('Saved.'))
                return redirect('accounts:website_page', key=key)
    mode = policy.current().mode(key)
    tone, word = MODE_WORDS[Mode(mode)]
    return render(
        request,
        'admin/website_page.html',
        {
            'active_section': 'website',
            'page': page,
            'values': values,
            'errors': errors,
            'limits': LIMITS,
            'mode': mode,
            'mode_tone': tone,
            'mode_word': word,
            'has_text': key in content.has_text(),
            'public_url': reverse(key),
            'plugin': _plugin_state(),
        },
    )
