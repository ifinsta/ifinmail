"""The mail app's contributions to the plugin layer: the capability contract and its adapter.

**Capabilities** (``CAPABILITIES`` below) are the contract plugins write to. They say what the
administrator wants in plain units (MB, days, yes/no, address lists) and never name Postfix,
Dovecot or Rspamd, so plugins keep working if an engine is replaced.

**Adapter targets** are the engine side, the only code here that knows the software. Each is a
``key = value`` file on the runtime volume, applied by a watcher in the container that owns the
software, which re-validates every key and value, checks the resulting configuration before
reloading, and acknowledges what it applied:

* ``postfix.main``          main.cf parameters                  -> postfix (sync-overrides.sh)
* ``postfix.tls_policy``    per-domain outbound TLS             -> postfix (sync-overrides.sh)
* ``postfix.sender_policy`` internal-only logins                -> postfix (sync-overrides.sh)
* ``rspamd.policy``         filtering, limits, ARC              -> rspamd  (sync-plugins.sh)
* ``dovecot.policy``        mailbox retention, Sieve, quota     -> dovecot (sync-plugins.sh)

Replacing an engine means new targets and new ``target=`` bindings; the capabilities stay.

Setting type ``mailbox``: an email address that must be an existing mailbox on this server.

Registered from ``MailConfig.ready()``; core never imports this module.
"""

from __future__ import annotations

import re

from backend.apps.core.plugins.services import registry
from backend.apps.core.plugins.services.registry import (
    AdapterTarget,
    Capability,
    CapabilityField,
    TargetKey,
)

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


_SENDER_RE = re.compile(
    r'^(?:[a-z0-9._%+-]{1,64}@)?[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$'
)


def _sender_list(value: str) -> str | None:
    """Addresses and/or domains (a domain covers every address in it)."""
    items = value.split(',')
    if len(items) > MAX_LIST_ITEMS:
        return f'at most {MAX_LIST_ITEMS} entries'
    bad = [i for i in items if not _SENDER_RE.match(i)]
    return f'not an address or domain: {bad[0]}' if bad else None


def _address_list(value: str) -> str | None:
    items = value.split(',')
    if len(items) > MAX_LIST_ITEMS:
        return f'at most {MAX_LIST_ITEMS} addresses'
    bad = [i for i in items if '@' not in i or not _SENDER_RE.match(i)]
    return f'not an email address: {bad[0]}' if bad else None


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


class PostfixMainTarget(AdapterTarget):
    key = 'postfix.main'
    service = 'postfix'
    keys = {
        'always_bcc': TargetKey(
            _single_address, 'Send a copy of every message, inbound and outbound, to this address.'
        ),
        'message_size_limit_mb': TargetKey(
            # Rspamd refuses to scan (and so to DKIM-sign) messages over its 50 MiB max_message,
            # and Postfix would then pass them on unscanned: the two limits must agree.
            _int_between(1, 50),
            'Largest message accepted or sent, in MB (attachments included).',
        ),
    }
    runtime_file = 'postfix-plugins.conf'
    ack_file = 'postfix-plugins.applied'


class PostfixTlsPolicyTarget(AdapterTarget):
    key = 'postfix.tls_policy'
    service = 'postfix'
    keys = {
        'domains': TargetKey(
            _domain_list,
            'Destination domains that must be reached over TLS.',
            _normalize_domains,
        ),
        'level': TargetKey(
            _one_of('encrypt', 'secure'),
            'encrypt: TLS required; secure: TLS required and the certificate must be valid.',
        ),
    }
    runtime_file = 'postfix-tls-policy.conf'
    ack_file = 'postfix-tls-policy.applied'


class PostfixSenderPolicyTarget(AdapterTarget):
    key = 'postfix.sender_policy'
    service = 'postfix'
    keys = {
        'internal_only_logins': TargetKey(
            _address_list,
            'These logins may only send to domains hosted on this server.',
            _normalize_domains,
        ),
    }
    runtime_file = 'postfix-sender-policy.conf'
    ack_file = 'postfix-sender-policy.applied'


