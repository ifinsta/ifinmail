"""Plain data the threat digest passes around: what was seen, and what it adds up to.

Nothing here touches the database or the network, so every detector can be tested with a list of
literals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum


class Severity(IntEnum):
    """Ordered so that ``max()`` and comparisons mean what they say."""

    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @property
    def word(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class Access:
    """One request as nginx logged it."""

    at: datetime
    ip: str
    net: str  # /24 for IPv4, /48 for IPv6: what a firewall rule would name
    method: str
    path: str  # without the query string
    query: str
    status: int
    host: str
    ua: str
    cid: str  # the request id the console also records (X-Correlation-ID)
    seconds: float


@dataclass(frozen=True)
class AuthEvent:
    """One authentication outcome from the audit trail."""

    at: datetime
    kind: str  # login_failed | login_success | api_auth_failed | mfa_failed | stepup_failed
    who: str  # account address, or the public key id for API keys
    net: str  # '' when the record carries no address
    reason: str  # for api_auth_failed: unknown_key | bad_secret | ...


@dataclass(frozen=True)
class Action:
    """Where to tighten: a console page (``where`` is a URL name) and what to do there."""

    label: str
    where: str = ''
    detail: str = ''


@dataclass
class Finding:
    key: str  # stable across runs: "<kind>:<subject>"
    kind: str
    severity: Severity
    subject: str  # a network, a key id or an account: never message content
    title: str
    summary: str
    count: int
    first_seen: datetime
    last_seen: datetime
    evidence: list[str] = field(default_factory=list)  # correlation ids, newest first
    samples: list[str] = field(default_factory=list)  # sanitised paths or user agents
    tighten: list[Action] = field(default_factory=list)


@dataclass
class WindowSummary:
    """The slim version of a window: counts and classes, no individual requests."""

    start: datetime
    end: datetime
    requests: int = 0
    clients: int = 0
    by_status: dict[str, int] = field(default_factory=dict)  # "2xx" .. "5xx"
    by_class: dict[str, int] = field(default_factory=dict)  # probe classes and "normal"
    peak_per_minute: int = 0
    top_networks: list[dict[str, object]] = field(default_factory=list)
    auth_failures: int = 0
    server_errors: int = 0
    skipped_bytes: int = 0  # log that was not read because the window was too big (a flood)
