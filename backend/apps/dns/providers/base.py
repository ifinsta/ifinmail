"""Abstract DNS provider interface."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class DNSRecord:
    type: str  # A, MX, TXT, CNAME
    name: str  # @ for root, subdomain name otherwise
    value: str  # record value
    priority: int = 0  # MX priority
    ttl: int = 3600


@dataclass
class DNSResult:
    success: bool
    message: str
    records_created: list[str] = field(default_factory=list)
    records_failed: list[str] = field(default_factory=list)


def record_key(rec_type: str, name: str, content: str) -> tuple[str, str, str]:
    """Identity of a record when deciding "update the existing one or create".

    Several TXT records commonly share one name (SPF next to a site-verification
    token), so a TXT record is identified by its ``v=`` tag, never by name alone.
    Any TXT without a recognised tag is identified by its full content, which
    means we create it instead of overwriting somebody else's record.
    """
    if rec_type != 'TXT':
        return (rec_type, name, '')
    text = content.strip().strip('"').strip()
    lowered = text.lower()
    if lowered.startswith('v='):
        return (rec_type, name, lowered.split(';', 1)[0].split(' ', 1)[0])
    return (rec_type, name, lowered)


class BaseDNSProvider(Protocol):
    """Protocol that all DNS provider backends must implement."""

    provider_name: str

    def configure_domain(self, domain: str, records: list[DNSRecord]) -> DNSResult:
        """Create or update DNS records for a domain. Returns per-record results."""
        ...

    def verify_records(self, domain: str) -> dict[str, bool]:
        """Check whether expected records exist for a domain. Returns {record_type: exists}."""
        ...

    def get_nameservers(self, domain: str) -> list[str]:
        """Return the authoritative nameservers for this domain."""
        ...
