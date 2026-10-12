"""The administrator assistant page: ask, read answers with what was sent, apply drafted changes.

Everything goes through ``ConversationService``; answers are produced by the background worker,
so the page polls a small status endpoint while a question runs.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from backend.apps.core.assistant.services import ConversationService
from backend.apps.core.assistant.services import config as assistant_config
from backend.apps.core.assistant.types import AssistantError, ConversationStatus, MessageRole

from ..types.permissions import PermissionCode
from .auth import require_perm

_MANAGE = require_perm(PermissionCode.SYSTEM_MANAGE)


def _actor(request: HttpRequest) -> str:
    return request.user.email


def _turns(conversation) -> list[dict]:  # noqa: ANN001
    """Messages grouped for display: questions, answers, and the tool calls behind each answer."""
    turns: list[dict] = []
    current: dict | None = None
    for message in ConversationService.messages(conversation):
        if message.role == MessageRole.USER:
            current = {'question': message, 'steps': [], 'answers': [], 'proposals': []}
            turns.append(current)
            continue
        if current is None:
            continue
        if message.role == MessageRole.TOOL:
            current['steps'].append(message)
            if message.proposal:
                current['proposals'].append(message)
        elif message.content:
            current['answers'].append(message)
    return turns


def _page(request: HttpRequest, conversation=None) -> HttpResponse:  # noqa: ANN001
    settings = assistant_config.current()
    context = {
        'active_section': 'assistant',
        'configured': settings is not None,
        'model': settings.model if settings else '',
        'host': settings.host if settings else '',
        'usage': ConversationService.usage(),
        'conversations': ConversationService.list_for(_actor(request)),
        'conversation': conversation,
        'turns': _turns(conversation) if conversation else [],
        'running': bool(conversation and conversation.status == ConversationStatus.RUNNING),
        'prefill': request.GET.get('q', '')[:2000],
    }
    return render(request, 'admin/assistant.html', context)


@login_required
@_MANAGE
@require_GET
def assistant(request: HttpRequest) -> HttpResponse:
    return _page(request)


@login_required
@_MANAGE
@require_GET
def assistant_conversation(request: HttpRequest, conversation_id: str) -> HttpResponse:
    conversation = ConversationService.get(_actor(request), conversation_id)
    if conversation is None:
        raise Http404('No such conversation')
    return _page(request, conversation)


@login_required
@_MANAGE
@require_GET
def assistant_status(request: HttpRequest, conversation_id: str) -> JsonResponse:
    conversation = ConversationService.get(_actor(request), conversation_id)
    if conversation is None:
        raise Http404('No such conversation')
    return JsonResponse({'status': conversation.status})


@login_required
@_MANAGE
@require_POST
def assistant_ask(request: HttpRequest) -> HttpResponse:
    conversation_id = request.POST.get('conversation') or None
    try:
        conversation = ConversationService.ask(
            _actor(request), request.POST.get('question', ''), conversation_id
        )
    except AssistantError as exc:
        messages.error(request, str(exc))
        if conversation_id:
            return redirect('accounts:assistant_conversation', conversation_id=conversation_id)
        return redirect('accounts:assistant')
    return redirect('accounts:assistant_conversation', conversation_id=str(conversation.pk))


@login_required
@_MANAGE
@require_POST
def assistant_apply(request: HttpRequest, message_id: str) -> HttpResponse:
    back = request.POST.get('conversation', '')
    try:
        messages.success(request, ConversationService.apply_proposal(_actor(request), message_id))
    except AssistantError as exc:
        messages.error(request, str(exc))
    if back and ConversationService.get(_actor(request), back):
        return redirect('accounts:assistant_conversation', conversation_id=back)
    return redirect('accounts:assistant')


@login_required
@_MANAGE
@require_POST
def assistant_test(request: HttpRequest) -> HttpResponse:
    try:
        messages.success(request, ConversationService.test_connection())
    except AssistantError as exc:
        messages.error(request, f'Connection test failed: {exc}')
    return redirect('accounts:assistant')
