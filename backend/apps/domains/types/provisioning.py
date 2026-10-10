"""Typed results of the domain provisioning and verification pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class StepStatus(StrEnum):
    OK = 'ok'
    SKIPPED = 'skipped'
    MANUAL = 'manual'  # needs a person (for example DNS without a provider)
    WARN = 'warn'
    ERROR = 'error'


class CheckStatus(StrEnum):
    PASS = 'pass'
    FAIL = 'fail'
    ERROR = 'err'  # the lookup itself failed; do not change stored state


@dataclass(frozen=True)
class ProvisionStep:
    name: str
    status: StepStatus
    detail: str = ''


@dataclass(frozen=True)
class DNSCheck:
    status: CheckStatus
    detail: str = ''


@dataclass(frozen=True)
class VerificationResult:
    domain: str
    mx: DNSCheck
    spf: DNSCheck
    dkim: DNSCheck
    dmarc: DNSCheck
    accepts_mail: bool = False

    def as_dict(self) -> dict[str, dict[str, str]]:
        return {
            name: {'status': str(check.status), 'detail': check.detail}
            for name, check in (
                ('mx', self.mx),
                ('spf', self.spf),
                ('dkim', self.dkim),
                ('dmarc', self.dmarc),
            )
        }


@dataclass
class ProvisionResult:
    domain: str
    created: bool
    steps: list[ProvisionStep] = field(default_factory=list)
    dns_records: list[dict[str, str]] = field(default_factory=list)
    verification: VerificationResult | None = None

    @property
    def ok(self) -> bool:
        return not any(s.status == StepStatus.ERROR for s in self.steps)
