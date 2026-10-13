"""Detectors: turn a window of requests and sign-in outcomes into findings.

Pure functions over the types in ``types.py``. Each finding has a stable key (so the same
scanner is the same finding on every run), a severity, a plain-language summary, a few
correlation ids as evidence, and the places in the console where it can be tightened.

The thresholds are deliberately modest: a single stray ``/.env`` request is background noise
(everything on the internet gets one), a network that asks for ten of them is a finding.
"""

from __future__ import annotations

import ipaddress
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from .classify import clean, is_raw_protocol, is_scanner_agent, probe_class
from .types import Access, Action, AuthEvent, Finding, Severity, WindowSummary

REJECTED = (400, 403, 404, 405, 444)


@dataclass(frozen=True)
class Thresholds:
    probe_hits: int = 3  # requests for known probe paths from one network
    distinct_rejected: int = 12  # different rejected paths from one network
    probe_flood: int = 100  # probes from one network that make a sweep serious by volume
    flood_per_minute: int = 240  # one network, one minute (4 requests a second)
    flood_total: int = 3000  # one network, the whole window
    global_peak_per_minute: int = 1200  # everyone together
    distributed_networks: int = 20  # networks each sending >= 10 a minute at the peak
    error_count: int = 10  # 5xx answers
    error_share: float = 0.10
    login_failures: int = 5  # from one network
    spray_accounts: int = 4  # different accounts tried from one network
    distributed_networks_per_account: int = 4  # one account, many networks
    key_guesses: int = 5  # unknown key ids from one network
    key_secret_failures: int = 3  # wrong secret for a key that exists
    mfa_failures: int = 5
    success_after_failures: int = 3  # failures from the same network before a success


DEFAULTS = Thresholds()

_BLOCK = Action(
    'Block the network',
    'network',
    'Check it is not an address you use yourself first.',
)
_RATE = Action(
    'Lower the connection rate caps',
    'network',
    'Network & entry points: cap new connections per address per minute.',
)
_MFA = Action(
    'Require two-factor sign-in',
    'security',
    'Security: set MFA enforcement to required so a guessed password is not enough.',
)
_KEYS = Action(
    'Restrict or rotate the key',
    'api_keys',
    'Give it an allowed-networks list, or rotate it if it may have leaked.',
)
_SESSIONS = Action(
    'Review sessions and reset the password',
    'users',
    'End the account’s sessions, set a new password and check its recent activity.',
)
_HEALTH = Action('Check server health', 'health', 'See which service is failing and why.')


def _block(net: str) -> Action:
    return Action(_BLOCK.label, _BLOCK.where, f'Add {net} under Blocked networks. {_BLOCK.detail}')


_INTERNAL = tuple(
    ipaddress.ip_network(n)
    for n in (
        '10.0.0.0/8',
        '172.16.0.0/12',
        '192.168.0.0/16',
        '127.0.0.0/8',
        '169.254.0.0/16',
        '::1/128',
        'fc00::/7',
        'fe80::/10',
    )
)


# Findings whose subject is a network that the console can block.
NETWORK_KINDS = frozenset({'probe_sweep', 'request_flood', 'login_guessing', 'api_key_guessing'})


def is_internal(net: str) -> bool:
    """A client on the server's own side (LAN, loopback, link-local), not a stranger.

    Documentation and reserved ranges are *not* internal: they are what test traffic looks like,
    and treating a stranger as internal would hide a real scanner.
    """
    try:
        network = ipaddress.ip_network(net, strict=False)
    except ValueError:
        return False
    return any(
        network.version == n.version
        and network.network_address in n
        and network.broadcast_address in n
        for n in _INTERNAL
    )


def _status_class(code: int) -> str:
    return f'{code // 100}xx' if 100 <= code < 600 else 'other'


def _ids(requests: Iterable[Access], limit: int = 5) -> list[str]:
    seen: list[str] = []
    for request in requests:
        if request.cid and request.cid not in seen:
            seen.append(request.cid)
        if len(seen) >= limit:
            break
    return seen


