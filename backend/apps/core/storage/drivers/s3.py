"""The S3 driver: any service that speaks the S3 REST API, signed with SigV4 (stdlib only).

AWS, Cloudflare R2, Backblaze B2, Wasabi, DigitalOcean Spaces, Hetzner, OVHcloud, Scaleway, Ceph,
Garage and SeaweedFS all accept these requests. Only the operations the contract needs are used:
PUT/GET/HEAD/DELETE object, ListObjectsV2, multipart upload, and pre-signed GET URLs.

Every request has a timeout; reads, heads, deletes and lists are retried with backoff on network
errors, 5xx and 429; a write is retried only when its body can be sent again (single PUT and each
multipart part). Large streams are uploaded in 16 MiB parts so memory stays flat whatever the size.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import io
import os
import ssl
import time
import uuid
import xml.etree.ElementTree as ET  # noqa: S405 - responses of the configured endpoint, size-bounded
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import BinaryIO
from urllib.parse import SplitResult, urlsplit

from ..contract import (
    DEFAULT_MAX_READ,
    ObjectInfo,
    ObjectNotFoundError,
    ProbeResult,
    StorageError,
    StorageRejectedError,
    StorageUnavailableError,
    check_key,
)
from . import sigv4

PART_SIZE = 16 * 1024 * 1024
MAX_PARTS = 10_000
TIMEOUT = 30.0
RETRIES = 3
MAX_XML = 4 * 1024 * 1024
_RETRY_STATUS = {429, 500, 502, 503, 504}


def _text(element: ET.Element | None, tag: str) -> str:
    if element is None:
        return ''
    for child in element:
        if child.tag.rsplit('}', 1)[-1] == tag:
            return child.text or ''
    return ''


def _children(element: ET.Element, tag: str) -> list[ET.Element]:
    return [c for c in element if c.tag.rsplit('}', 1)[-1] == tag]


@dataclass
class _Response:
    status: int
    headers: dict[str, str]
    body: bytes = b''
    stream: http.client.HTTPResponse | None = field(default=None, repr=False)


@dataclass
class S3Store:
    endpoint: str
    bucket: str
    access_key: str
    secret_key: str = field(repr=False)
    region: str = 'us-east-1'
    prefix: str = ''
    addressing: str = 'path'
    name: str = 's3'

    @classmethod
    def from_settings(cls, settings: Mapping[str, str]) -> S3Store:
        endpoint = (settings.get('endpoint') or '').strip().rstrip('/')
        parts = urlsplit(endpoint)
        if parts.scheme not in ('http', 'https') or not parts.hostname:
            raise StorageRejectedError('The storage endpoint must be an http(s) URL.')
        bucket = (settings.get('bucket') or '').strip()
        if not bucket:
            raise StorageRejectedError('A bucket name is needed.')
        if not settings.get('access_key') or not settings.get('secret_key'):
            raise StorageRejectedError('An access key and a secret key are needed.')
        prefix = (settings.get('prefix') or '').strip().strip('/')
        if prefix:
            check_key(prefix)
        return cls(
            endpoint=endpoint,
            bucket=bucket,
            access_key=settings['access_key'].strip(),
            secret_key=settings['secret_key'].strip(),
            region=(settings.get('region') or 'us-east-1').strip() or 'us-east-1',
            prefix=prefix,
            addressing='virtual' if settings.get('addressing') == 'virtual' else 'path',
        )

    # -- addressing ----------------------------------------------------------------------------

    @property
    def _parts(self) -> SplitResult:
        return urlsplit(self.endpoint)

    def _host(self) -> str:
        parts = self._parts
        host = parts.hostname or ''
        default = 443 if parts.scheme == 'https' else 80
        port = f':{parts.port}' if parts.port and parts.port != default else ''
        if self.addressing == 'virtual':
            host = f'{self.bucket}.{host}'
        return host + port

    def _object_key(self, key: str) -> str:
        check_key(key)
        return f'{self.prefix}/{key}' if self.prefix else key

    def _path(self, object_key: str = '') -> str:
        base = self._parts.path.rstrip('/')
        if self.addressing == 'virtual':
            return f'{base}/{object_key}' if object_key else f'{base}/'
        return f'{base}/{self.bucket}/{object_key}' if object_key else f'{base}/{self.bucket}'

    # -- transport ------------------------------------------------------------------------------

    def _connection(self) -> http.client.HTTPConnection:
        parts = self._parts
        host = parts.hostname or ''
        if self.addressing == 'virtual':
            host = f'{self.bucket}.{host}'
        if parts.scheme == 'https':
            return http.client.HTTPSConnection(
                host, parts.port or 443, timeout=TIMEOUT, context=ssl.create_default_context()
            )
        return http.client.HTTPConnection(host, parts.port or 80, timeout=TIMEOUT)

    def _request(
        self,
        method: str,
        object_key: str = '',
        *,
        query: Mapping[str, str] | None = None,
        body: bytes = b'',
        headers: Mapping[str, str] | None = None,
        stream: bool = False,
        retry: bool = True,
    ) -> _Response:
        query = dict(query or {})
        path = self._path(object_key)
        payload_hash = hashlib.sha256(body).hexdigest()
        attempts = RETRIES if retry else 1
        last: Exception | None = None
        for attempt in range(attempts):
            if attempt:
                time.sleep(0.5 * 2 ** (attempt - 1))
            signed = sigv4.sign_headers(
                method=method,
                path=path,
                query=query,
                headers={'host': self._host(), **(headers or {})},
                payload_sha256=payload_hash,
                access_key=self.access_key,
                secret_key=self.secret_key,
                region=self.region,
            )
            target = sigv4.uri_encode(path, keep_slash=True)
            if query:
                target += '?' + sigv4.canonical_query(query)
            connection = self._connection()
            try:
                connection.request(
                    method,
                    target,
                    body=body or None,
                    headers={**signed, 'Content-Length': str(len(body))},
                )
                response = connection.getresponse()
            except (OSError, TimeoutError, http.client.HTTPException) as exc:
                connection.close()
                last = exc
                continue
            if response.status in _RETRY_STATUS and attempt < attempts - 1:
                response.read()
                connection.close()
                last = StorageUnavailableError(f'The storage service answered {response.status}.')
                continue
            headers_out = {k.lower(): v for k, v in response.getheaders()}
            if stream and response.status == 200:
                return _Response(response.status, headers_out, stream=response)
            data = response.read(MAX_XML + 1) if method != 'HEAD' else b''
            connection.close()
            return _Response(response.status, headers_out, data)
        raise StorageUnavailableError(f'The storage service could not be reached: {last}')

    def _fail(self, response: _Response, key: str = '') -> StorageError:
        code, message = '', ''
        if response.body:
            try:
                root = ET.fromstring(response.body[:MAX_XML])  # noqa: S314
                code, message = _text(root, 'Code'), _text(root, 'Message')
            except ET.ParseError:
                pass
        if response.status == 404 and code in ('', 'NoSuchKey'):
            return ObjectNotFoundError(f'No object "{key}".')
        if code == 'NoSuchBucket':
            return StorageRejectedError(f'The bucket "{self.bucket}" does not exist.')
        if code in ('InvalidAccessKeyId', 'SignatureDoesNotMatch'):
            return StorageRejectedError(
                'The storage service did not accept the access key or secret.'
            )
        if code == 'RequestTimeTooSkewed':
            return StorageRejectedError(
                'This server’s clock differs too much from the storage service.'
            )
        if code == 'AccessDenied' or response.status == 403:
            return StorageRejectedError('The key may not do that in this bucket (access denied).')
        if response.status in _RETRY_STATUS:
            return StorageUnavailableError(f'The storage service answered {response.status}.')
        detail = f' ({code}: {message})' if code else ''
        return StorageRejectedError(
            f'The storage service refused the request: {response.status}{detail}.'
        )

    # -- the contract ---------------------------------------------------------------------------

    def put(self, key: str, data: bytes, *, content_type: str = '') -> ObjectInfo:
        object_key = self._object_key(key)
        response = self._request(
            'PUT',
            object_key,
            body=data,
            headers={'content-type': content_type or 'application/octet-stream'},
        )
        if response.status != 200:
            raise self._fail(response, key)
        return ObjectInfo(
            key=key,
            size=len(data),
            etag=response.headers.get('etag', '').strip('"'),
            content_type=content_type or 'application/octet-stream',
            sha256=hashlib.sha256(data).hexdigest(),
        )

    def put_stream(
        self, key: str, stream: BinaryIO, *, content_type: str = '', size: int | None = None
    ) -> ObjectInfo:
        first = stream.read(PART_SIZE)
        if len(first) < PART_SIZE:
            return self.put(key, first, content_type=content_type)
        object_key = self._object_key(key)
        content_type = content_type or 'application/octet-stream'
        created = self._request(
            'POST', object_key, query={'uploads': ''}, headers={'content-type': content_type}
        )
        if created.status != 200:
            raise self._fail(created, key)
        upload_id = _text(ET.fromstring(created.body), 'UploadId')  # noqa: S314
        if not upload_id:
            raise StorageUnavailableError('The storage service did not start the upload.')
        etags: list[str] = []
        total = 0
        digest = hashlib.sha256()
        try:
            chunk = first
            while chunk:
                if len(etags) >= MAX_PARTS:
                    raise StorageRejectedError('That file is too large for one object.')
                digest.update(chunk)
                total += len(chunk)
                part = self._request(
                    'PUT',
                    object_key,
                    query={'partNumber': str(len(etags) + 1), 'uploadId': upload_id},
                    body=chunk,
                )
                if part.status != 200:
                    raise self._fail(part, key)
                etags.append(part.headers.get('etag', ''))
                chunk = stream.read(PART_SIZE)
            body = (
                '<CompleteMultipartUpload>'
                + ''.join(
                    f'<Part><PartNumber>{n}</PartNumber><ETag>{e}</ETag></Part>'
                    for n, e in enumerate(etags, 1)
                )
                + '</CompleteMultipartUpload>'
            )
            done = self._request(
                'POST',
                object_key,
                query={'uploadId': upload_id},
                body=body.encode(),
                headers={'content-type': 'application/xml'},
            )
            if done.status != 200 or b'<Error>' in done.body:
                raise self._fail(done, key)
        except BaseException:
            with contextlib.suppress(StorageError):
                self._request('DELETE', object_key, query={'uploadId': upload_id}, retry=False)
            raise
        etag = _text(ET.fromstring(done.body), 'ETag').strip('"')  # noqa: S314
        return ObjectInfo(key, total, etag, content_type, sha256=digest.hexdigest())

    def get(self, key: str, *, max_bytes: int = DEFAULT_MAX_READ) -> bytes:
        response = self._request('GET', self._object_key(key), stream=True)
        if response.stream is None:
            raise self._fail(response, key)
        try:
            if int(response.headers.get('content-length') or 0) > max_bytes:
                raise StorageError('That object is too large to read at once.')
            data = response.stream.read(max_bytes + 1)
        finally:
            response.stream.close()
        if len(data) > max_bytes:
            raise StorageError('That object is too large to read at once.')
        return data

    def open(self, key: str, *, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        response = self._request('GET', self._object_key(key), stream=True)
        if response.stream is None:
            raise self._fail(response, key)
        stream = response.stream

        def chunks() -> Iterator[bytes]:
            try:
                while chunk := stream.read(chunk_size):
                    yield chunk
            finally:
                stream.close()

        return chunks()

    def head(self, key: str) -> ObjectInfo:
        response = self._request('HEAD', self._object_key(key))
        if response.status != 200:
            if response.status == 404:
                raise ObjectNotFoundError(f'No object "{key}".')
            raise self._fail(response, key)
        modified: datetime | None = None
        if response.headers.get('last-modified'):
            try:
                modified = parsedate_to_datetime(response.headers['last-modified'])
            except (TypeError, ValueError):
                modified = None
        return ObjectInfo(
            key=key,
            size=int(response.headers.get('content-length') or 0),
            etag=response.headers.get('etag', '').strip('"'),
            content_type=response.headers.get('content-type', 'application/octet-stream'),
            modified=modified,
        )

    def exists(self, key: str) -> bool:
        try:
            self.head(key)
        except ObjectNotFoundError:
            return False
        return True

    def delete(self, key: str) -> None:
        response = self._request('DELETE', self._object_key(key))
        if response.status not in (200, 204, 404):
            raise self._fail(response, key)

    def list(self, prefix: str = '', *, limit: int = 1000) -> list[ObjectInfo]:
        out: list[ObjectInfo] = []
        base = f'{self.prefix}/' if self.prefix else ''
        token = ''
        while len(out) < limit:
            query = {
                'list-type': '2',
                'prefix': base + prefix,
                'max-keys': str(min(1000, limit - len(out))),
            }
            if token:
                query['continuation-token'] = token
            response = self._request('GET', query=query)
            if response.status != 200:
                raise self._fail(response)
            root = ET.fromstring(response.body)  # noqa: S314
            for item in _children(root, 'Contents'):
                key = _text(item, 'Key')[len(base) :]
                if not key or key.startswith('.ifinmail-probe/'):
                    continue
                try:
                    modified = datetime.fromisoformat(
                        _text(item, 'LastModified').replace('Z', '+00:00')
                    )
                except ValueError:
                    modified = None
                out.append(
                    ObjectInfo(
                        key,
                        int(_text(item, 'Size') or 0),
                        _text(item, 'ETag').strip('"'),
                        modified=modified,
                    )
                )
            token = _text(root, 'NextContinuationToken')
            if _text(root, 'IsTruncated') != 'true' or not token:
                break
        return out[:limit]

    def retrieval_url(self, key: str, *, expires: int = 300) -> str | None:
        object_key = self._object_key(key)
        path = self._path(object_key)
        query = sigv4.presign(
            method='GET',
            host=self._host(),
            path=path,
            access_key=self.access_key,
            secret_key=self.secret_key,
            region=self.region,
            expires=max(1, min(int(expires), 7 * 24 * 3600)),
        )
        encoded = sigv4.uri_encode(path, keep_slash=True)
        return f'{self._parts.scheme}://{self._host()}{encoded}?{query}'

    def probe(self) -> ProbeResult:
        started = time.monotonic()
        key = f'.ifinmail-probe/{uuid.uuid4().hex}'
        body = os.urandom(32)
        try:
            self.put(key, body, content_type='application/octet-stream')
            echoed = self.get(key)
            self.delete(key)
        except StorageError as exc:
            return ProbeResult(False, self.name, str(exc))
        ms = int((time.monotonic() - started) * 1000)
        if echoed != body:
            return ProbeResult(
                False, self.name, 'The object read back was not what was written.', ms
            )
        return ProbeResult(
            True,
            self.name,
            f'Wrote, read back and removed a test object in "{self.bucket}" ({ms} ms).',
            ms,
        )


def stream_bytes(data: bytes) -> io.BytesIO:
    return io.BytesIO(data)
