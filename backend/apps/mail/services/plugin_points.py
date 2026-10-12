"""The mail app's contributions to the plugin layer.

Extension points (each a ``key = value`` file on the runtime volume, applied by a watcher in the
container that owns the software, which re-validates every key and value, checks the resulting
configuration before reloading, and acknowledges what it applied):

* ``postfix.main``        Postfix main.cf parameters            -> postfix   (sync-overrides.sh)
* ``postfix.tls_policy``  per-domain outbound TLS requirements  -> postfix   (sync-overrides.sh)
* ``rspamd.policy``       attachment and DMARC enforcement      -> rspamd    (sync-plugins.sh)
* ``dovecot.policy``      forwarding limits, mailbox cleanup    -> dovecot   (sync-plugins.sh)

Setting type ``mailbox``: an email address that must be an existing mailbox on this server.

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


_EXTENSION_RE = re.compile(r'^[a-z0-9]{1,10}$')
_DOMAIN_RE = re.compile(
    r'^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$'
)
MAX_LIST_ITEMS = 200


def _tokens(value: str) -> list[str]:
    return [t for t in re.split(r'[\s,;]+', value.strip().lower()) if t]


def _normalize_extensions(value: str) -> str:
    """ "EXE, .js;iso" -> "exe,iso,js" (sorted, de-duplicated, dots dropped)."""
    return ','.join(sorted({t.lstrip('.') for t in _tokens(value)}))


def _normalize_domains(value: str) -> str:
    return ','.join(sorted({t.rstrip('.') for t in _tokens(value)}))


def _extension_list(value: str) -> str | None:
    items = value.split(',')
    if len(items) > MAX_LIST_ITEMS:
        return f'at most {MAX_LIST_ITEMS} file types'
    bad = [i for i in items if not _EXTENSION_RE.match(i)]
    return f'not a file extension: {bad[0]}' if bad else None


def _domain_list(value: str) -> str | None:
    items = value.split(',')
    if len(items) > MAX_LIST_ITEMS:
        return f'at most {MAX_LIST_ITEMS} domains'
    bad = [i for i in items if not _DOMAIN_RE.match(i)]
    return f'not a domain name: {bad[0]}' if bad else None


def _one_of(*options: str):
    def check(value: str) -> str | None:
        return None if value in options else f'must be one of: {", ".join(options)}'

    return check


def _int_between(low: int, high: int):
    def check(value: str) -> str | None:
        if not value.isdigit() or not low <= int(value) <= high:
            return f'must be a whole number from {low} to {high}'
        return None

    return check


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


class PostfixTlsPolicyPoint(ExtensionPoint):
    key = 'postfix.tls_policy'
    title = 'Postfix (outbound TLS policy)'
    description = 'Which destination domains must be reached over TLS, applied by Postfix.'
    keys = {
        'domains': PointKey(
            _domain_list,
            'Destination domains that must be reached over TLS.',
            _normalize_domains,
        ),
        'level': PointKey(
            _one_of('encrypt', 'secure'),
            'encrypt: TLS required; secure: TLS required and the certificate must be valid.',
        ),
    }
    runtime_file = 'postfix-tls-policy.conf'
    ack_file = 'postfix-tls-policy.applied'


class RspamdPolicyPoint(ExtensionPoint):
    key = 'rspamd.policy'
    title = 'Rspamd (message policy)'
    description = 'Filtering rules checked by Rspamd, which validates its configuration first.'
    keys = {
        'blocked_attachment_types': PointKey(
            _extension_list,
            'Messages with an attachment of these types (by name or by detected content).',
            _normalize_extensions,
        ),
        'blocked_attachment_action': PointKey(
            _one_of('reject', 'quarantine'),
            'reject: refuse the message; quarantine: deliver it to Junk.',
        ),
        'dmarc_enforcement': PointKey(
            _one_of('enforce', 'quarantine'),
            "Act on senders' DMARC policies (enforce: reject and quarantine as published).",
        ),
        'arc_trusted_sealers': PointKey(
            _domain_list,
            'Forwarders whose valid ARC chain lifts a DMARC rejection '
            '(they vouch for the original).',
            _normalize_domains,
        ),
        'arc_sealing': PointKey(
            _one_of('yes', 'no'),
            "Add an ARC seal, signed with the domain's DKIM key, to mail passing through.",
        ),
    }
    runtime_file = 'rspamd-plugins.conf'
    ack_file = 'rspamd-plugins.applied'


class DovecotPolicyPoint(ExtensionPoint):
    key = 'dovecot.policy'
    title = 'Dovecot (mailbox policy)'
    description = 'Mailbox rules applied by Dovecot, which checks its configuration first.'
    keys = {
        'max_redirects': PointKey(
            _int_between(0, 20),
            'How many addresses a mail filter rule may forward a message to (0 = none).',
        ),
        'autoexpunge_trash_days': PointKey(
            _int_between(1, 3650), 'Delete messages in Trash after this many days.'
        ),
        'autoexpunge_junk_days': PointKey(
            _int_between(1, 3650), 'Delete messages in Junk after this many days.'
        ),
        'autoexpunge_sent_days': PointKey(
            _int_between(1, 3650), 'Delete messages in Sent after this many days.'
        ),
    }
    runtime_file = 'dovecot-plugins.conf'
    ack_file = 'dovecot-plugins.applied'


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
    registry.register_point(PostfixTlsPolicyPoint())
    registry.register_point(RspamdPolicyPoint())
    registry.register_point(DovecotPolicyPoint())
    registry.register_setting_type('mailbox', 'email', _existing_mailbox)
