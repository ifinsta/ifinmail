"""Spam filtering: how strict the filter is, the extra DNS lists it asks, and what it did."""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from backend.apps.core.telemetry import report
from backend.apps.mail.services import spam_policy
from backend.apps.mail.services.spam_policy import SpamSettingError

from ..types.permissions import PermissionCode
from .auth import require_perm

logger = logging.getLogger('backend')

PERIOD_CHOICES = ('day', 'week')

# What the page says about each state of the engine's copy of the settings.
APPLY_WORDS = {
    'applied': ('success', 'Applied'),
    'applying': ('warning', 'Applying'),
    'not_applied': ('danger', 'Not applied yet'),
    'unknown': ('neutral', 'Not confirmed'),
}
# What each state of a tested list means for the person reading the table.
LIST_STATES = {
    'works': ('success', 'Answers'),
    'quiet': ('info', 'Reachable'),
    'refused': ('warning', 'Refuses this server'),
    'missing': ('danger', 'Name not found'),
    'down': ('danger', 'No answer'),
}
# Lists Rspamd consults without being asked (its own configuration), named so the table is not
# mistaken for the whole story.
BUILT_IN = ('Spamhaus ZEN', 'Mailspike', 'SenderScore', 'Spameatingmonkey', 'DNSWL', 'Nixspam')


def _actor(request: HttpRequest) -> str:
    return request.user.email if request.user.is_authenticated else ''


def _back() -> HttpResponseRedirect:
    return redirect(reverse('accounts:spam_filtering'))


def _guarded(request: HttpRequest, action) -> HttpResponseRedirect:
    """Run a change; a value the administrator can fix is shown as a message, never a 500."""
    try:
        done = action()
    except SpamSettingError as exc:
        messages.error(request, str(exc))
    else:
        if done:
            messages.success(request, done)
    return _back()


@login_required
@require_perm(PermissionCode.SECURITY_MANAGE)
def spam_filtering(request: HttpRequest) -> HttpResponse:
    period = request.GET.get('period', 'day')
    period = period if period in PERIOD_CHOICES else 'day'
    level = spam_policy.level()
    stats = report.spam_section(period)

    lists = []
    for p in spam_policy.providers():
        tested = p.tested or {}
        tone, word = LIST_STATES.get(str(tested.get('state')), ('neutral', 'Not tested yet'))
        lists.append(
            {
                'host': p.host,
                'kind': p.kind,
                'kind_label': p.label,
                'enabled': p.enabled,
                'tone': tone,
                'word': word,
                'detail': tested.get('detail', ''),
                'ms': tested.get('ms'),
                'at': tested.get('at', ''),
            }
        )
    tone, word = APPLY_WORDS.get(spam_policy.applied(), APPLY_WORDS['unknown'])
    levels = {
        str(n): {k: f'{v:g}' for k, v in spam_policy.thresholds(n).items()}
        for n in range(spam_policy.MIN_LEVEL, spam_policy.MAX_LEVEL + 1)
    }
    return render(
        request,
        'admin/spam_filtering.html',
        {
            'active_section': 'spam',
            'level': level,
            'levels': levels,
            'now_thresholds': levels[str(level)],
            'min_level': spam_policy.MIN_LEVEL,
            'max_level': spam_policy.MAX_LEVEL,
            'default_level': spam_policy.DEFAULT_LEVEL,
            'stats': stats,
            'period': period,
            'lists': lists,
            'list_kinds': [(k, v[0], v[1], v[2]) for k, v in spam_policy.KINDS.items()],
            'max_lists': spam_policy.MAX_PROVIDERS,
            'apply_tone': tone,
            'apply_word': word,
            'built_in': BUILT_IN,
        },
    )


@login_required
@require_perm(PermissionCode.SECURITY_MANAGE)
@require_POST
def spam_set_sensitivity(request: HttpRequest) -> HttpResponseRedirect:
    def change() -> str:
        value = spam_policy.set_level(request.POST.get('level', ''), _actor(request))
        return _('Sensitivity set to %(level)s. Rspamd picks it up within a few seconds.') % {
            'level': value
        }

    return _guarded(request, change)


@login_required
@require_perm(PermissionCode.SECURITY_MANAGE)
@require_POST
def spam_add_provider(request: HttpRequest) -> HttpResponseRedirect:
    def change() -> str:
        added = spam_policy.add_provider(
            request.POST.get('host', ''), request.POST.get('kind', ''), _actor(request)
        )
        return _('%(host)s added. Use Test to see that it answers.') % {'host': added.host}

    return _guarded(request, change)


@login_required
@require_perm(PermissionCode.SECURITY_MANAGE)
@require_POST
def spam_remove_provider(request: HttpRequest) -> HttpResponseRedirect:
    def change() -> str:
        host = request.POST.get('host', '')
        spam_policy.remove_provider(host, _actor(request))
        return _('%(host)s removed.') % {'host': host}

    return _guarded(request, change)


@login_required
@require_perm(PermissionCode.SECURITY_MANAGE)
@require_POST
def spam_toggle_provider(request: HttpRequest) -> HttpResponseRedirect:
    def change() -> str:
        host = request.POST.get('host', '')
        enabled = request.POST.get('enabled') == 'on'
        spam_policy.set_provider_enabled(host, enabled, _actor(request))
        return (_('%(host)s is on.') if enabled else _('%(host)s is off.')) % {'host': host}

    return _guarded(request, change)


@login_required
@require_perm(PermissionCode.SECURITY_MANAGE)
@require_POST
def spam_test_provider(request: HttpRequest) -> HttpResponseRedirect:
    def change() -> str:
        host = request.POST.get('host', '')
        result = spam_policy.test_provider(host)
        return f'{host}: {result["detail"]} ({result["ms"]} ms)'

    return _guarded(request, change)
