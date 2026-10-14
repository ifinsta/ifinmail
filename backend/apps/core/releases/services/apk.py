"""Reads what the server needs to know about an Android package without any Android tooling.

An uploaded APK is untrusted input. This module opens it as a ZIP, reads only
``AndroidManifest.xml`` (bounded) and the APK Signing Block, and reports:

* the application id, version code and name, and the SDK levels from the compiled (binary) XML
  manifest;
* whether the package is signed at all and, for v2/v3 signatures, the SHA-256 of the first signer
  certificate, which is what Android compares when it decides whether an update may replace the
  installed app.

Nothing here trusts the file: every read is bounds-checked, sizes are capped, and any structural
problem raises :class:`ApkError`, whose message is safe to show to the person who uploaded it.
"""

from __future__ import annotations

import hashlib
import struct
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from typing import IO

_MAX_MANIFEST_BYTES = 8 * 1024 * 1024
_MAX_STRINGS = 200_000
_EOCD_SIGNATURE = b'PK\x05\x06'
_SIGNING_BLOCK_MAGIC = b'APK Sig Block 42'
_SIGNATURE_V2 = 0x7109871A
_SIGNATURE_V3 = 0xF05368C0
_SIGNATURE_V31 = 0x1B93AD61

# Binary XML chunk types
_XML = 0x0003
_STRING_POOL = 0x0001
_START_ELEMENT = 0x0102

# Typed value kinds
_TYPE_STRING = 0x03
_TYPE_INT_DEC = 0x10
_TYPE_INT_HEX = 0x11


class ApkError(ValueError):
    """The file is not an installable APK; the message says why."""


@dataclass(frozen=True)
class ApkInfo:
    package: str
    version_code: int
    version_name: str
    min_sdk: int
    target_sdk: int
    signed: bool
    signing_cert_sha256: str  # '' when only a v1 (JAR) signature is present
    sha256: str
    size_bytes: int


# -- binary XML ------------------------------------------------------------------------------


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def u16(self, offset: int) -> int:
        try:
            return int(struct.unpack_from('<H', self.data, offset)[0])
        except struct.error as exc:
            raise ApkError('The manifest of this APK is damaged.') from exc

    def u32(self, offset: int) -> int:
        try:
            return int(struct.unpack_from('<I', self.data, offset)[0])
        except struct.error as exc:
            raise ApkError('The manifest of this APK is damaged.') from exc

    def u8(self, offset: int) -> int:
        if offset < 0 or offset >= len(self.data):
            raise ApkError('The manifest of this APK is damaged.')
        return self.data[offset]


def _read_string_pool(r: _Reader, pos: int) -> list[str]:
    count = r.u32(pos + 8)
    flags = r.u32(pos + 16)
    strings_start = r.u32(pos + 20)
    if count > _MAX_STRINGS:
        raise ApkError('The manifest of this APK is damaged.')
    utf8 = bool(flags & 0x100)
    offsets = pos + r.u16(pos + 2)
    base = pos + strings_start
    out: list[str] = []
    for index in range(count):
        p = base + r.u32(offsets + 4 * index)
        if utf8:
            # char count, then byte count; each is one byte or two when the high bit is set
            first = r.u8(p)
            p += 2 if first & 0x80 else 1
            second = r.u8(p)
            if second & 0x80:
                length = ((second & 0x7F) << 8) | r.u8(p + 1)
                p += 2
            else:
                length = second
                p += 1
            raw = r.data[p : p + length]
            out.append(raw.decode('utf-8', 'replace'))
        else:
            word = r.u16(p)
            if word & 0x8000:
                length = ((word & 0x7FFF) << 16) | r.u16(p + 2)
                p += 4
            else:
                length = word
                p += 2
            raw = r.data[p : p + 2 * length]
            out.append(raw.decode('utf-16-le', 'replace'))
    return out


def _attribute_value(r: _Reader, at: int, strings: list[str]) -> str | int | None:
    kind = r.u8(at + 15)
    data = r.u32(at + 16)
    if kind == _TYPE_STRING:
        return strings[data] if data < len(strings) else None
    if kind in (_TYPE_INT_DEC, _TYPE_INT_HEX):
        return data
    return None  # references and other kinds need resources.arsc, which is not read


def parse_manifest(data: bytes) -> dict[str, str | int]:
    """The fields of the ``<manifest>`` and ``<uses-sdk>`` elements of a compiled manifest."""
    r = _Reader(data)
    if len(data) < 8 or r.u16(0) != _XML:
        raise ApkError('AndroidManifest.xml is not a compiled Android manifest.')
    pos = r.u16(2)
    strings: list[str] = []
    found: dict[str, str | int] = {}
    seen_manifest = False
    while pos + 8 <= len(data):
        chunk_type, header, size = r.u16(pos), r.u16(pos + 2), r.u32(pos + 4)
        if size < 8 or pos + size > len(data):
            raise ApkError('The manifest of this APK is damaged.')
        if chunk_type == _STRING_POOL:
            strings = _read_string_pool(r, pos)
        elif chunk_type == _START_ELEMENT:
            name_index = r.u32(pos + 20)
            element = strings[name_index] if name_index < len(strings) else ''
            attr_start = r.u16(pos + 24)
            attr_size = r.u16(pos + 26)
            attr_count = r.u16(pos + 28)
            if attr_size != 20:
                raise ApkError('The manifest of this APK is damaged.')
            first = pos + header + attr_start
            if element in ('manifest', 'uses-sdk'):
                seen_manifest = seen_manifest or element == 'manifest'
                for i in range(attr_count):
                    at = first + i * attr_size
                    key_index = r.u32(at + 4)
                    key = strings[key_index] if key_index < len(strings) else ''
                    value = _attribute_value(r, at, strings)
                    if value is not None:
                        found[f'{element}.{key}'] = value
        pos += size
    if not seen_manifest:
        raise ApkError('AndroidManifest.xml has no <manifest> element.')
    return found


