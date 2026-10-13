"""The local driver: files on this server's disk (the default, and the behaviour before v0.0.40).

Writes are atomic (a temporary file in the same directory, then a rename), so a reader never sees
half a file; paths are built only from keys that passed ``check_key`` and are confirmed to stay
under the root.
"""

from __future__ import annotations

import contextlib
import hashlib
import mimetypes
import os
import tempfile
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from ..contract import (
    DEFAULT_MAX_READ,
    InvalidKeyError,
    ObjectInfo,
    ObjectNotFoundError,
    ProbeResult,
    StorageError,
    StorageUnavailableError,
    check_key,
)


class LocalStore:
    name = 'local'

    def __init__(self, root: str | os.PathLike[str]) -> None:
        if not root:
            raise StorageError('The local store needs a directory.')
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self.root / check_key(key)).resolve()
        root = self.root.resolve()
        if root != path and root not in path.parents:
            raise InvalidKeyError('That key would leave the storage directory.')
        return path

    @staticmethod
    def _info(key: str, path: Path, sha256: str = '') -> ObjectInfo:
        stat = path.stat()
        return ObjectInfo(
            key=key,
            size=stat.st_size,
            etag=f'{stat.st_size:x}-{int(stat.st_mtime_ns):x}',
            content_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream',
            modified=datetime.fromtimestamp(stat.st_mtime, UTC),
            sha256=sha256,
        )

    def put(self, key: str, data: bytes, *, content_type: str = '') -> ObjectInfo:
        import io

        return self.put_stream(key, io.BytesIO(data), content_type=content_type, size=len(data))

    def put_stream(
        self, key: str, stream: BinaryIO, *, content_type: str = '', size: int | None = None
    ) -> ObjectInfo:
        path = self._path(key)
        digest = hashlib.sha256()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle, temp = tempfile.mkstemp(prefix='.upload-', dir=path.parent)
            try:
                with os.fdopen(handle, 'wb') as out:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                        out.write(chunk)
                os.chmod(temp, 0o644)
                os.replace(temp, path)
            finally:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(temp)
        except OSError as exc:
            raise StorageUnavailableError(
                f'Could not write to the disk: {exc.strerror or exc}'
            ) from exc
        return self._info(key, path, digest.hexdigest())

    def get(self, key: str, *, max_bytes: int = DEFAULT_MAX_READ) -> bytes:
        path = self._path(key)
        try:
            if path.stat().st_size > max_bytes:
                raise StorageError('That object is too large to read at once.')
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(f'No object "{key}".') from exc
        except IsADirectoryError as exc:
            raise ObjectNotFoundError(f'No object "{key}".') from exc
        except OSError as exc:
            raise StorageUnavailableError(
                f'Could not read from the disk: {exc.strerror or exc}'
            ) from exc

    def open(self, key: str, *, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        path = self._path(key)
        try:
            handle = path.open('rb')
        except (FileNotFoundError, IsADirectoryError) as exc:
            raise ObjectNotFoundError(f'No object "{key}".') from exc

        def chunks() -> Iterator[bytes]:
            with handle:
                while chunk := handle.read(chunk_size):
                    yield chunk

        return chunks()

    def head(self, key: str) -> ObjectInfo:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFoundError(f'No object "{key}".')
        return self._info(key, path)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._path(key).unlink()

    def list(self, prefix: str = '', *, limit: int = 1000) -> list[ObjectInfo]:
        base = self.root.resolve()
        out: list[ObjectInfo] = []
        if not base.is_dir():
            return out
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames.sort()
            for filename in sorted(filenames):
                if filename.startswith('.upload-'):
                    continue
                full = Path(dirpath) / filename
                key = full.relative_to(base).as_posix()
                if key.startswith(prefix):
                    out.append(self._info(key, full))
                    if len(out) >= limit:
                        return out
        return out

    def retrieval_url(self, key: str, *, expires: int = 300) -> str | None:
        return None  # served from the disk by the web server (or the console)

    def probe(self) -> ProbeResult:
        started = time.monotonic()
        key = f'.ifinmail-probe/{uuid.uuid4().hex}'
        try:
            body = os.urandom(32)
            self.put(key, body)
            ok = self.get(key) == body
            self.delete(key)
        except StorageError as exc:
            return ProbeResult(False, self.name, str(exc))
        ms = int((time.monotonic() - started) * 1000)
        return ProbeResult(ok, self.name, 'Wrote, read back and removed a test file.', ms)
