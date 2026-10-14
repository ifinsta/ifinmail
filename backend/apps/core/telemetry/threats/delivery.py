"""Delivery status: what happened to the mail this server sent, in words an owner can act on.

Postfix logs one status line per delivery attempt. This module turns those lines into counters per
hour (never an address list, a subject or a message): how many were accepted, how many are being
retried, how many failed for good, *why* (the receiving server's own words, classified), *where*
(destination domain and provider) and *who from* (the local sending mailbox).

What the numbers mean, and do not:

* ``sent`` is "the receiving server accepted it" (an SMTP 250). It is not "it reached the inbox":
  placement in Inbox or Spam is invisible from here.
* ``deferred`` counts *attempts*, not messages: a message that is retried four times is four
  deferrals and, in the end, one ``sent`` or one ``bounced``.
* The bounce rate is therefore ``bounced / (sent + bounced)``: final outcomes only.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .types import Action, Finding, MailEvent, Severity

# -- thresholds (industry practice: under 2% is healthy, over 5% is a problem) -------------------

WATCH_RATE = 2.0  # percent of final outcomes
ALERT_RATE = 5.0
MIN_FINAL = 20  # a rate over fewer messages than this is noise
PROVIDER_MIN_FAILURES = 5  # attempts that failed at one provider before it is a finding
PROVIDER_FAILURE_SHARE = 0.5
KEEP_DOMAINS = 15  # destination domains kept per hour
KEEP_SENDERS = 10


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    hint: str
    patterns: tuple[str, ...]
    reputation: bool = False  # a refusal that is about this server's standing, not the recipient


# Order matters: the first category whose pattern matches wins, so the specific ones come first.
CATEGORIES: tuple[Category, ...] = (
    Category(
        'reverse_dns',
        'Reverse DNS is missing or does not match',
        'Set the reverse DNS (PTR) of this server’s IP address to the mail hostname at your VPS '
        'provider; it cannot be set in your DNS host.',
        (r'\bptr\b', r'reverse dns', r'\brdns\b', r'iprev', r'fcrdns', r'reverse lookup'),
        True,
    ),
    Category(
        'authentication',
        'SPF, DKIM or DMARC did not pass at the receiver',
        'Open Domains & DNS and fix the failing check; send from an address on a domain this '
        'server signs.',
        (
            r'\bspf\b',
            r'\bdkim\b',
            r'\bdmarc\b',
            r'not authenticated',
            r'unauthenticated',
            r'authentication (?:required|failed|results)',
            r'5\.7\.2[346]',
        ),
        True,
    ),
    Category(
        'mailbox_full',
        'The recipient’s mailbox is full',
        'Nothing to fix on this server: the recipient has to free space.',
        (
            r'over quota',
            r'mailbox (?:is )?full',
            r'mailbox.*quota',
            r'quota exceeded for',
            r'storage (?:limit|quota)',
            r'\b[45]\.2\.2\b',
        ),
    ),
    Category(
        'too_large',
        'The message is larger than the receiver accepts',
        'Send a smaller message or a link to the file.',
        (r'too large', r'message size', r'size limit', r'\b5\.3\.4\b', r'exceeds (?:the )?size'),
    ),
    Category(
        'blocked',
        'Blocked for reputation or by a blocklist',
        'Check the blocklist status on System health, request removal from any list that names '
        'this IP, and send less until a track record builds.',
        (
            r'block ?list',
            r'blacklist',
            r'\bdnsbl\b',
            r'spamhaus',
            r'barracuda',
            r'spamcop',
            r'\blisted\b',
            r'reputation',
            r'banned',
            r'denied by policy',
            r'ip (?:has been )?blocked',
            r'blocked',
            r'access denied',
        ),
        True,
    ),
    Category(
        'rate_limited',
        'The receiver is rate-limiting this server',
        'Slow down and spread sending out. A new IP address earns volume gradually; do not '
        'retry in bursts.',
        (
            r'rate limit',
            r'too many (?:messages|connections|recipients|emails)',
            r'throttl',
            r'unusual rate',
            r'sending (?:quota|limit)',
            r'too fast',
            r'temporarily rate limited',
            r'4\.7\.\d+.*(?:rate|volume|limit)',
            r'try again later',
            r'temporarily deferred',
        ),
        True,
    ),
    Category(
        'greylisted',
        'Greylisted: asked to try again in a few minutes',
        'Normal and automatic. The message is retried and is usually delivered; nothing to do.',
        (r'grey ?list', r'please try again', r'retry (?:in|later)'),
    ),
    Category(
        'spam_content',
        'Rejected as spam or by content policy',
        'Review the message content, links and sending volume, and ask the recipient to check '
        'their junk folder and mark it as not spam.',
        (
            r'\bspam\b',
            r'content (?:reject|policy)',
            r'message (?:rejected|refused)',
            r'suspected',
            r'unsolicited',
            r'5\.7\.\d+.*(?:content|message)',
        ),
        True,
    ),
    Category(
        'tls',
        'Encrypted delivery (TLS) could not be agreed',
        'Usually the receiver’s certificate or protocol settings; it is retried, and mail is '
        'not sent unencrypted to a server that demands encryption.',
        (r'\btls\b', r'starttls', r'certificate', r'handshake', r'\bssl\b'),
    ),
    Category(
        'connection',
        'The receiving server could not be reached',
        'A network or DNS problem at either end, usually temporary. If every destination fails, '
        'check DNS and that outbound port 25 is open.',
        (
            r'connection (?:timed out|refused|reset)',
            r'timed out',
            r'no route',
            r'host not found',
            r'host or domain name not found',
            r'name service error',
            r'lost connection',
            r'network is unreachable',
            r'conversation with',
            r'unable to connect',
        ),
    ),
    Category(
        'unknown_recipient',
        'The address does not exist',
        'The address is wrong or retired: remove it from any list. A run of these in a row '
        'harms reputation.',
        (
            r'user unknown',
            r'no such user',
            r'unknown user',
            r'does not exist',
            r'recipient (?:address )?rejected',
            r'invalid (?:recipient|address)',
            r'\b5\.1\.[01]\b',
            r'mailbox unavailable',
            r'(?:user|recipient|address|mailbox) not found',
            r'no mailbox',
        ),
    ),
)
OTHER = Category(
    'other',
    'Another reason',
    'Open the example below: the receiving server explains itself in its own words.',
    (),
)
BY_KEY = {c.key: c for c in (*CATEGORIES, OTHER)}

_EMAIL = re.compile(r'<?[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}>?')
_IP = re.compile(
    r'\[?\b(?:\d{1,3}\.){3}\d{1,3}\b\]?(?::\d+)?|\[?(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}\]?'
)
_QUEUE_ID = re.compile(r'\b(?:queued as|id=)\s*[0-9A-Za-z]{6,}\b', re.I)
_SPACE = re.compile(r'\s+')
_UNPRINTABLE = re.compile(r'[^\x20-\x7e]')


def scrub(text: str, limit: int = 220) -> str:
    """The receiving server's words with addresses and IPs removed, bounded and printable."""
    text = _EMAIL.sub('<address>', text)
    text = _IP.sub('[ip]', text)
    text = _QUEUE_ID.sub('', text)
    text = _UNPRINTABLE.sub('?', text)
    return _SPACE.sub(' ', text).strip()[:limit]


