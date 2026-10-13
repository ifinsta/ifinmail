"""An in-memory store that implements the storage contract, for tests (no network, no disk)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import BinaryIO

from backend.apps.core.storage.contract import (
    DEFAULT_MAX_READ,
    ObjectInfo,
    ObjectNotFoundError,
    ProbeResult,
    StorageError,
    check_key,
)


class MemoryStore:
    name = 'memory'

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str, datetime]] = {}
        self.fail = False

    def _guard(self) -> None:
        if self.fail:
            raise StorageError('The store is down.')

    def put(self, key: str, data: bytes, *, content_type: str = '') -> ObjectInfo:
        self._guard()
        check_key(key)
        self.objects[key] = (data, content_type or 'application/octet-stream', datetime.now(UTC))
        return ObjectInfo(
            key, len(data), sha256=hashlib.sha256(data).hexdigest(), content_type=content_type
        )

    def put_stream(
        self, key: str, stream: BinaryIO, *, content_type: str = '', size: int | None = None
    ) -> ObjectInfo:
        return self.put(key, stream.read(), content_type=content_type)

    def get(self, key: str, *, max_bytes: int = DEFAULT_MAX_READ) -> bytes:
        self._guard()
        if key not in self.objects:
            raise ObjectNotFoundError(key)
        return self.objects[key][0]

    def open(self, key: str, *, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        data = self.get(key)
        return iter([data[i : i + chunk_size] for i in range(0, len(data), chunk_size)] or [b''])

    def head(self, key: str) -> ObjectInfo:
        self._guard()
        if key not in self.objects:
            raise ObjectNotFoundError(key)
        data, content_type, modified = self.objects[key]
        return ObjectInfo(key, len(data), content_type=content_type, modified=modified)

    def exists(self, key: str) -> bool:
        self._guard()
        return key in self.objects

    def delete(self, key: str) -> None:
        self._guard()
        self.objects.pop(key, None)

    def list(self, prefix: str = '', *, limit: int = 1000) -> list[ObjectInfo]:
        self._guard()
        return [self.head(k) for k in sorted(self.objects) if k.startswith(prefix)][:limit]

    def retrieval_url(self, key: str, *, expires: int = 300) -> str | None:
        return f'https://store.example.test/{key}?signed={expires}'

    def probe(self) -> ProbeResult:
        if self.fail:
            return ProbeResult(False, self.name, 'The store is down.')
        return ProbeResult(True, self.name, 'Wrote, read back and removed a test object.', 3)
