"""core.storage — viewsets: API operation handlers (API flow).

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
The upload call comes from the Django request layer; this viewset keeps
the transport handling thin and delegates validation to StorageService.
"""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser
from django.core.files.uploadedfile import UploadedFile

from backend.apps.core.storage.serializers import StoredFileOut
from backend.apps.core.storage.services import StorageService


def upload_file(
    *,
    file: UploadedFile,
    user: AbstractBaseUser,
    entity_type: str,
    entity_id: str = '',
) -> StoredFileOut:
    """Validate and persist an upload; returns the shaped record."""
    stored = StorageService.upload(
        file=file,
        user=user,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    return StoredFileOut.from_model(stored)


__all__ = ['upload_file']
