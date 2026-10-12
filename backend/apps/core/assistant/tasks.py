"""Assistant background jobs: answering questions, and the 30-day retention."""

from __future__ import annotations

from celery import shared_task

from backend.apps.core.assistant.services import ConversationService, agent


@shared_task(name='assistant.run', soft_time_limit=600, time_limit=660)
def run(conversation_id: str) -> None:
    agent.run(conversation_id)


@shared_task(name='assistant.purge')
def purge() -> int:
    return ConversationService.purge()
