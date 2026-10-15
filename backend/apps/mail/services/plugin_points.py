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


MAX_PAUSED = 1000  # containment must not fail open when many mailboxes are paused at once


def _paused_list(value: str) -> str | None:
    items = value.split(',')
    if len(items) > MAX_PAUSED:
        return f'at most {MAX_PAUSED} addresses'
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


_SCORE_RE = re.compile(r'^(?:[1-9][0-9]?(?:\.[0-9])?|0\.[5-9])$')
MAX_DNS_LISTS = 20
_DNS_LIST_KINDS = ('dnsbl', 'dnswl', 'uribl')


def _score(value: str) -> str | None:
    return None if _SCORE_RE.match(value) else 'must be a number from 0.5 to 99.9'


def _dns_lists(value: str) -> str | None:
    """``host/kind`` items: a DNS name and what the list is (sender, link or allow list)."""
    items = value.split(',')
    if len(items) > MAX_DNS_LISTS:
        return f'at most {MAX_DNS_LISTS} DNS lists'
    for item in items:
        host, _, kind = item.rpartition('/')
        if kind not in _DNS_LIST_KINDS or not _DOMAIN_RE.match(host) or host[-1:].isdigit():
            return f'not a DNS list (name/{"|".join(_DNS_LIST_KINDS)}): {item}'
    return None


def _one_domain(value: str) -> str | None:
    return None if _DOMAIN_RE.match(value) else 'must be one domain name'


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
        'recipient_limit': TargetKey(
            _int_between(1, 1000),
            'Most recipients one message from a logged-in user may have (submission ports).',
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
        'blocked_destinations': TargetKey(
            _sender_list,
            'Logged-in users cannot send to these addresses or domains (and their subdomains).',
            _normalize_domains,
        ),
        # Not a plugin setting: filled from live state (containment), see the dynamic source.
        'paused_logins': TargetKey(
            _paused_list,
            'Logins whose sending is paused until an administrator resumes it (containment).',
            _normalize_domains,
        ),
    }
    runtime_file = 'postfix-sender-policy.conf'
    ack_file = 'postfix-sender-policy.applied'


