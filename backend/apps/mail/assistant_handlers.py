"""Assistant tools offered by the mail app: domains, mailboxes and aliases (no secrets)."""

from __future__ import annotations


def _mail_accounts(arguments: dict, context) -> dict:  # noqa: ANN001
    from backend.apps.mail.services.mailboxes import AliasService, MailboxService

    mailboxes = MailboxService.list_rows()
    return {
        'mailboxes': [
            {
                'address': m.address,
                'quota_mb': m.quota_bytes // 1048576 if m.quota_bytes else 'unlimited',
                'active': m.is_active,
                'admin': m.is_admin,
                'setup_pending': m.invite_pending,
            }
            for m in mailboxes
        ],
        'aliases': [
            {'alias': a.source, 'forwards_to': a.destination} for a in AliasService.list_rows()
        ],
        'page': 'Mailboxes / Aliases',
    }


def register() -> None:
    from backend.apps.core.assistant.services import tools
    from backend.apps.core.assistant.services.tools import Tool

    tools.register(
        Tool(
            'mail_accounts',
            'Mailboxes (address, quota, active, admin, setup pending) and aliases with where '
            'they forward. No passwords or message contents.',
            _mail_accounts,
        )
    )
