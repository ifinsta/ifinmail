"""Conversations: asking, reading, applying proposals, retention. The single interface for views."""

from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from backend.apps.core.assistant.models import AssistantConversation, AssistantMessage
from backend.apps.core.assistant.services import agent, config
from backend.apps.core.assistant.services.provider import OpenAICompatibleProvider, check_endpoint
from backend.apps.core.assistant.types import (
    MAX_QUESTION_CHARS,
    RETENTION_DAYS,
    STALE_RUN_SECONDS,
    AssistantError,
    BusyError,
    ConversationStatus,
    MessageRole,
    ProviderError,
)
from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.plugins.types import PluginError

_PING_TOOL = {
    'type': 'function',
    'function': {
        'name': 'ping',
        'description': 'Confirms the connection works. Call it when asked to.',
        'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
}


class ConversationService:
    @staticmethod
    def list_for(user: str, limit: int = 20) -> list[AssistantConversation]:
        return list(AssistantConversation.objects.filter(user=user)[:limit])

    @staticmethod
    def get(user: str, conversation_id: str) -> AssistantConversation | None:
        try:
            return AssistantConversation.objects.filter(pk=conversation_id, user=user).first()
        except (ValueError, TypeError, ValidationError):
            return None

    @staticmethod
    def messages(conversation: AssistantConversation) -> list[AssistantMessage]:
        return list(conversation.messages.order_by('position'))

    @staticmethod
    def _clean(question: str) -> str:
        text = (question or '').strip()
        if not text:
            raise AssistantError('Type a question first.')
        if len(text) > MAX_QUESTION_CHARS:
            raise AssistantError(f'Questions are limited to {MAX_QUESTION_CHARS} characters.')
        return text

    @staticmethod
    def _check_not_busy(user: str) -> None:
        stale = timezone.now() - timedelta(seconds=STALE_RUN_SECONDS)
        running = AssistantConversation.objects.filter(user=user, status=ConversationStatus.RUNNING)
        running.filter(updated_at__lt=stale).update(
            status=ConversationStatus.FAILED, error='This answer was interrupted. Ask again.'
        )
        if running.filter(updated_at__gte=stale).exists():
            raise BusyError('The previous question is still being answered.')

    @classmethod
    def ask(
        cls, user: str, question: str, conversation_id: str | None = None
    ) -> AssistantConversation:
        """Store the question and queue the answer. Starts a conversation when none is given."""
        text = cls._clean(question)
        config.require(with_key=False)
        with transaction.atomic():
            cls._check_not_busy(user)
            if conversation_id:
                conversation = cls.get(user, conversation_id)
                if conversation is None:
                    raise AssistantError('That conversation does not exist.')
            else:
                conversation = AssistantConversation.objects.create(user=user, title=text[:120])
            position = (conversation.messages.aggregate(p=Max('position'))['p'] or 0) + 1
            AssistantMessage.objects.create(
                conversation=conversation, position=position, role=MessageRole.USER, content=text
            )
            conversation.status, conversation.error = ConversationStatus.RUNNING, ''
            conversation.save(update_fields=['status', 'error', 'updated_at'])
            AuditService.record(
                'assistant_question', user=user, detail=f'conversation {conversation.pk}'
            )
            pk = str(conversation.pk)
            transaction.on_commit(lambda: _queue(pk))
        return conversation

    @staticmethod
    def apply_proposal(user: str, message_id: str) -> str:
        """Apply a drafted plugin change on the administrator's click. Returns a summary."""
        from backend.apps.core.plugins.services import InstallationService

        with transaction.atomic():
            try:
                message = (
                    AssistantMessage.objects.select_for_update()
                    .filter(pk=message_id, conversation__user=user)
                    .first()
                )
            except (ValueError, TypeError, ValidationError):
                message = None
            if message is None or not message.proposal:
                raise AssistantError('There is no proposal to apply.')
            if message.proposal_applied_at:
                raise AssistantError('This proposal was already applied.')
            proposal = message.proposal
            if proposal.get('error'):
                raise AssistantError('This draft did not validate, so it cannot be applied.')
            plugin_id, settings = proposal['plugin_id'], proposal['settings']
            ConversationService._check_matches_draft(proposal)
            try:
                if InstallationService.get(plugin_id) is None:
                    InstallationService.install(plugin_id, settings, user)
                    verb = 'installed'
                else:
                    InstallationService.configure(plugin_id, settings, user)
                    verb = 'updated'
            except PluginError as exc:
                raise AssistantError(f'Not applied: {exc}') from None
            message.proposal_applied_by = user
            message.proposal_applied_at = timezone.now()
            message.save(update_fields=['proposal_applied_by', 'proposal_applied_at', 'updated_at'])
        AuditService.record(
            'assistant_proposal_applied',
            user=user,
            detail=(
                f'{plugin_id} {verb} from assistant draft {message_id}: '
                f'{", ".join(sorted(settings))}'
            ),
        )
        return f'{proposal.get("plugin_name", plugin_id)} {verb}.'

    @staticmethod
    def _check_matches_draft(proposal: dict) -> None:
        """Refuse to apply anything other than what the administrator was shown."""
        from backend.apps.core.plugins.services import CatalogService, InstallationService
        from backend.apps.core.plugins.services import manifest as manifests
        from backend.apps.core.plugins.types import PluginError

        plugin_id = proposal['plugin_id']
        row = InstallationService.get(plugin_id)
        entry = CatalogService.get(plugin_id)
        if row is None and entry is None:
            raise AssistantError('That plugin is no longer available.')
        manifest = InstallationService.manifest_of(row) if row else entry.manifest
        current = dict(row.settings) if row else {}
        try:
            result = manifests.clean_settings(manifest, {**current, **proposal['settings']})
        except PluginError as exc:
            raise AssistantError(f'The draft no longer validates: {exc}') from None
        expected = proposal.get('expected', {})
        if any(result.get(key) != value for key, value in expected.items()):
            raise AssistantError(
                'Applying would not give the values shown in this draft (the plugin changed '
                'since). Nothing was changed; ask again for a fresh draft.'
            )

    @staticmethod
    def test_connection() -> str:
        """One tiny request that must come back as a tool call. Returns a success message."""
        settings = config.require(with_key=True)
        check_endpoint(settings.base_url)
        provider = OpenAICompatibleProvider(settings.base_url, settings.model, settings.api_key)
        result = provider.complete(
            [
                {'role': 'system', 'content': 'You test a connection. Call the ping tool.'},
                {'role': 'user', 'content': 'Call ping now.'},
            ],
            [_PING_TOOL],
        )
        if not any(call.name == 'ping' for call in result.tool_calls):
            raise ProviderError(
                f'{settings.model} at {provider.host} answered but did not call a tool. The '
                'assistant needs a model that supports tool (function) calling.'
            )
        return f'Connected: {settings.model} at {provider.host} answers and can use tools.'

    @staticmethod
    def purge(now=None) -> int:  # noqa: ANN001
        cutoff = (now or timezone.now()) - timedelta(days=RETENTION_DAYS)
        _, per_model = AssistantConversation.objects.filter(updated_at__lt=cutoff).delete()
        return per_model.get(AssistantConversation._meta.label, 0)

    @staticmethod
    def usage() -> dict[str, int]:
        settings = config.current()
        return {
            'today': agent.tokens_today(),
            'budget': settings.daily_tokens if settings else config.DEFAULT_DAILY_TOKENS,
        }


def _queue(conversation_id: str) -> None:
    from backend.apps.core.assistant.tasks import run

    run.delay(conversation_id)
