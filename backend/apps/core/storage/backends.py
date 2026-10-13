"""Django's file storage, routed to whichever store holds media (the local disk by default).

``StoredFile`` (a ``FileField``) and everything else that uses ``default_storage`` go through this
backend, so moving media to object storage needs no change in the code that stores files. URLs stay
``/media/<key>`` whatever the store: nginx serves them from the disk when the file is there, and
otherwise hands them to the console, which negotiates retrieval (``views.media``).
"""

from __future__ import annotations

from datetime import datetime
from typing import IO, Any, BinaryIO, cast

from django.conf import settings
from django.core.files.base import ContentFile, File
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

from . import config
from .contract import ObjectNotFoundError, ObjectStore, StorageError, check_key


@deconstructible
class ObjectStorage(Storage):
    purpose = 'media'

    def _store(self) -> ObjectStore:
        return config.store_for(self.purpose)

    @staticmethod
    def _key(name: str) -> str:
        return check_key(str(name).replace('\\', '/').lstrip('/'))

    def _open(self, name: str, mode: str = 'rb') -> File[bytes]:
        if 'w' in mode or 'a' in mode:
            raise StorageError('Stored files are written with save(), not opened for writing.')
        try:
            data = self._store().get(self._key(name))
        except ObjectNotFoundError as exc:
            raise FileNotFoundError(name) from exc
        return ContentFile(data, name=name)

    def _save(self, name: str, content: IO[Any]) -> str:
        key = self._key(name)
        if hasattr(content, 'seek'):
            content.seek(0)
        stream = cast(BinaryIO, getattr(content, 'file', content))
        content_type = getattr(content, 'content_type', '') or ''
        self._store().put_stream(
            key, stream, content_type=content_type, size=getattr(content, 'size', None)
        )
        return key

    def delete(self, name: str) -> None:
        if name:
            self._store().delete(self._key(name))

    def exists(self, name: str) -> bool:
        return bool(self._store().exists(self._key(name)))

    def size(self, name: str) -> int:
        return int(self._store().head(self._key(name)).size)

    def path(self, name: str) -> str:
        """A path on this server's disk, only while media is kept on it (Django's convention)."""
        store = self._store()
        local_path = getattr(store, '_path', None)
        if store.name != 'local' or local_path is None:
            raise NotImplementedError('Media is in object storage: it has no path on this disk.')
        return str(local_path(self._key(name)))

    def url(self, name: str | None) -> str:
        return f'{settings.MEDIA_URL}{self._key(name or "")}'

    def listdir(self, path: str) -> tuple[list[str], list[str]]:
        prefix = path.strip('/') + '/' if path.strip('/') else ''
        dirs: set[str] = set()
        files: list[str] = []
        for item in self._store().list(prefix, limit=10_000):
            rest = item.key[len(prefix) :]
            if '/' in rest:
                dirs.add(rest.split('/', 1)[0])
            else:
                files.append(rest)
        return sorted(dirs), files

    def get_modified_time(self, name: str) -> datetime:
        modified: datetime | None = self._store().head(self._key(name)).modified
        if modified is None:
            raise NotImplementedError('This store does not report modification times.')
        return modified
