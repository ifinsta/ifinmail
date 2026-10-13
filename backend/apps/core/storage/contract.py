"""The storage contract: what every storage system must do to hold this server's files.

Drivers implement ``ObjectStore`` (the local disk, any S3-compatible service, later others); the
rest of the console only ever talks to this interface, chosen per *purpose* (media, backups) by the
``storage.objects`` capability a plugin configures. See docs/storage-contract.md.

The rules here are the same for every driver, so a key that is valid on one is valid on all:
keys are relative, slash-separated, printable, at most 512 bytes, and never climb (``..``).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO, Protocol, runtime_checkable

MAX_KEY_BYTES = 512
DEFAULT_MAX_READ = 64 * 1024 * 1024  # get() refuses objects larger than this; use open()
_BAD = re.compile(r'[\x00-\x1f\x7f\\]')


class StorageError(Exception):
    """A storage operation failed; the message is safe to show to an administrator."""


class ObjectNotFoundError(StorageError):
    """No object under that key."""


class StorageUnavailableError(StorageError):
    """The store could not be reached or answered with a server error: worth retrying later."""


class StorageRejectedError(StorageError):
    """The store refused (credentials, permissions, missing bucket, clock): needs a person."""


class InvalidKeyError(StorageError):
    """A key that breaks the contract's rules."""


def check_key(key: str) -> str:
    """The key, if it is valid for every driver; otherwise ``InvalidKeyError``."""
    if not isinstance(key, str) or not key:
        raise InvalidKeyError('An object key cannot be empty.')
    if len(key.encode('utf-8')) > MAX_KEY_BYTES:
        raise InvalidKeyError(f'An object key may be at most {MAX_KEY_BYTES} bytes.')
    if key.startswith('/') or key.endswith('/') or '//' in key:
        raise InvalidKeyError('An object key is relative and has no empty segments.')
    if _BAD.search(key):
        raise InvalidKeyError('An object key cannot contain control characters or backslashes.')
    if any(part in ('.', '..') for part in key.split('/')):
        raise InvalidKeyError('An object key cannot contain "." or ".." segments.')
    return key


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size: int
    etag: str = ''
    content_type: str = 'application/octet-stream'
    modified: datetime | None = None
    sha256: str = ''  # hex, when the driver knows it (set on put)


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    driver: str
    detail: str
    milliseconds: int = 0


@runtime_checkable
class ObjectStore(Protocol):
    """What a storage driver must provide. Every method raises a ``StorageError`` subclass."""

    name: str

    def put(self, key: str, data: bytes, *, content_type: str = ...) -> ObjectInfo: ...

    def put_stream(
        self, key: str, stream: BinaryIO, *, content_type: str = ..., size: int | None = None
    ) -> ObjectInfo: ...

    def get(self, key: str, *, max_bytes: int = DEFAULT_MAX_READ) -> bytes: ...

    def open(self, key: str, *, chunk_size: int = 1024 * 1024) -> Iterator[bytes]: ...

    def head(self, key: str) -> ObjectInfo: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

    def list(self, prefix: str = '', *, limit: int = 1000) -> list[ObjectInfo]: ...

    def retrieval_url(self, key: str, *, expires: int = 300) -> str | None: ...

    def probe(self) -> ProbeResult: ...
