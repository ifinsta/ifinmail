"""dns — serializers: request parsing and response shaping for the API flow.

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
Serializers validate transport input and shape service outcomes into the
stable JSON contract (same keys and status codes as before).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DNSConfigureRequest:
    """Parsed POST body for dns_configure."""

    provider: str
    domain: str
    credentials: dict[str, str]

    @classmethod
    def from_post(cls, post: dict[str, str], default_domain: str) -> DNSConfigureRequest:
        return cls(
            provider=(post.get('provider') or '').lower(),
            domain=post.get('domain') or default_domain,
            credentials=dict(post),
        )

    def missing_fields(self, required: list[str]) -> list[str]:
        return [f for f in required if not (self.credentials.get(f) or '').strip()]

    def credential_map(self, required: list[str]) -> dict[str, str]:
        return {f: (self.credentials.get(f) or '').strip() for f in required}


@dataclass(frozen=True)
class ProvisionStepOut:
    name: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {'name': self.name, 'status': self.status, 'detail': self.detail}


@dataclass(frozen=True)
class DNSConfigureResponse:
    """Response contract for dns_configure."""

    success: bool
    message: str
    records_created: list[str] = field(default_factory=list)
    records_failed: list[str] = field(default_factory=list)
    steps: list[ProvisionStepOut] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            'success': self.success,
            'message': self.message,
            'records_created': self.records_created,
            'records_failed': self.records_failed,
            'steps': [st.to_dict() for st in self.steps],
            'propagation_note': (
                'DNS changes may take up to 48 hours to propagate. '
                'The server re-checks automatically and starts accepting mail '
                'once MX resolves.'
            ),
        }


@dataclass(frozen=True)
class DNSStatusResponse:
    """Response contract for dns_status."""

    domain: str
    records: dict[str, object] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        body: dict[str, object] = {'domain': self.domain}
        if self.error is not None:
            body['error'] = self.error
        else:
            body['records'] = self.records or {}
        return body


__all__ = [
    'DNSConfigureRequest',
    'DNSConfigureResponse',
    'DNSStatusResponse',
    'ProvisionStepOut',
]
