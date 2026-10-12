"""Assistant persistence: conversations and their messages (kept RETENTION_DAYS days).

All reads and writes go through ``backend.apps.core.assistant.services``.
"""

from __future__ import annotations

from django.db import models

from backend.apps.core.assistant.types import ConversationStatus, MessageRole
from backend.apps.core.base.models.base import CoreModel


class AssistantConversation(CoreModel):
    user = models.CharField(max_length=255, db_index=True)  # the administrator's address
    title = models.CharField(max_length=120)
    status = models.CharField(
        max_length=16,
        choices=[(s.value, s.value) for s in ConversationStatus],
        default=ConversationStatus.IDLE,
    )
    error = models.TextField(blank=True, default='')
    tokens_used = models.PositiveIntegerField(default=0)
    # Where the model was reached for the last answer (shown under "What was sent").
    provider_host = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        db_table = 'assistant_conversation'
        ordering = ['-updated_at']

    def __str__(self) -> str:
        return f'{self.user}: {self.title}'


class AssistantMessage(CoreModel):
    conversation = models.ForeignKey(
        AssistantConversation, on_delete=models.CASCADE, related_name='messages'
    )
    position = models.PositiveIntegerField()
    role = models.CharField(max_length=16, choices=[(r.value, r.value) for r in MessageRole])
    content = models.TextField(blank=True, default='')
    # assistant: the tool calls it asked for; tool: the call it answers and what was sent back.
    tool_calls = models.JSONField(default=list, blank=True)
    tool_call_id = models.CharField(max_length=120, blank=True, default='')
    tool_name = models.CharField(max_length=80, blank=True, default='')
    tool_arguments = models.JSONField(default=dict, blank=True)
    # A drafted change (propose tier): {plugin_id, settings, changes, error}; applied by a person.
    proposal = models.JSONField(null=True, blank=True)
    proposal_applied_by = models.CharField(max_length=255, blank=True, default='')
    proposal_applied_at = models.DateTimeField(null=True, blank=True)
    tokens = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'assistant_message'
        ordering = ['conversation', 'position']
        constraints = [
            models.UniqueConstraint(
                fields=['conversation', 'position'], name='assistant_message_position_unique'
            )
        ]
        indexes = [models.Index(fields=['created_at'], name='assistant_msg_created_idx')]

    def __str__(self) -> str:
        return f'{self.conversation_id} #{self.position} {self.role}'