def classify(dsn: str, reason: str) -> str:
    """The category key for one failure or deferral."""
    text = f'{dsn} {reason}'.lower()
    for category in CATEGORIES:
        if any(re.search(p, text) for p in category.patterns):
            return category.key
    return OTHER.key


# -- providers -----------------------------------------------------------------------------------

_PROVIDERS: dict[str, str] = {}
for _label, _names in {
    'Google': ('gmail.com', 'googlemail.com', 'google.com'),
    'Microsoft': (
        'outlook.com',
        'hotmail.com',
        'live.com',
        'msn.com',
        'office365.com',
        'outlook.de',
        'hotmail.co.uk',
        'hotmail.fr',
        'live.co.uk',
    ),
    'Yahoo': ('yahoo.com', 'ymail.com', 'aol.com', 'yahoo.co.uk', 'yahoo.fr', 'rocketmail.com'),
    'Apple': ('icloud.com', 'me.com', 'mac.com'),
    'Proton': ('proton.me', 'protonmail.com', 'pm.me'),
    'Zoho': ('zoho.com', 'zohomail.com'),
}.items():
    for _name in _names:
        _PROVIDERS[_name] = _label


def provider_of(domain: str) -> str:
    """The mailbox provider behind a destination domain (the domain itself when unknown)."""
    domain = (domain or '').lower().strip('.')
    if domain in _PROVIDERS:
        return _PROVIDERS[domain]
    for suffix, label in _PROVIDERS.items():
        if domain.endswith('.' + suffix):
            return label
    return domain or 'unknown'


