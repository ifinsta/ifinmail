"""Builds small, structurally real APKs for tests (no binary fixtures, no Android tooling).

The manifest is a genuine compiled-XML document (string pool + start-element chunks) and the
signature, when asked for, is a genuine APK Signing Block holding a v2 pair, so the inspector is
tested against the same structures it meets in production.
"""

from __future__ import annotations

import io
import struct
import zipfile

_NO_INDEX = 0xFFFFFFFF
_ATTR_NS_ANDROID = 0  # index of the android namespace URI in the pool built below


def _pool(strings: list[str]) -> bytes:
    body = bytearray()
    offsets = []
    for text in strings:
        offsets.append(len(body))
        raw = text.encode('utf-16-le')
        body += struct.pack('<H', len(text)) + raw + b'\x00\x00'
    while len(body) % 4:
        body += b'\x00'
    header_size = 28
    strings_start = header_size + 4 * len(strings)
    size = strings_start + len(body)
    out = struct.pack('<HHIIIIII', 0x0001, header_size, size, len(strings), 0, 0, strings_start, 0)
    out += b''.join(struct.pack('<I', o) for o in offsets)
    return out + bytes(body)


def _start(name: int, attrs: list[tuple[int, int, int, int]]) -> bytes:
    """``attrs`` are ``(name_index, value_type, data, raw_string_index_or_NO_INDEX)``."""
    fixed = struct.pack('<IIHHHHHH', _NO_INDEX, name, 0x14, 0x14, len(attrs), 0, 0, 0)
    body = b''
    for attr_name, kind, data, raw in attrs:
        body += struct.pack('<IIIHBBI', _ATTR_NS_ANDROID, attr_name, raw, 8, 0, kind, data)
    size = 16 + len(fixed) + len(body)
    return struct.pack('<HHIII', 0x0102, 16, size, 1, _NO_INDEX) + fixed + body


def _end(name: int) -> bytes:
    return struct.pack('<HHIIIII', 0x0103, 16, 24, 1, _NO_INDEX, _NO_INDEX, name)


def manifest_xml(
    *, package: str, version_code: int, version_name: str, min_sdk: int, target_sdk: int
) -> bytes:
    strings = [
        'http://schemas.android.com/apk/res/android',  # 0
        'versionCode',  # 1
        'versionName',  # 2
        'package',  # 3
        'minSdkVersion',  # 4
        'targetSdkVersion',  # 5
        'manifest',  # 6
        'uses-sdk',  # 7
        package,  # 8
        version_name,  # 9
    ]
    chunks = _pool(strings)
    chunks += _start(
        6,
        [
            (1, 0x10, version_code, _NO_INDEX),
            (2, 0x03, 9, 9),
            (3, 0x03, 8, 8),
        ],
    )
    chunks += _start(7, [(4, 0x10, min_sdk, _NO_INDEX), (5, 0x10, target_sdk, _NO_INDEX)])
    chunks += _end(7) + _end(6)
    return struct.pack('<HHI', 0x0003, 8, 8 + len(chunks)) + chunks


def _signing_block(certificate: bytes) -> bytes:
    def prefixed(data: bytes) -> bytes:
        return struct.pack('<I', len(data)) + data

    digests = prefixed(b'')
    certificates = prefixed(prefixed(certificate))
    signed_data = prefixed(digests + certificates + prefixed(b''))
    signer = prefixed(signed_data + prefixed(b'') + prefixed(b'public-key'))
    value = prefixed(signer)
    pair_id = struct.pack('<I', 0x7109871A)
    pair = struct.pack('<Q', len(pair_id) + len(value)) + pair_id + value
    size = len(pair) + 8 + 16  # trailing size + magic
    return struct.pack('<Q', size) + pair + struct.pack('<Q', size) + b'APK Sig Block 42'


def build_apk(
    *,
    package: str = 'com.ifinmail',
    version_code: int = 1,
    version_name: str = '1.0.0',
    min_sdk: int = 24,
    target_sdk: int = 36,
    certificate: bytes | None = b'certificate-A',
    v1_signature: bool = False,
    with_manifest: bool = True,
) -> bytes:
    """An APK as bytes. ``certificate=None`` and ``v1_signature=False`` makes it unsigned."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as archive:
        if with_manifest:
            archive.writestr(
                'AndroidManifest.xml',
                manifest_xml(
                    package=package,
                    version_code=version_code,
                    version_name=version_name,
                    min_sdk=min_sdk,
                    target_sdk=target_sdk,
                ),
            )
        archive.writestr('classes.dex', b'dex\n035\x00' + bytes(range(256)) * 8)
        archive.writestr('assets/padding.bin', bytes(2048))
        if v1_signature:
            archive.writestr('META-INF/CERT.SF', b'Signature-Version: 1.0\n')
            archive.writestr('META-INF/CERT.RSA', b'pkcs7')
    data = buffer.getvalue()
    if certificate is None:
        return data
    eocd = data.rfind(b'PK\x05\x06')
    central_directory = struct.unpack_from('<I', data, eocd + 16)[0]
    block = _signing_block(certificate)
    patched = bytearray(data[:central_directory] + block + data[central_directory:])
    new_eocd = eocd + len(block)
    struct.pack_into('<I', patched, new_eocd + 16, central_directory + len(block))
    return bytes(patched)
