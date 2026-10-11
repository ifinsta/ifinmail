"""core.storage — serializers: shaping for the API flow.

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.apps.core.storage.models import StoredFile


@dataclass(frozen=True)
class StoredFileOut:
    id: str
    original_filename: str
    content_type: str
    size_bytes: int
    entity_type: str
    entity_id: str
    visibility: str
    created_at: str

    @classmethod
    def from_model(cls, row: StoredFile) -> StoredFileOut:
        created = getattr(row, 'created_at', None)
        return cls(
            id=str(row.id),
            original_filename=row.original_filename,
            content_type=row.content_type,
            size_bytes=row.size_bytes,
            entity_type=row.entity_type,
            entity_id=str(row.entity_id) if row.entity_id else '',
            visibility=row.visibility,
            created_at=created.isoformat() if created is not None else '',
        )


__all__ = ['StoredFileOut']