# -- hourly counters -----------------------------------------------------------------------------


def _top(table: dict[str, list[int]], keep: int) -> dict[str, list[int]]:
    ranked = sorted(table.items(), key=lambda kv: (-sum(kv[1]), kv[0]))[:keep]
    return {k: v for k, v in ranked}


def aggregate(events: list[MailEvent]) -> dict[str, Any]:
    """The delivery counters for one window of Postfix events (see the module docstring)."""
    sender_of = {e.ref: e.sender for e in events if e.kind == 'received' and e.ref and e.sender}
    index = {'sent': 0, 'deferred': 1, 'bounced': 2}
    domains: dict[str, list[int]] = {}
    senders: dict[str, list[int]] = {}
    reasons: dict[str, Counter[str]] = {'deferred': Counter(), 'bounced': Counter()}
    examples: dict[str, str] = {}
    totals = {'sent': 0, 'deferred': 0, 'bounced': 0}
    local_failed = 0
    for event in events:
        if event.service != 'postfix' or event.kind not in ('sent', 'deferred', 'bounced'):
            continue
        if event.kind != 'sent' and not event.domain:
            local_failed += event.weight  # LMTP/local: delivery into one of our own mailboxes
            continue
        if not event.domain:
            continue
        totals[event.kind] += event.weight
        slot = index[event.kind]
        domains.setdefault(event.domain, [0, 0, 0])[slot] += event.weight
        sender = sender_of.get(event.ref, '')
        if sender:
            senders.setdefault(sender, [0, 0, 0])[slot] += event.weight
        if event.kind in reasons:
            category = classify(event.dsn, event.reason)
            reasons[event.kind][category] += event.weight
            if event.reason and category not in examples:
                examples[category] = event.reason
    return {
        **totals,
        'local_failed': local_failed,
        'reasons': {k: dict(v) for k, v in reasons.items()},
        'examples': examples,
        'domains': _top(domains, KEEP_DOMAINS),
        'senders': _top(senders, KEEP_SENDERS),
    }