def summarise(
    requests: list[Access],
    auth: list[AuthEvent],
    start: datetime,
    end: datetime,
    skipped_bytes: int = 0,
) -> WindowSummary:
    """Counts and classes only: what is kept once the individual requests are discarded."""
    summary = WindowSummary(start=start, end=end, skipped_bytes=skipped_bytes)
    summary.requests = len(requests)
    summary.clients = len({r.net for r in requests})
    by_status = Counter(_status_class(r.status) for r in requests)
    summary.by_status = dict(sorted(by_status.items()))
    classes: Counter[str] = Counter()
    minutes: Counter[str] = Counter()
    by_net: dict[str, list[Access]] = defaultdict(list)
    for request in requests:
        by_net[request.net].append(request)
        minutes[request.at.strftime('%Y%m%d%H%M')] += 1
        if is_raw_protocol(request.method, request.path):
            classes['raw_protocol'] += 1
            continue
        found = probe_class(request.path, request.query)
        if found is not None:
            classes[found.name] += 1
        elif request.status in REJECTED:
            classes['rejected_other'] += 1
        else:
            classes['normal'] += 1
    summary.by_class = dict(classes.most_common())
    summary.peak_per_minute = max(minutes.values(), default=0)
    summary.server_errors = by_status.get('5xx', 0)
    summary.auth_failures = sum(
        1 for e in auth if e.kind in ('login_failed', 'api_auth_failed', 'mfa_failed')
    )
    top = sorted(by_net.items(), key=lambda item: len(item[1]), reverse=True)[:5]
    summary.top_networks = [
        {
            'network': net,
            'requests': len(items),
            'probes': sum(1 for r in items if probe_class(r.path, r.query) is not None),
            'rejected': sum(1 for r in items if r.status in REJECTED),
        }
        for net, items in top
    ]
    return summary


def analyze(
    requests: list[Access], auth: list[AuthEvent], now: datetime, t: Thresholds = DEFAULTS
) -> list[Finding]:
    findings: list[Finding] = []
    findings += _probing(requests, t)
    findings += _exposed(requests)
    findings += _floods(requests, t)
    findings += _errors(requests, t)
    findings += _guessing(auth, t, now)
    findings += _compromise(auth, t)
    findings += _api_keys(auth, t)
    findings += _mfa(auth, t)
    findings.sort(key=lambda f: (-int(f.severity), -f.count, f.key))
    return findings


# -- requests ----------------------------------------------------------------------------------


def _probing(requests: list[Access], t: Thresholds) -> list[Finding]:
    by_net: dict[str, list[Access]] = defaultdict(list)
    for request in requests:
        by_net[request.net].append(request)
    found: list[Finding] = []
    for net, items in by_net.items():
        probes = [r for r in items if probe_class(r.path, r.query) is not None]
        rejected = {r.path for r in items if r.status in REJECTED}
        scanner = any(is_scanner_agent(r.ua) for r in items)
        if not (
            len(probes) >= t.probe_hits
            or len(rejected) >= t.distinct_rejected
            or (scanner and len(items) >= 3)
        ):
            continue
        classes = Counter(c.name for r in probes if (c := probe_class(r.path, r.query)))
        # Refused probes are the background of every public server. A probe is serious when it
        # was *answered* (a page, or an error that the request provoked) or when it is a flood.
        answered = [r for r in probes if r.status < 300 or r.status >= 500]
        severity = Severity.HIGH if answered or len(probes) >= t.probe_flood else Severity.MEDIUM
        if is_internal(net):
            severity = Severity.LOW  # an internal client misbehaving is a different problem
        samples = [clean(p) for p, _ in Counter(r.path for r in probes or items).most_common(5)]
        listed = ', '.join(f'{n} x{c}' for n, c in classes.most_common(4)) or 'unknown paths'
        found.append(
            Finding(
                key=f'probe_sweep:{net}',
                kind='probe_sweep',
                severity=severity,
                subject=net,
                title='Scanner probing for files and admin pages',
                summary=(
                    f'{net} made {len(items)} requests, {len(probes)} of them for known probe '
                    f'paths ({listed}) and {len(rejected)} different paths that were refused.'
                    + (
                        f' {len(answered)} of the probes got an answer other than a refusal.'
                        if answered
                        else ' Every probe was refused.'
                    )
                    + (' It identified itself as a scanning tool.' if scanner else '')
                ),
                count=len(items),
                first_seen=items[0].at,
                last_seen=items[-1].at,
                evidence=_ids(probes or items),
                samples=samples,
                tighten=[] if is_internal(net) else [_block(net), _RATE],
            )
        )
    return found


def _exposed(requests: list[Access]) -> list[Finding]:
    """A probe for a sensitive file that was *answered*: that file is being served."""
    hits: dict[str, list[Access]] = defaultdict(list)
    for request in requests:
        found = probe_class(request.path, request.query)
        if found is not None and found.sensitive and request.status in (200, 206):
            hits[f'{found.name}:{clean(request.path, 60)}'].append(request)
    out: list[Finding] = []
    for subject, items in hits.items():
        name, _, path = subject.partition(':')
        out.append(
            Finding(
                key=f'exposed_path:{subject}',
                kind='exposed_path',
                severity=Severity.CRITICAL,
                subject=path,
                title='A sensitive file is being served',
                summary=(
                    f'{path} ({name}) was answered with 200 to {len(items)} request(s). Files of '
                    'this kind hold credentials or source code; treat anything in it as leaked.'
                ),
                count=len(items),
                first_seen=items[0].at,
                last_seen=items[-1].at,
                evidence=_ids(items),
                samples=[clean(path)],
                tighten=[
                    Action(
                        'Stop serving it and rotate what it holds',
                        '',
                        'Remove or block the path, then change every secret that was in it.',
                    )
                ],
            )
        )
    return out


