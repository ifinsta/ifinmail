"""Detectors for the mail ports: password guessing, open-relay probing, address harvesting.

Pure functions over ``MailEvent`` lists, like ``rules``. The mail ports have no second factor, so
a guessed mailbox password is the whole breach: that is why a sign-in that succeeds right after a
spray from the same network is critical. A single mistyped client is not an attack, so one account
failing repeatedly stays a medium finding ("look at that client"), while many accounts from one
network, or a very high volume, is high.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .rules import _RATE, _block, is_internal
from .types import Action, Finding, MailEvent, Severity

_PASSWORDS = Action(
    'Check the mailbox passwords',
    'users',
    'The mail ports have no second factor: make sure the accounts named have strong, unique '
    'passwords and reset any that are weak.',
)
_CLIENT = Action(
    'Check the mail client',
    'users',
    'One account failing again and again is usually a phone or program with an old password.',
)


@dataclass(frozen=True)
class MailThresholds:
    failures: int = 10  # failed mail sign-ins from one network (a Dovecot line counts its attempts)
    high_failures: int = 60  # volume that is serious whatever the accounts
    spray_accounts: int = 4  # different accounts tried from one network
    relay_probes: int = 3
    relay_flood: int = 100
    unknown_recipients: int = 25
    distributed_networks: int = 15  # networks that each failed at least three times
    distributed_failures: int = 60
    breach_accounts: int = 3  # accounts tried from a network before one of them signed in
    breach_failures: int = 20


MAIL_DEFAULTS = MailThresholds()


def analyze(events: list[MailEvent], t: MailThresholds = MAIL_DEFAULTS) -> list[Finding]:
    external = [e for e in events if not is_internal(e.net)]
    found: list[Finding] = []
    found += _guessing(external, t)
    found += _relay(external, t)
    found += _harvest(external, t)
    found += _distributed(external, t)
    found += _breach(external, t)
    found.sort(key=lambda f: (-int(f.severity), -f.count, f.key))
    return found


def failures(events: list[MailEvent]) -> int:
    """Failed mail sign-ins, counting the attempts a single Dovecot line reports."""
    return sum(e.weight for e in events if e.kind == 'auth_failed')


def _by_net(events: list[MailEvent], kind: str) -> dict[str, list[MailEvent]]:
    grouped: dict[str, list[MailEvent]] = defaultdict(list)
    for event in events:
        if event.kind == kind and event.net:
            grouped[event.net].append(event)
    return grouped


def _guessing(events: list[MailEvent], t: MailThresholds) -> list[Finding]:
    found: list[Finding] = []
    for net, items in _by_net(events, 'auth_failed').items():
        total = failures(items)
        if total < t.failures:
            continue
        accounts = {e.who.lower() for e in items if e.who}
        spray = len(accounts) >= t.spray_accounts
        severity = Severity.HIGH if spray or total >= t.high_failures else Severity.MEDIUM
        who = (
            f'across {len(accounts)} different accounts (password spraying)'
            if spray
            else f'for {len(accounts)} account(s)'
            if accounts
            else 'against the mail ports'
        )
        found.append(
            Finding(
                key=f'mail_login_guessing:{net}',
                kind='mail_login_guessing',
                severity=severity,
                subject=net,
                title='Password guessing against the mail ports',
                summary=(
                    f'{total} failed mail sign-ins from {net} {who}. Mail accounts have no '
                    'second factor, so a guessed password is a breach.'
                    if severity >= Severity.HIGH
                    else f'{total} failed mail sign-ins from {net} {who}. One account failing '
                    'repeatedly is usually a client with an old password rather than an attack.'
                ),
                count=total,
                first_seen=items[0].at,
                last_seen=items[-1].at,
                samples=sorted(accounts)[:5],
                tighten=[_block(net), _RATE, _PASSWORDS if severity >= Severity.HIGH else _CLIENT],
            )
        )
    return found


def _relay(events: list[MailEvent], t: MailThresholds) -> list[Finding]:
    found: list[Finding] = []
    for net, items in _by_net(events, 'relay_denied').items():
        if len(items) < t.relay_probes:
            continue
        found.append(
            Finding(
                key=f'mail_relay_probe:{net}',
                kind='mail_relay_probe',
                severity=Severity.HIGH if len(items) >= t.relay_flood else Severity.MEDIUM,
                subject=net,
                title='Someone is testing whether the server relays mail for strangers',
                summary=(
                    f'{net} tried {len(items)} times to send mail to other domains through this '
                    'server without signing in. Every attempt was refused: nothing was relayed.'
                ),
                count=len(items),
                first_seen=items[0].at,
                last_seen=items[-1].at,
                tighten=[_block(net)],
            )
        )
    return found


def _harvest(events: list[MailEvent], t: MailThresholds) -> list[Finding]:
    found: list[Finding] = []
    for net, items in _by_net(events, 'unknown_recipient').items():
        if len(items) < t.unknown_recipients:
            continue
        found.append(
            Finding(
                key=f'mail_recipient_guessing:{net}',
                kind='mail_recipient_guessing',
                severity=Severity.MEDIUM,
                subject=net,
                title='Someone is guessing which mailboxes exist',
                summary=(
                    f'{net} sent to {len(items)} addresses that do not exist here. Each was '
                    'refused; the list of real addresses is what it is after.'
                ),
                count=len(items),
                first_seen=items[0].at,
                last_seen=items[-1].at,
                tighten=[_block(net), _RATE],
            )
        )
    return found


def _distributed(events: list[MailEvent], t: MailThresholds) -> list[Finding]:
    by_net = _by_net(events, 'auth_failed')
    heavy = {net: items for net, items in by_net.items() if failures(items) >= 3}
    total = sum(failures(items) for items in heavy.values())
    if len(heavy) < t.distributed_networks or total < t.distributed_failures:
        return []
    every = [e for items in heavy.values() for e in items]
    every.sort(key=lambda e: e.at)
    return [
        Finding(
            key='mail_distributed_guessing:all',
            kind='mail_distributed_guessing',
            severity=Severity.HIGH,
            subject='many networks',
            title='Password guessing against the mail ports from many networks at once',
            summary=(
                f'{total} failed mail sign-ins from {len(heavy)} networks. Blocking one network '
                'will not help; make sure mailbox passwords are strong and lower the rates.'
            ),
            count=total,
            first_seen=every[0].at,
            last_seen=every[-1].at,
            tighten=[_PASSWORDS, _RATE],
        )
    ]


def _breach(events: list[MailEvent], t: MailThresholds) -> list[Finding]:
    """A mailbox sign-in from a network that was spraying passwords a moment ago."""
    found: list[Finding] = []
    seen: dict[str, list[MailEvent]] = defaultdict(list)
    for event in sorted(events, key=lambda e: e.at):
        if event.kind == 'auth_failed' and event.net:
            seen[event.net].append(event)
            continue
        if event.kind != 'login_success' or not event.net or not event.who:
            continue
        before = seen.get(event.net, [])
        accounts = {e.who.lower() for e in before if e.who}
        if len(accounts) < t.breach_accounts and failures(before) < t.breach_failures:
            continue
        found.append(
            Finding(
                key=f'mail_success_after_failures:{event.who.lower()}:{event.net}',
                kind='mail_success_after_failures',
                severity=Severity.CRITICAL,
                subject=event.who,
                title='A mailbox signed in from a network that was guessing passwords',
                summary=(
                    f'{event.who} signed in from {event.net} after {failures(before)} failed '
                    f'attempts from it across {len(accounts)} account(s). If that was not the '
                    'owner, the password has been guessed: reset it now.'
                ),
                count=failures(before),
                first_seen=before[0].at,
                last_seen=event.at,
                tighten=[
                    Action(
                        'Reset the password and review the mailbox',
                        'users',
                        'Set a new password, end its sessions, and check forwarding rules and '
                        'recent sent mail.',
                    ),
                    _block(event.net),
                ],
            )
        )
    return found
