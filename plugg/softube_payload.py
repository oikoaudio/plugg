"""Extract the pinned Softube service without executing its bundled PACE setup.

The offsets describe the exact reviewed helper installer, not arbitrary NSIS
archives. New installer versions need an independently verified payload record.
SPDX-License-Identifier: GPL-3.0-or-later
"""
import hashlib
from pathlib import Path

from . import core
from ._nsis_bzip2 import decompress_with_framing

HELPER_SHA256 = 'f6542ed688a9bec3f0bd02bacf01708290aec909784c8018be6a2c8823a307cd'
HELPER_SIZE = 151109784
SERVICE_SHA256 = '2a19ede7f2f450e0d9e1fab717ccadd14b65768d5c7a8fb97681d57c24cfe634'
SERVICE_SIZE = 13364472
SERVICE_OFFSET = 78336 + 145791695
STORED_SIZE = 5168199


def decode_chunks(payload, output_limit):
    """Decode bounded NSISBI u24 chunks containing modified bzip2 streams."""
    result = bytearray()
    pos = 0
    while pos + 3 <= len(payload):
        size = int.from_bytes(payload[pos:pos + 3], 'little')
        pos += 3
        if not size:
            if pos != len(payload):
                raise core.HostError('Unexpected data after NSISBI terminator.')
            return bytes(result)
        if pos + size > len(payload):
            raise core.HostError('Truncated NSISBI chunk.')
        decoded, _ = decompress_with_framing(
            payload[pos:pos + size], max_output_size=output_limit - len(result))
        result.extend(decoded)
        pos += size
        if len(result) > output_limit:
            raise core.HostError('NSISBI output exceeds its declared size.')
    raise core.HostError('Missing NSISBI terminator.')


def extract_service(installer):
    """Return verified service bytes; never execute or modify any environment."""
    with Path(installer).open('rb') as source:
        # Hash and decode from the same file handle. Bound reads before parsing.
        source.seek(0, 2)
        if source.tell() != HELPER_SIZE:
            raise core.HostError('Unsupported Softube helper installer size.')
        source.seek(0)
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
        if digest != HELPER_SHA256:
            raise core.HostError('Unsupported Softube helper installer hash.')
        source.seek(SERVICE_OFFSET)
        framing = int.from_bytes(source.read(8), 'little')
        if framing != (1 << 63) | STORED_SIZE:
            raise core.HostError('Unexpected Softube service framing.')
        payload = source.read(STORED_SIZE)
    result = decode_chunks(payload, SERVICE_SIZE)
    if len(result) != SERVICE_SIZE or hashlib.sha256(result).hexdigest() != SERVICE_SHA256:
        raise core.HostError('Softube service payload verification failed.')
    return result