class ContainmentTarget(AdapterTarget):
    """Read by the console's own containment job; no file, nothing for a container to apply."""

    key = 'console.containment'
    service = 'api'
    in_process = True
    keys = {
        'action': TargetKey(
            _one_of('off', 'notify', 'pause'), 'What to do when a mailbox crosses a threshold.'
        ),
        'max_messages': TargetKey(_int_between(1, 100000), 'Messages in an hour.'),
        'max_recipients': TargetKey(_int_between(1, 1000000), 'Distinct recipients in an hour.'),
        'max_domains': TargetKey(_int_between(1, 100000), 'Distinct recipient domains in an hour.'),
        'notify': TargetKey(
            _address_list, 'Addresses told besides the administrators.', _normalize_domains
        ),
    }


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
        # Not plugin settings: filled from the console's Spam Filtering page (spam_policy), see
        # the dynamic source. All four are written together or not at all.
        'spam_greylist_score': TargetKey(_score, 'Score at which a sender is asked to retry.'),
        'spam_junk_score': TargetKey(_score, 'Score at which a message goes to Junk.'),
        'spam_rewrite_score': TargetKey(
            _score, 'Score at which the subject is also marked as spam.'
        ),
        'spam_reject_score': TargetKey(_score, 'Score at which a message is refused.'),
        'dnsbl_providers': TargetKey(
            _dns_lists,
            'Extra DNS lists asked about every message, as name/kind (dnsbl, uribl or dnswl).',
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


class DeveloperTarget(AdapterTarget):
    """The developer and agent features the console runs itself (sandbox, events, agent inboxes,
    webhooks, approvals, compliance, the agent gateway). No file, nothing for a container to
    apply: each feature reads its values with ``InstallationService.capability_values``."""

    key = 'console.developer'
    service = 'api'
    in_process = True
    keys = {
        'sandbox_enabled': TargetKey(_one_of('yes', 'no'), 'Capture mail from sandbox keys.'),
        'sandbox_retention_days': TargetKey(
            _int_between(1, 90), 'Days a captured message is kept.'
        ),
        'sandbox_max_messages': TargetKey(
            _int_between(10, 10000), 'Captured messages kept per key (the oldest go first).'
        ),
        'events_enabled': TargetKey(_one_of('yes', 'no'), 'Send delivery events to webhooks.'),
        'events_allow_http': TargetKey(_one_of('yes', 'no'), 'Allow plain http webhooks.'),
        'events_allow_private': TargetKey(
            _one_of('yes', 'no'), 'Allow webhooks on private networks.'
        ),
        'events_max_attempts': TargetKey(_int_between(1, 8), 'Attempts per event.'),
        'inboxes_enabled': TargetKey(_one_of('yes', 'no'), 'Let API keys create agent inboxes.'),
        'inboxes_domain': TargetKey(_one_domain, 'The hosted domain agent inboxes are created on.'),
        'inboxes_max_per_key': TargetKey(_int_between(1, 1000), 'Inboxes one key may hold.'),
        'inboxes_ttl_hours': TargetKey(
            _int_between(0, 8760), 'Hours an inbox lives unless asked otherwise (0: kept).'
        ),
        'inboxes_quota_mb': TargetKey(_int_between(1, 1024), 'Size of each agent inbox in MB.'),
        'inbox_events_enabled': TargetKey(
            _one_of('yes', 'no'), 'Send received mail of watched mailboxes to webhooks.'
        ),
        'inbox_events_body': TargetKey(_one_of('yes', 'no'), 'Include the message text and HTML.'),
        'inbox_events_allow_http': TargetKey(_one_of('yes', 'no'), 'Allow plain http webhooks.'),
        'inbox_events_allow_private': TargetKey(
            _one_of('yes', 'no'), 'Allow webhooks on private networks.'
        ),
        'shield_enabled': TargetKey(
            _one_of('yes', 'no'), 'Score mail for prompt injection before agents read it.'
        ),
        'shield_action': TargetKey(
            _one_of('flag', 'hold'), 'flag: report the risk; hold: keep high-risk mail from agents.'
        ),
    }


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
    ContainmentTarget(),
    DeveloperTarget(),
)