def _floods(requests: list[Access], t: Thresholds) -> list[Finding]:
    per_net_minute: dict[str, Counter[str]] = defaultdict(Counter)
    per_minute: Counter[str] = Counter()
    for request in requests:
        stamp = request.at.strftime('%Y%m%d%H%M')
        per_net_minute[request.net][stamp] += 1
        per_minute[stamp] += 1
    found: list[Finding] = []
    for net, minutes in per_net_minute.items():
        peak, total = max(minutes.values()), sum(minutes.values())
        if peak < t.flood_per_minute and total < t.flood_total:
            continue
        items = [r for r in requests if r.net == net]
        found.append(
            Finding(
                key=f'request_flood:{net}',
                kind='request_flood',
                severity=Severity.HIGH if not is_internal(net) else Severity.LOW,
                subject=net,
                title='One network is sending requests far faster than a person',
                summary=(
                    f'{net} sent {total} requests, at most {peak} in a single minute '
                    f'({peak / 60:.1f} a second). That is enough to crowd out real visitors.'
                ),
                count=total,
                first_seen=items[0].at,
                last_seen=items[-1].at,
                evidence=_ids(items),
                samples=[clean(p) for p, _ in Counter(r.path for r in items).most_common(3)],
                tighten=[] if is_internal(net) else [_block(net), _RATE],
            )
        )
    peak = max(per_minute.values(), default=0)
    heavy = {net for net, minutes in per_net_minute.items() if max(minutes.values()) >= 10}
    if peak >= t.global_peak_per_minute and len(heavy) >= t.distributed_networks:
        found.append(
            Finding(
                key='distributed_flood:all',
                kind='distributed_flood',
                severity=Severity.CRITICAL,
                subject='many networks',
                title='Traffic from many networks at once, at a rate that can take the site down',
                summary=(
                    f'{peak} requests in one minute from {len(heavy)} networks that each sent '
                    'at least ten. Blocking one address will not help; lower the rates instead.'
                ),
                count=peak,
                first_seen=requests[0].at,
                last_seen=requests[-1].at,
                evidence=_ids(requests),
                tighten=[_RATE, _HEALTH],
            )
        )
    return found


def _errors(requests: list[Access], t: Thresholds) -> list[Finding]:
    errors = [r for r in requests if r.status >= 500]
    if len(errors) < t.error_count or len(errors) / max(len(requests), 1) < t.error_share:
        return []
    paths = Counter(clean(r.path, 60) for r in errors)
    return [
        Finding(
            key='server_errors:all',
            kind='server_errors',
            severity=Severity.HIGH,
            subject='the console',
            title='The server is answering with errors',
            summary=(
                f'{len(errors)} of {len(requests)} requests ended in a server error. Either the '
                'server is under pressure (see the other findings) or something is broken.'
            ),
            count=len(errors),
            first_seen=errors[0].at,
            last_seen=errors[-1].at,
            evidence=_ids(errors),
            samples=[p for p, _ in paths.most_common(5)],
            tighten=[_HEALTH],
        )
    ]


# -- sign-in outcomes --------------------------------------------------------------------------


def _guessing(auth: list[AuthEvent], t: Thresholds, now: datetime) -> list[Finding]:
    since = now - timedelta(hours=1)
    failed = [e for e in auth if e.kind == 'login_failed' and e.at >= since]
    found: list[Finding] = []
    by_net: dict[str, list[AuthEvent]] = defaultdict(list)
    by_who: dict[str, list[AuthEvent]] = defaultdict(list)
    for event in failed:
        if event.net:
            by_net[event.net].append(event)
        by_who[event.who.lower()].append(event)
    for net, items in by_net.items():
        if len(items) < t.login_failures:
            continue
        accounts = {e.who.lower() for e in items}
        spray = len(accounts) >= t.spray_accounts
        found.append(
            Finding(
                key=f'login_guessing:{net}',
                kind='login_guessing',
                severity=Severity.HIGH,
                subject=net,
                title='Password guessing against the console',
                summary=(
                    f'{len(items)} failed sign-ins from {net}'
                    + (
                        f' across {len(accounts)} different accounts (password spraying).'
                        if spray
                        else f' for {len(accounts)} account(s).'
                    )
                ),
                count=len(items),
                first_seen=items[0].at,
                last_seen=items[-1].at,
                tighten=[_block(net), _MFA],
            )
        )
    for who, items in by_who.items():
        networks = {e.net for e in items if e.net}
        if len(networks) < t.distributed_networks_per_account:
            continue
        found.append(
            Finding(
                key=f'account_attack:{who}',
                kind='account_attack',
                severity=Severity.HIGH,
                subject=who,
                title='One account is being attacked from many networks',
                summary=(
                    f'{len(items)} failed sign-ins for {who} from {len(networks)} networks. '
                    'Blocking one network will not stop it; make a guessed password useless.'
                ),
                count=len(items),
                first_seen=items[0].at,
                last_seen=items[-1].at,
                tighten=[_MFA, _SESSIONS],
            )
        )
    return found


