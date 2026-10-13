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


# -- API-wide contract types --------------------------------------------------------------------


class ErrorV1(Schema):
    """Every error answer of the API: a message safe to show, nothing else."""

    detail: str


class ApiVersionV1(Schema):
    version: str
    status: str
    url: str
    openapi: str


class ApiIndexV1(Schema):
    current: str
    versions: list[ApiVersionV1]


__all__ = ['ApiIndexV1', 'ApiVersionV1', 'DomainOut', 'ErrorV1', 'StatusOut']