MAIN, TLS, SENDER = 'postfix.main', 'postfix.tls_policy', 'postfix.sender_policy'
FILTER, MAILBOX = 'rspamd.policy', 'dovecot.policy'
CONTAIN = 'console.containment'
DEV = 'console.developer'


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
            'sending.recipient_limits',
            'Recipients per message',
            'Limits how many people one message may be sent to, so one mistake or one stolen '
            'password cannot reach thousands at once.',
            {
                'per_message': _field(
                    (MAIN, 'recipient_limit'),
                    'Most recipients (To, Cc and Bcc together) of one message, 1-1000.',
                )
            },
        ),
        _Capability(
            'sending.blocked_destinations',
            'Blocked destinations',
            'Addresses and domains your people must not send to.',
            {
                'domains': _field(
                    (SENDER, 'blocked_destinations'),
                    'Addresses or domains (including their subdomains) that are refused.',
                )
            },
        ),
        _Capability(
            'sending.containment',
            'Containment of suspected compromise',
            'Notices a mailbox sending far more than usual and stops it until someone checks.',
            {
                'action': _field(
                    (CONTAIN, 'action'),
                    'off: nothing; notify: tell administrators; pause: also stop that '
                    "mailbox's sending until an administrator resumes it.",
                ),
                'max_messages': _field(
                    (CONTAIN, 'max_messages'), 'Messages one mailbox may send in an hour.'
                ),
                'max_recipients': _field(
                    (CONTAIN, 'max_recipients'),
                    'Different recipients one mailbox may write to in an hour.',
                ),
                'max_domains': _field(
                    (CONTAIN, 'max_domains'),
                    'Different recipient domains one mailbox may write to in an hour.',
                ),
                'notify': _field(
                    (CONTAIN, 'notify'), 'Addresses to tell besides the administrators.'
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
            'developer.sandbox',
            'Developer sandbox',
            'Mail from keys marked "sandbox" is checked like real mail, then kept for inspection '
            'and never delivered.',
            {
                'enabled': _field((DEV, 'sandbox_enabled'), 'yes: capture sandbox mail.'),
                'retention_days': _field(
                    (DEV, 'sandbox_retention_days'), 'Days a captured message is kept.'
                ),
                'max_messages': _field(
                    (DEV, 'sandbox_max_messages'), 'Captured messages kept per key.'
                ),
            },
        ),
        _Capability(
            'developer.events',
            'Delivery events',
            'What became of each message sent through the API (queued, delivered, deferred, '
            'bounced), sent to webhooks as signed JSON.',
            {
                'enabled': _field((DEV, 'events_enabled'), 'yes: send delivery events.'),
                'allow_http': _field(
                    (DEV, 'events_allow_http'), 'yes: allow plain http webhook addresses.'
                ),
                'allow_private': _field(
                    (DEV, 'events_allow_private'),
                    'yes: allow webhooks on private networks (10.x, 172.16-31.x, 192.168.x).',
                ),
                'max_attempts': _field(
                    (DEV, 'events_max_attempts'), 'Attempts before an event is given up.'
                ),
            },
        ),
        _Capability(
            'developer.agent_inboxes',
            'Agent inboxes',
            'API keys create mailboxes for AI agents in one call, read them back (with the '
            'one-time code or sign-in link already found) and let them expire.',
            {
                'enabled': _field((DEV, 'inboxes_enabled'), 'yes: keys may create agent inboxes.'),
                'domain': _field(
                    (DEV, 'inboxes_domain'),
                    'A hosted domain for agent inboxes (a subdomain such as agents.example.com '
                    'keeps them apart from people).',
                    normalize=lambda v: v.strip().lower().rstrip('.'),
                ),
                'max_per_key': _field((DEV, 'inboxes_max_per_key'), 'Inboxes one key may hold.'),
                'default_ttl_hours': _field(
                    (DEV, 'inboxes_ttl_hours'),
                    'Hours an inbox lives unless the key asks otherwise (0: kept until deleted).',
                ),
                'quota_mb': _field((DEV, 'inboxes_quota_mb'), 'Size of each inbox in MB.'),
            },
        ),
        _Capability(
            'developer.inbox_webhooks',
            'Inbox webhooks',
            'Mail that arrives in a watched mailbox is sent to a webhook as signed JSON, with the '
            'one-time code or sign-in link already found.',
            {
                'enabled': _field((DEV, 'inbox_events_enabled'), 'yes: send received mail.'),
                'include_body': _field(
                    (DEV, 'inbox_events_body'),
                    'yes: the event carries the text and HTML (up to 64 KB each); no: only the '
                    'sender, subject, snippet, attachment names and the code or link.',
                ),
                'allow_http': _field(
                    (DEV, 'inbox_events_allow_http'), 'yes: allow plain http webhook addresses.'
                ),
                'allow_private': _field(
                    (DEV, 'inbox_events_allow_private'), 'yes: allow webhooks on private networks.'
                ),
            },
        ),
        _Capability(
            'developer.injection_shield',
            'Injection shield',
            'Mail read by agents is checked for hidden or planted instructions first; agents get '
            'a risk score, the reasons and the text a person would see.',
            {
                'enabled': _field((DEV, 'shield_enabled'), 'yes: check mail agents read.'),
                'action': _field(
                    (DEV, 'shield_action'),
                    'flag: report the risk with each message; hold: also keep high-risk mail '
                    'from agents (no code extracted, skipped by wait, body left out of events).',
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


def _paused_senders() -> dict[str, dict[str, str]]:
    from backend.apps.mail.services import containment

    return {SENDER: {'paused_logins': ','.join(sorted(containment.paused()))}}


def _spam_policy() -> dict[str, dict[str, str]]:
    from backend.apps.mail.services import spam_policy

    return spam_policy.rspamd_values()


def register() -> None:
    for target in TARGETS:
        registry.register_target(target)
    for capability in _capabilities():
        registry.register_capability(capability)
    registry.register_setting_type('mailbox', 'email', _existing_mailbox)
    registry.register_dynamic_source('paused-senders', _paused_senders)
    registry.register_dynamic_source('spam-policy', _spam_policy)
