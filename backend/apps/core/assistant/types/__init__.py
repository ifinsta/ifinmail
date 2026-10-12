"""Assistant types: states, roles, tool tiers, limits and errors."""

from __future__ import annotations

from enum import StrEnum

CAPABILITY = 'assistant.model'
MAX_STEPS = 8  # model calls per question
CALL_TIMEOUT_SECONDS = 60
CONNECT_TIMEOUT_SECONDS = 10
RETENTION_DAYS = 30
MAX_QUESTION_CHARS = 2000
MAX_TOOL_OUTPUT_CHARS = 12000
HISTORY_MESSAGES = 40  # earlier turns sent back to the model, newest last
STALE_RUN_SECONDS = 600  # a run older than this no longer blocks a new question


class ConversationStatus(StrEnum):
    IDLE = 'idle'
    RUNNING = 'running'
    FAILED = 'failed'


class MessageRole(StrEnum):
    USER = 'user'
    ASSISTANT = 'assistant'
    TOOL = 'tool'


class ToolTier(StrEnum):
    READ = 'read'  # reads state through the console's services
    PROPOSE = 'propose'  # drafts a change; a person applies it


class AssistantError(Exception):
    """Base error; the message is safe to show to an administrator."""


class NotConfiguredError(AssistantError):
    """No model endpoint is set in the Assistant plugin."""


class BudgetExceededError(AssistantError):
    """Today's token budget is used up."""


class ProviderError(AssistantError):
    """The model endpoint refused, failed or answered with something unusable."""


class BusyError(AssistantError):
    """A question of this user is still being answered."""
