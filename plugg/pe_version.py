"""Read a Windows program's version resource without running it.

Almost every Windows binary carries a VERSIONINFO resource: who made it
(CompanyName), what it is (ProductName, FileDescription) and its version.
Plugg otherwise learns a plug-in's vendor by loading the plug-in, and a
copy-protected plug-in does not load until it is activated, so until then
nothing says whose it is. This reads the same facts straight from the file.

It parses only what it needs: the PE headers, the section table, the
resource directory down to RT_VERSION, and the version block itself. Every
offset is checked against the file, and a file that is not what it claims
gives an empty answer rather than an error.

SPDX-License-Identifier: GPL-3.0-or-later
"""
import mmap
import struct
from pathlib import Path

RT_VERSION = 16
#: Enough for any plug-in or helper; larger files are not mapped at all.
LIMIT = 2 * 1024 ** 3
FIELDS = ('CompanyName', 'ProductName', 'FileDescription', 'ProductVersion', 'FileVersion',
          'OriginalFilename', 'InternalName', 'LegalCopyright')


class Malformed(Exception):
    pass


def module_of(path):
    """The PE file behind a VST3 path: the file itself, or a bundle's Windows module."""
    path = Path(path)
    if path.is_dir():
        found = sorted((path / 'Contents' / 'x86_64-win').glob('*.vst3'))
        return found[0] if found else None
    return path


def version_info(path):
    """{field: text} from the file's version resource; {} when it has none or is not a PE file."""
    module = module_of(path)
    if module is None:
        return {}
    try:
        size = module.stat().st_size
        if not 64 <= size <= LIMIT:
            return {}
        with module.open('rb') as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
            return _read(data)
    except (OSError, ValueError, Malformed, struct.error, UnicodeDecodeError):
        return {}


def _unpack(fmt, data, offset):
    if offset < 0 or offset + struct.calcsize(fmt) > len(data):
        raise Malformed('read past the end of the file')
    return struct.unpack_from(fmt, data, offset)


def _read(data):
    if data[:2] != b'MZ':
        return {}
    pe = _unpack('<I', data, 60)[0]
    if bytes(data[pe:pe + 4]) != b'PE\0\0':
        return {}
    sections, optional_size = _unpack('<H', data, pe + 6)[0], _unpack('<H', data, pe + 20)[0]
    optional = pe + 24
    magic = _unpack('<H', data, optional)[0]
    directories = optional + {0x10b: 96, 0x20b: 112}.get(magic, -1)
    if directories < optional:
        return {}
    count = _unpack('<I', data, directories - 4)[0]
    if count <= 2:
        return {}
    resource_rva, resource_size = _unpack('<II', data, directories + 2 * 8)
    if not resource_rva or not resource_size:
        return {}
    table = optional + optional_size
    spans = []
    for index in range(min(sections, 96)):
        header = table + index * 40
        virtual_size, virtual_address, raw_size, raw_pointer = _unpack('<IIII', data, header + 8)
        spans.append((virtual_address, max(virtual_size, raw_size), raw_pointer))

    def offset(rva):
        for start, length, raw in spans:
            if start <= rva < start + length:
                return raw + rva - start
        raise Malformed('address outside every section')

    root = offset(resource_rva)
    block = _find_version(data, root)
    if block is None:
        return {}
    rva, length = _unpack('<II', data, block)
    start = offset(rva)
    if length > 1024 * 1024 or start + length > len(data):
        return {}
    return _strings(bytes(data[start:start + length]))


def _entries(data, directory):
    named, ids = _unpack('<HH', data, directory + 12)
    for index in range(min(named + ids, 4096)):
        name, target = _unpack('<II', data, directory + 16 + index * 8)
        yield name, target


def _find_version(data, root):
    """The data entry of the first RT_VERSION resource: type, then name, then language."""
    for name, target in _entries(data, root):
        if name == RT_VERSION and target & 0x80000000:
            level = root + (target & 0x7fffffff)
            for depth in range(2):
                entries = list(_entries(data, level))
                if not entries:
                    return None
                target = entries[0][1]
                if depth == 1:
                    return None if target & 0x80000000 else root + target
                if not target & 0x80000000:
                    return None
                level = root + (target & 0x7fffffff)
    return None


def _align(value):
    return (value + 3) & ~3


def _key(blob, offset, end):
    """A null-terminated UTF-16 key, and where the padded value after it starts."""
    stop = offset
    while stop + 1 < end and blob[stop:stop + 2] != b'\0\0':
        stop += 2
    return blob[offset:stop].decode('utf-16-le'), _align(stop + 2)


def _blocks(blob, offset, end):
    """(key, value bytes, children start, children end, text?) for each block in blob[offset:end]."""
    while offset + 6 <= end:
        length, value_length, kind = struct.unpack_from('<HHH', blob, offset)
        if length < 6 or offset + length > end:
            return
        key, value = _key(blob, offset + 6, offset + length)
        width = value_length * 2 if kind == 1 else value_length
        yield key, blob[value:value + width], _align(value + width), offset + length, kind == 1
        offset = _align(offset + length)


def _strings(blob):
    found = {}
    for key, _, children, end, _ in _blocks(blob, 0, len(blob)):
        if key != 'VS_VERSION_INFO':
            continue
        for name, _, tables, tables_end, _ in _blocks(blob, children, end):
            if name != 'StringFileInfo':
                continue
            for _, _, strings, strings_end, _ in _blocks(blob, tables, tables_end):
                for field, value, _, _, is_text in _blocks(blob, strings, strings_end):
                    if is_text and field in FIELDS and field not in found:
                        text = value.decode('utf-16-le').split('\0', 1)[0].strip()
                        if text:
                            found[field] = text
    return found