class RspamdPolicyTarget(AdapterTarget):
    key = 'rspamd.policy'
    service = 'rspamd'
    keys = {
        'blocked_attachment_types': TargetKey(
            _extension_list,
            'Messages with an attachment of these types (by name or by detected content).',
            _normalize_extensions,
        ),
        'blocked_attachment_action': TargetKey(
            _one_of('reject', 'quarantine'),
            'reject: refuse the message; quarantine: deliver it to Junk.',
        ),
        'dmarc_enforcement': TargetKey(
            _one_of('enforce', 'quarantine'),
            "Act on senders' DMARC policies (enforce: reject and quarantine as published).",
        ),
        'arc_trusted_sealers': TargetKey(
            _domain_list,
            'Forwarders whose valid ARC chain lifts a DMARC rejection '
            '(they vouch for the original).',
            _normalize_domains,
        ),
        'sender_block_list': TargetKey(
            _sender_list,
            'Mail from these addresses or domains (envelope or From header) is refused.',
            _normalize_domains,
        ),
        'sender_allow_list': TargetKey(
            _sender_list,
            'Never marked as spam or greylisted, but only when SPF or DKIM proves the sender; '
            'attachment and malware checks still apply.',
            _normalize_domains,
        ),
        'greylisting': TargetKey(
            _one_of('on', 'off'),
            'Ask suspicious first-time senders to retry later (Rspamd greylisting).',
        ),
        'send_limit_per_minute': TargetKey(
            _int_between(1, 1000), 'Messages one login may send per minute (burst).'
        ),
        'send_limit_per_day': TargetKey(
            _int_between(1, 100000), 'Messages one login may send per day.'
        ),
        'arc_sealing': TargetKey(
            _one_of('yes', 'no'),
            "Add an ARC seal, signed with the domain's DKIM key, to mail passing through.",
        ),
    }
    runtime_file = 'rspamd-plugins.conf'
    ack_file = 'rspamd-plugins.applied'


class DovecotPolicyTarget(AdapterTarget):
    key = 'dovecot.policy'
    service = 'dovecot'
    keys = {
        'max_redirects': TargetKey(
            _int_between(0, 20),
            'How many addresses a mail filter rule may forward a message to (0 = none).',
        ),
        'autoexpunge_trash_days': TargetKey(
            _int_between(1, 3650), 'Delete messages in Trash after this many days.'
        ),
        'autoexpunge_junk_days': TargetKey(
            _int_between(1, 3650), 'Delete messages in Junk after this many days.'
        ),
        'autoexpunge_sent_days': TargetKey(
            _int_between(1, 3650), 'Delete messages in Sent after this many days.'
        ),
        'quota_warnings': TargetKey(
            _one_of('yes', 'no'),
            'Put a notice in the Inbox when a mailbox reaches 80% and 95% of its quota.',
        ),
    }
    runtime_file = 'dovecot-plugins.conf'
    ack_file = 'dovecot-plugins.applied'


# ------------------------------------------------------------------------------ capabilities

_YES_NO = _one_of('yes', 'no')


def _field(
    target: tuple[str, str],
    description: str,
    validator=None,
    normalize=None,
    translate=None,
) -> CapabilityField:
    """A contract field. Without its own validator it uses the grammar of the key it is bound to."""
    targets = {t.key: t for t in TARGETS}
    spec = targets[target[0]].keys[target[1]]
    return CapabilityField(
        validator=validator or spec.validator,
        description=description,
        target=target,
        normalize=normalize if normalize is not None else spec.normalize,
        translate=translate,
    )


class _Capability(Capability):
    def __init__(
        self, key: str, title: str, description: str, fields: dict[str, CapabilityField]
    ) -> None:
        self.key, self.title, self.description, self.fields = key, title, description, fields


TARGETS: tuple[AdapterTarget, ...] = (
    PostfixMainTarget(),
    PostfixTlsPolicyTarget(),
    PostfixSenderPolicyTarget(),
    RspamdPolicyTarget(),
    DovecotPolicyTarget(),
)

MAIN, TLS, SENDER = 'postfix.main', 'postfix.tls_policy', 'postfix.sender_policy'
FILTER, MAILBOX = 'rspamd.policy', 'dovecot.policy'


