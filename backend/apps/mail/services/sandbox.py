"""Developer sandbox: mail from a sandbox API key is captured, never delivered.

A sandbox key goes through every check a real send does (allowed senders, the domain, the
Outbound policy) so a test proves the real call would work; then the message is stored here
instead of being handed to the relay. Nothing about it reaches the containment counters or the
sender's quotas, and nothing can make it leave the server: when the Developer sandbox plugin is
off, a sandbox key's send is refused rather than delivered.

Captured messages are kept for the plugin's number of days and capped per key (the oldest go
first); ``purge`` runs daily.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from backend.apps.core.plugins.services import InstallationService
from backend.apps.mail.models import SandboxMessage

CAPABILITY = 'developer.sandbox'
DEFAULT_RETENTION_DAYS = 7
DEFAULT_MAX_MESSAGES = 500


@dataclass(frozen=True)
class SandboxSettings:
    enabled: bool
    retention_days: int
    max_messages: int


def settings() -> SandboxSettings:
    values = InstallationService.capability_values(CAPABILITY)

    def number(name: str, default: int) -> int:
        try:
            return int(values.get(name) or default)
        except ValueError:
            return default

    return SandboxSettings(
        enabled=values.get('enabled') == 'yes',
        retention_days=number('retention_days', DEFAULT_RETENTION_DAYS),
        max_messages=number('max_messages', DEFAULT_MAX_MESSAGES),
    )


@transaction.atomic
def capture(
    *,
    key_prefix: str,
    key_name: str,
    message_id: str,
    sender: str,
    to: list[str],
    cc: list[str],
    bcc: list[str],
    reply_to: str,
    subject: str,
    text: str,
    html: str,
    keep: int,
) -> SandboxMessage:
    row = SandboxMessage.objects.create(
        key_prefix=key_prefix,
        key_name=key_name[:64],
        message_id=message_id,
        sender=sender,
        to=to,
        cc=cc,
        bcc=bcc,
        reply_to=reply_to or '',
        subject=subject[:998],
        text=text,
        html=html,
    )
    surplus = SandboxMessage.objects.filter(key_prefix=key_prefix).order_by('-created_at')[keep:]
    SandboxMessage.objects.filter(pk__in=list(surplus.values_list('pk', flat=True))).delete()
    return row


def messages_for(key_prefix: str, *, to: str | None = None) -> list[SandboxMessage]:
    """A key's captured messages, newest first; ``to`` matches any recipient (a key keeps at most
    a few thousand, so filtering in Python is fine and works on every database)."""
    rows = list(SandboxMessage.objects.filter(key_prefix=key_prefix))
    if to:
        wanted = to.strip().lower()
        rows = [r for r in rows if wanted in r.recipients]
    return rows


def get_for(key_prefix: str, message_uuid: str) -> SandboxMessage | None:
    try:
        return SandboxMessage.objects.filter(key_prefix=key_prefix, pk=message_uuid).first()
    except (ValueError, TypeError):
        return None


def clear(key_prefix: str) -> int:
    deleted, _ = SandboxMessage.objects.filter(key_prefix=key_prefix).delete()
    return deleted


def purge(now=None) -> int:  # noqa: ANN001
    """Drop what is older than the retention (run daily)."""
    days = settings().retention_days
    cutoff = (now or timezone.now()) - timedelta(days=days)
    deleted, _ = SandboxMessage.objects.filter(created_at__lt=cutoff).delete()
    return deleted
