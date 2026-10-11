"""accounts — serializers: input/output schemas for the v1 API.

Validation boundary for api.py → viewsets/ → serializers/ → services/.
Schemas mirror console permission codes; responses carry no secrets.
"""

from __future__ import annotations

from ninja import Schema


class DomainOut(Schema):
    name: str
    verified: bool
    mx_verified: bool
    spf_verified: bool
    dkim_verified: bool
    dmarc_verified: bool


class StatusOut(Schema):
    ok: bool
    domains: int
    mailboxes: int


__all__ = ['DomainOut', 'StatusOut']