def _capabilities() -> tuple[Capability, ...]:
    return (
        _Capability(
            'mail.journal',
            'Mail journal',
            'A copy of every message, inbound and outbound.',
            {
                'archive_address': _field(
                    (MAIN, 'always_bcc'), 'Address that receives a copy of every message.'
                )
            },
        ),
        _Capability(
            'mail.limits',
            'Message limits',
            'Limits on single messages.',
            {
                'max_message_mb': _field(
                    (MAIN, 'message_size_limit_mb'),
                    'Largest message accepted or sent, in MB (attachments included, 1-50).',
                )
            },
        ),
        _Capability(
            'delivery.require_tls',
            'Encrypted delivery to partners',
            'Mail to these domains is never sent without encryption.',
            {
                'domains': _field((TLS, 'domains'), 'Destination domains that must get TLS.'),
                'verify_certificate': _field(
                    (TLS, 'level'),
                    'yes: the receiving server must also present a valid certificate.',
                    validator=_YES_NO,
                    normalize=None,
                    translate=lambda v: 'secure' if v == 'yes' else 'encrypt',
                ),
            },
        ),
        _Capability(
            'sending.internal_only',
            'Internal-only mailboxes',
            'Mailboxes that may send only inside the organisation.',
            {
                'mailboxes': _field(
                    (SENDER, 'internal_only_logins'),
                    'These mailboxes may only send to domains hosted on this server.',
                )
            },
        ),
        _Capability(
            'sending.rate_limit',
            'Sending limits',
            'How much one mailbox may send, so a stolen password cannot send a flood.',
            {
                'per_minute': _field(
                    (FILTER, 'send_limit_per_minute'), 'Messages one mailbox may send per minute.'
                ),
                'per_day': _field(
                    (FILTER, 'send_limit_per_day'), 'Messages one mailbox may send per day.'
                ),
            },
        ),
        _Capability(
            'inbound.senders',
            'Blocked and allowed senders',
            'Senders refused, and senders never treated as spam.',
            {
                'block': _field(
                    (FILTER, 'sender_block_list'),
                    'Mail from these addresses or domains (envelope or From header) is refused.',
                ),
                'allow': _field(
                    (FILTER, 'sender_allow_list'),
                    'Never treated as spam or delayed, but only when SPF or DKIM proves the '
                    'sender; attachment and malware checks still apply.',
                ),
            },
        ),
        _Capability(
            'inbound.attachments',
            'Attachment blocking',
            'Attachments of dangerous types, detected by name and by content.',
            {
                'block_types': _field(
                    (FILTER, 'blocked_attachment_types'), 'File types (extensions) to block.'
                ),
                'action': _field(
                    (FILTER, 'blocked_attachment_action'),
                    'reject: refuse the message; quarantine: deliver it to Junk.',
                ),
            },
        ),
        _Capability(
            'inbound.authentication',
            'Sender authentication',
            "Acting on senders' published anti-forgery policies.",
            {
                'dmarc': _field(
                    (FILTER, 'dmarc_enforcement'),
                    "enforce: reject or quarantine as the sender's DMARC policy says; "
                    'quarantine: send failures to Junk; off: failures only count towards the '
                    'spam score.',
                    validator=_one_of('enforce', 'quarantine', 'off'),
                    translate=lambda v: '' if v == 'off' else v,
                )
            },
        ),
        _Capability(
            'inbound.greylisting',
            'Greylisting',
            'Asking suspicious first-time senders to try again a few minutes later.',
            {
                'enabled': _field(
                    (FILTER, 'greylisting'),
                    'yes: suspicious first-time senders are delayed; no: never delay mail.',
                    validator=_YES_NO,
                    translate=lambda v: 'on' if v == 'yes' else 'off',
                )
            },
        ),
        _Capability(
            'forwarding.arc',
            'Trusted forwarding (ARC)',
            'Keeping forwarded and list mail deliverable when senders enforce DMARC.',
            {
                'trusted_forwarders': _field(
                    (FILTER, 'arc_trusted_sealers'),
                    'Forwarders whose valid ARC chain lifts a DMARC rejection.',
                ),
                'seal': _field(
                    (FILTER, 'arc_sealing'),
                    "yes: seal mail this server forwards, with the domain's DKIM key.",
                ),
            },
        ),
        _Capability(
            'mailbox.retention',
            'Mailbox retention',
            'Deleting old messages from special folders.',
            {
                'trash_days': _field(
                    (MAILBOX, 'autoexpunge_trash_days'),
                    'Delete messages in Trash after this many days.',
                ),
                'junk_days': _field(
                    (MAILBOX, 'autoexpunge_junk_days'),
                    'Delete messages in Junk after this many days.',
                ),
                'sent_days': _field(
                    (MAILBOX, 'autoexpunge_sent_days'),
                    'Delete messages in Sent after this many days.',
                ),
            },
        ),
        _Capability(
            'mailbox.forwarding',
            'Forwarding by mail filters',
            "Users' own filter rules that forward messages elsewhere.",
            {
                'max_redirects': _field(
                    (MAILBOX, 'max_redirects'),
                    'How many addresses one filter rule may forward a message to (0 = none).',
                )
            },
        ),
        _Capability(
            'mailbox.quota_warnings',
            'Quota warnings',
            'Telling users before their mailbox is full.',
            {
                'enabled': _field(
                    (MAILBOX, 'quota_warnings'),
                    'yes: a notice in the Inbox at 80% and 95% of the quota.',
                )
            },
        ),
    )


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
    for target in TARGETS:
        registry.register_target(target)
    for capability in _capabilities():
        registry.register_capability(capability)
    registry.register_setting_type('mailbox', 'email', _existing_mailbox)