def _compromise(auth: list[AuthEvent], t: Thresholds) -> list[Finding]:
    """A success from a network (or for an account) that was failing a moment ago."""
    found: list[Finding] = []
    failures_by_net: dict[str, list[AuthEvent]] = defaultdict(list)
    failures_by_who: dict[str, list[AuthEvent]] = defaultdict(list)
    for event in sorted(auth, key=lambda e: e.at):
        if event.kind == 'login_failed':
            if event.net:
                failures_by_net[event.net].append(event)
            failures_by_who[event.who.lower()].append(event)
            continue
        if event.kind != 'login_success':
            continue
        before_net = [f for f in failures_by_net.get(event.net, []) if f.at <= event.at]
        before_who = [
            f
            for f in failures_by_who.get(event.who.lower(), [])
            if f.at <= event.at and f.net != event.net
        ]
        if len(before_net) >= t.success_after_failures or len(before_who) >= t.login_failures:
            found.append(
                Finding(
                    key=f'success_after_failures:{event.who.lower()}:{event.net}',
                    kind='success_after_failures',
                    severity=Severity.CRITICAL,
                    subject=event.who,
                    title='A sign-in succeeded after repeated failures',
                    summary=(
                        f'{event.who} signed in from {event.net or "an unknown network"} after '
                        f'{len(before_net) or len(before_who)} failed attempts. If that was not '
                        'the account owner, the password has been guessed.'
                    ),
                    count=len(before_net) or len(before_who),
                    first_seen=(before_net or before_who)[0].at,
                    last_seen=event.at,
                    tighten=[_SESSIONS, _MFA],
                )
            )
    return found


def _api_keys(auth: list[AuthEvent], t: Thresholds) -> list[Finding]:
    found: list[Finding] = []
    unknown: dict[str, list[AuthEvent]] = defaultdict(list)
    wrong: dict[str, list[AuthEvent]] = defaultdict(list)
    for event in auth:
        if event.kind != 'api_auth_failed':
            continue
        if event.reason == 'unknown_key':
            unknown[event.net].append(event)
        elif event.reason == 'bad_secret':
            wrong[event.who].append(event)
    for net, items in unknown.items():
        if net and len(items) >= t.key_guesses:
            found.append(
                Finding(
                    key=f'api_key_guessing:{net}',
                    kind='api_key_guessing',
                    severity=Severity.MEDIUM,
                    subject=net,
                    title='Someone is trying API key identifiers that do not exist',
                    summary=(
                        f'{len(items)} requests from {net} used keys this server does not have.'
                    ),
                    count=len(items),
                    first_seen=items[0].at,
                    last_seen=items[-1].at,
                    tighten=[_block(net)],
                )
            )
    for who, items in wrong.items():
        if len(items) >= t.key_secret_failures:
            found.append(
                Finding(
                    key=f'api_key_targeted:{who}',
                    kind='api_key_targeted',
                    severity=Severity.HIGH,
                    subject=who,
                    title='A real API key is being attacked',
                    summary=(
                        f'{len(items)} calls presented the wrong secret for {who}. Whoever it is '
                        'knows the key identifier exists.'
                    ),
                    count=len(items),
                    first_seen=items[0].at,
                    last_seen=items[-1].at,
                    tighten=[_KEYS],
                )
            )
    return found


def _mfa(auth: list[AuthEvent], t: Thresholds) -> list[Finding]:
    failed: dict[str, list[AuthEvent]] = defaultdict(list)
    for event in auth:
        if event.kind == 'mfa_failed':
            failed[event.who.lower()].append(event)
    return [
        Finding(
            key=f'mfa_pressure:{who}',
            kind='mfa_pressure',
            severity=Severity.HIGH,
            subject=who,
            title='Second-factor codes are being guessed',
            summary=(
                f'{len(items)} wrong second-factor codes for {who}. The password was already '
                'right, so this is a person or a program that has it.'
            ),
            count=len(items),
            first_seen=items[0].at,
            last_seen=items[-1].at,
            tighten=[_SESSIONS],
        )
        for who, items in failed.items()
        if len(items) >= t.mfa_failures
    ]