def merge(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum the hourly ``delivery`` dicts found in digest summaries."""
    out: dict[str, Any] = {
        'sent': 0, 'deferred': 0, 'bounced': 0, 'local_failed': 0,
        'reasons': {'deferred': Counter(), 'bounced': Counter()},
        'examples': {}, 'domains': {}, 'senders': {}, 'hours_with_detail': 0,
    }  # fmt: skip
    for row in rows:
        data = ((row.get('sources') or {}).get('postfix') or {}).get('delivery')
        if not isinstance(data, dict):
            continue
        out['hours_with_detail'] += 1
        for key in ('sent', 'deferred', 'bounced', 'local_failed'):
            out[key] += int(data.get(key) or 0)
        for kind in ('deferred', 'bounced'):
            out['reasons'][kind].update(
                {k: int(v) for k, v in ((data.get('reasons') or {}).get(kind) or {}).items()}
            )
        for category, text in (data.get('examples') or {}).items():
            out['examples'].setdefault(category, text)
        for field in ('domains', 'senders'):
            for name, triple in (data.get(field) or {}).items():
                slot = out[field].setdefault(name, [0, 0, 0])
                for i in range(3):
                    slot[i] += int(triple[i])
    return out


# -- the report ----------------------------------------------------------------------------------


def _rate(bounced: int, sent: int) -> float | None:
    final = bounced + sent
    return round(100.0 * bounced / final, 1) if final else None


def _figures(merged: dict[str, Any]) -> dict[str, Any]:
    sent, deferred, bounced = merged['sent'], merged['deferred'], merged['bounced']
    return {
        'sent': sent,
        'deferred': deferred,
        'bounced': bounced,
        'final': sent + bounced,
        'bounce_rate': _rate(bounced, sent),
        'local_failed': merged['local_failed'],
    }


def _verdict(now: dict[str, Any]) -> dict[str, str]:
    final, rate = now['final'], now['bounce_rate']
    if final == 0 and now['deferred'] == 0:
        return {
            'tone': 'none',
            'headline': 'No outgoing mail in this period.',
            'next': 'Counts appear here as soon as this server sends mail on.',
        }
    if final >= MIN_FINAL and rate is not None and rate >= ALERT_RATE:
        return {
            'tone': 'bad',
            'headline': f'{rate}% of outgoing messages are bouncing.',
            'next': 'Read the reasons below: most failures have one cause that is quick to fix.',
        }
    if final >= MIN_FINAL and rate is not None and rate >= WATCH_RATE:
        return {
            'tone': 'watch',
            'headline': f'{rate}% of outgoing messages bounced: worth a look.',
            'next': 'Healthy senders stay under 2%. The reasons below say what to change.',
        }
    if now['bounced'] or now['deferred']:
        return {
            'tone': 'ok',
            'headline': 'Outgoing mail is being delivered.',
            'next': (
                f'{now["bounced"]} failed for good and {now["deferred"]} attempt(s) were '
                'retried; too few messages for a rate to mean much yet.'
                if final < MIN_FINAL
                else 'A few failures are normal; the reasons below say which.'
            ),
        }
    return {
        'tone': 'ok',
        'headline': 'Outgoing mail is being delivered.',
        'next': 'Every message was accepted by the receiving server.',
    }


def build(
    rows: list[dict[str, Any]], previous: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """The report's ``delivery`` section from digest summaries (this period, and the one before)."""
    merged = merge(rows)
    now = _figures(merged)
    before = _figures(merge(previous or []))
    failures = {
        cat: int(n)
        for kind in ('bounced', 'deferred')
        for cat, n in merged['reasons'][kind].items()
    }
    reasons = []
    for kind in ('bounced', 'deferred'):
        total = sum(merged['reasons'][kind].values()) or 1
        for cat, count in merged['reasons'][kind].most_common():
            spec = BY_KEY.get(cat, OTHER)
            reasons.append(
                {
                    'category': cat,
                    'kind': kind,
                    'label': spec.label,
                    'hint': spec.hint,
                    'count': int(count),
                    'share': round(100.0 * count / total),
                    'example': merged['examples'].get(cat, ''),
                    'reputation': spec.reputation,
                }
            )
    reasons.sort(key=lambda r: (r['kind'] != 'bounced', -r['count']))
    destinations = [
        {
            'domain': domain,
            'provider': provider_of(domain),
            'sent': s,
            'deferred': d,
            'bounced': b,
            'bounce_rate': _rate(b, s),
        }
        for domain, (s, d, b) in sorted(
            merged['domains'].items(), key=lambda kv: (-sum(kv[1]), kv[0])
        )[:8]
    ]
    providers: dict[str, list[int]] = {}
    for domain, (s, d, b) in merged['domains'].items():
        slot = providers.setdefault(provider_of(domain), [0, 0, 0])
        slot[0] += s
        slot[1] += d
        slot[2] += b
    senders = [
        {'address': a, 'sent': s, 'deferred': d, 'bounced': b, 'bounce_rate': _rate(b, s)}
        for a, (s, d, b) in sorted(merged['senders'].items(), key=lambda kv: (-sum(kv[1]), kv[0]))[
            :8
        ]
    ]
    change = None
    if before['final'] or before['deferred']:
        change = {
            'sent': now['sent'] - before['sent'],
            'bounced': now['bounced'] - before['bounced'],
            'deferred': now['deferred'] - before['deferred'],
            'bounce_rate_points': (
                round(now['bounce_rate'] - before['bounce_rate'], 1)
                if now['bounce_rate'] is not None and before['bounce_rate'] is not None
                else None
            ),
        }
    return {
        **now,
        'verdict': _verdict(now),
        'previous': before,
        'change': change,
        'reasons': reasons,
        'destinations': destinations,
        'providers': [
            {'provider': p, 'sent': s, 'deferred': d, 'bounced': b, 'bounce_rate': _rate(b, s)}
            for p, (s, d, b) in sorted(providers.items(), key=lambda kv: (-sum(kv[1]), kv[0]))[:6]
        ],
        'senders': senders,
        'detail': merged['hours_with_detail'] > 0,
        'failure_total': sum(failures.values()),
    }


def as_text(data: dict[str, Any]) -> list[str]:
    """Plain-text lines for the weekly email."""
    lines = [
        'DELIVERY (outgoing mail)',
        f'  {data["verdict"]["headline"]}',
        f'  accepted {data["sent"]}, failed for good {data["bounced"]}, '
        f'retried attempts {data["deferred"]}'
        + (f', bounce rate {data["bounce_rate"]}%' if data['bounce_rate'] is not None else ''),
    ]
    change = data.get('change')
    if change and change.get('bounce_rate_points') is not None:
        points = change['bounce_rate_points']
        lines.append(f'  against the previous period: bounce rate {points:+} points')
    for reason in data['reasons'][:3]:
        lines.append(f'  - {reason["count"]} {reason["kind"]}: {reason["label"]}')
    if data['reasons']:
        lines.append(f'    What to do: {data["reasons"][0]["hint"]}')
    return lines


# -- findings ------------------------------------------------------------------------------------


def findings(rows: list[dict[str, Any]], now: datetime) -> list[Finding]:
    """Problems an owner should hear about, from the last day's digests (and the current window)."""
    merged = merge(rows)
    figures = _figures(merged)
    out: list[Finding] = []
    report_action = Action(
        'Open the delivery report', 'report', 'Reasons, destinations and senders for the period.'
    )
    health_action = Action(
        'Check server health', 'health', 'Reverse DNS, blocklists and DNS records.'
    )
    final, rate = figures['final'], figures['bounce_rate']
    if final >= MIN_FINAL and rate is not None and rate >= WATCH_RATE:
        top = merged['reasons']['bounced'].most_common(1)
        spec = BY_KEY[top[0][0]] if top else OTHER
        severity = Severity.HIGH if rate >= ALERT_RATE else Severity.MEDIUM
        out.append(
            Finding(
                key='delivery_bounce_rate:all',
                kind='delivery_bounce_rate',
                severity=severity,
                subject='outgoing mail',
                title='Many outgoing messages are bouncing',
                summary=(
                    f'{rate}% of the {final} outgoing messages in the last day failed for good '
                    f'(healthy senders stay under {WATCH_RATE:g}%). '
                    + (f'Most common reason: {spec.label.lower()}. {spec.hint}' if top else '')
                ),
                count=figures['bounced'],
                first_seen=now,
                last_seen=now,
                samples=[merged['examples'][top[0][0]]]
                if top and top[0][0] in merged['examples']
                else [],
                tighten=[report_action, health_action],
            )
        )
    providers: dict[str, list[int]] = {}
    for domain, (s, d, b) in merged['domains'].items():
        slot = providers.setdefault(provider_of(domain), [0, 0, 0])
        slot[0] += s
        slot[1] += d
        slot[2] += b
    reputation_categories = {c.key for c in CATEGORIES if c.reputation}
    for provider, (sent, deferred, bounced) in providers.items():
        failures = deferred + bounced
        attempts = sent + failures
        if failures < PROVIDER_MIN_FAILURES or failures / attempts < PROVIDER_FAILURE_SHARE:
            continue
        # Whether the refusals are about us (reputation, authentication, rate) or about the
        # recipients (no such address, full mailbox) cannot be split per provider from here;
        # the overall mix decides how loud this is.
        reasons = merged['reasons']['bounced'] + merged['reasons']['deferred']
        about_us = sum(n for cat, n in reasons.items() if cat in reputation_categories)
        severity = Severity.HIGH if about_us >= PROVIDER_MIN_FAILURES else Severity.MEDIUM
        top = reasons.most_common(1)
        spec = BY_KEY[top[0][0]] if top else OTHER
        out.append(
            Finding(
                key=f'delivery_provider:{provider.lower()}',
                kind='delivery_provider',
                severity=severity,
                subject=provider,
                title=f'{provider} is refusing or delaying your mail',
                summary=(
                    f'{failures} of {attempts} delivery attempts to {provider} failed or were '
                    f'deferred in the last day. Most common reason: {spec.label.lower()}. '
                    f'{spec.hint}'
                ),
                count=failures,
                first_seen=now,
                last_seen=now,
                samples=[merged['examples'][top[0][0]]]
                if top and top[0][0] in merged['examples']
                else [],
                tighten=[report_action, health_action],
            )
        )
    return out
