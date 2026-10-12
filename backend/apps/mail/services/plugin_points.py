"""The mail app's contributions to the plugin layer.

* Extension point ``postfix.main``: Postfix main.cf parameters, written to ``postfix-plugins.conf``
  and applied by the postfix container's watcher (sync-overrides.sh), which re-validates every key
  and value and acknowledges what it applied.
* Setting type ``mailbox``: an email address that must be an existing mailbox on this server.

Registered from ``MailConfig.ready()``; core never imports this module.
"""

from __future__ import annotations

import re

from backend.apps.core.plugins.services import registry
from backend.apps.core.plugins.services.registry import ExtensionPoint, PointKey

# One address, no whitespace, nothing Postfix would read as a list or lookup table.
_ADDRESS_RE = re.compile(
    r'^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$'
)


def _single_address(value: str) -> str | None:
    return None if _ADDRESS_RE.match(value) else 'must be one email address'


class PostfixMainPoint(ExtensionPoint):
    key = 'postfix.main'
    title = 'Postfix (main.cf)'
    description = 'Postfix parameters, applied by the postfix container within about 10 seconds.'
    keys = {
        'always_bcc': PointKey(
            _single_address, 'Send a copy of every message, inbound and outbound, to this address.'
        ),
    }
    runtime_file = 'postfix-plugins.conf'
    ack_file = 'postfix-plugins.applied'


def _existing_mailbox(address: str) -> str | None:
    from backend.apps.mail.services.mailboxes import MailboxService
    from backend.apps.mail.types.provisioning import MailboxError

    try:
        return (
            None if MailboxService.exists(address) else f'{address} is not a mailbox on this server'
        )
    except MailboxError as exc:
        return str(exc)


def register() -> None:
    registry.register_point(PostfixMainPoint())
    registry.register_setting_type('mailbox', 'email', _existing_mailbox)