# -- signatures ------------------------------------------------------------------------------


def _signing_block(stream: IO[bytes], size: int) -> bytes | None:
    """The APK Signing Block (without its trailing size and magic), or None."""
    tail = min(size, 65_557)  # EOCD is at most 22 bytes plus a 65 535 byte comment
    stream.seek(size - tail)
    window = stream.read(tail)
    eocd = window.rfind(_EOCD_SIGNATURE)
    if eocd < 0 or eocd + 20 > len(window):
        return None
    central_directory = struct.unpack_from('<I', window, eocd + 16)[0]
    if central_directory < 32 or central_directory > size:
        return None
    stream.seek(central_directory - 24)
    footer = stream.read(24)
    if len(footer) != 24 or footer[8:] != _SIGNING_BLOCK_MAGIC:
        return None
    block_size = struct.unpack_from('<Q', footer, 0)[0]
    if block_size < 24 or block_size + 8 > central_directory or block_size > 64 * 1024 * 1024:
        return None
    start = central_directory - block_size - 8
    stream.seek(start + 8)
    return stream.read(block_size - 16)


def _first_certificate(value: bytes) -> bytes | None:
    """The DER of the first signer's first certificate in a v2/v3 signature value."""

    def length_prefixed(buf: bytes, at: int) -> tuple[bytes, int]:
        if at + 4 > len(buf):
            raise ApkError('The signature of this APK is damaged.')
        n = struct.unpack_from('<I', buf, at)[0]
        if at + 4 + n > len(buf):
            raise ApkError('The signature of this APK is damaged.')
        return buf[at + 4 : at + 4 + n], at + 4 + n

    signers, _ = length_prefixed(value, 0)
    signer, _ = length_prefixed(signers, 0)
    signed_data, _ = length_prefixed(signer, 0)
    _digests, after = length_prefixed(signed_data, 0)
    certificates, _ = length_prefixed(signed_data, after)
    if not certificates:
        return None
    certificate, _ = length_prefixed(certificates, 0)
    return certificate


def _signing_certificate_sha256(block: bytes) -> str:
    pos = 0
    wanted = (_SIGNATURE_V31, _SIGNATURE_V3, _SIGNATURE_V2)
    pairs: dict[int, bytes] = {}
    while pos + 12 <= len(block):
        pair_size = struct.unpack_from('<Q', block, pos)[0]
        if pair_size < 4 or pos + 8 + pair_size > len(block):
            break
        pair_id = struct.unpack_from('<I', block, pos + 8)[0]
        pairs[pair_id] = block[pos + 12 : pos + 8 + pair_size]
        pos += 8 + pair_size
    for pair_id in wanted:
        if pair_id in pairs:
            certificate = _first_certificate(pairs[pair_id])
            if certificate:
                return hashlib.sha256(certificate).hexdigest()
    return ''


# -- entry point -----------------------------------------------------------------------------


def _hash_stream(stream: IO[bytes]) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    stream.seek(0)
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(chunk)
        total += len(chunk)
    stream.seek(0)
    return digest.hexdigest(), total


def inspect_apk(stream: IO[bytes], *, on_progress: Callable[[int], None] | None = None) -> ApkInfo:
    """Validate ``stream`` as an APK and describe it. ``stream`` must be seekable."""
    sha256, size = _hash_stream(stream)
    if on_progress is not None:
        on_progress(size)
    if size < 1024:
        raise ApkError('This file is too small to be an APK.')
    try:
        archive = zipfile.ZipFile(stream)
    except zipfile.BadZipFile as exc:
        raise ApkError('This file is not an APK (it is not a ZIP archive).') from exc
    with archive:
        names = archive.namelist()
        if 'AndroidManifest.xml' not in names:
            raise ApkError('This archive has no AndroidManifest.xml, so it is not an APK.')
        entry = archive.getinfo('AndroidManifest.xml')
        if entry.file_size > _MAX_MANIFEST_BYTES:
            raise ApkError('The manifest of this APK is implausibly large.')
        manifest = parse_manifest(archive.read(entry))
        v1_signed = any(
            n.startswith('META-INF/') and n.rsplit('.', 1)[-1].upper() in ('RSA', 'DSA', 'EC')
            for n in names
        )
    block = _signing_block(stream, size)
    certificate = _signing_certificate_sha256(block) if block else ''
    signed = bool(certificate or block or v1_signed)

    package = str(manifest.get('manifest.package', '')).strip()
    version_code = manifest.get('manifest.versionCode')
    if not package:
        raise ApkError('The manifest names no application id (package).')
    if not isinstance(version_code, int) or version_code < 1:
        raise ApkError('The manifest has no usable versionCode.')
    return ApkInfo(
        package=package,
        version_code=version_code,
        version_name=str(manifest.get('manifest.versionName', '')).strip(),
        min_sdk=int(manifest.get('uses-sdk.minSdkVersion', 0) or 0),
        target_sdk=int(manifest.get('uses-sdk.targetSdkVersion', 0) or 0),
        signed=signed,
        signing_cert_sha256=certificate,
        sha256=sha256,
        size_bytes=size,
    )


__all__ = ['ApkError', 'ApkInfo', 'inspect_apk', 'parse_manifest']
