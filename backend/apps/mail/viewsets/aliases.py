"""Alias viewset — operations over AliasService."""

from __future__ import annotations

from backend.apps.mail.serializers import AliasCreateIn, AliasOut
from backend.apps.mail.services.mailboxes import AliasService


def list_aliases() -> list[AliasOut]:
    return [AliasOut.from_row(row) for row in AliasService.list_rows()]


def create_alias(payload: AliasCreateIn) -> AliasOut:
    alias = AliasService.create(payload.source, payload.destination)
    return AliasOut(
        id=str(alias.id),
        source=alias.source,
        destination=alias.destination,
        domain=alias.domain.name,
    )


def delete_alias(alias_id: str) -> None:
    AliasService.delete(alias_id)


__all__ = ['create_alias', 'delete_alias', 'list_aliases']
