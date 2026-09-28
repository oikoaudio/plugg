"""Reading a Windows file's version resource without running it.

The files here are built in the test: a minimal PE32+ image with one
resource section holding a VS_VERSIONINFO block, laid out the way linkers
write it. No vendor binary is needed.
"""
import struct
import tempfile
import unittest
from pathlib import Path

from plugg import pe_version


def pad(blob):
    return blob + b'\0' * (-len(blob) % 4)


def block(key, value=b'', children=b'', text=False):
    name = pad(b'\0' * 6 + (key + '\0').encode('utf-16-le'))[6:]
    body = name + pad(value) + children
    count = len(value) // 2 if text else len(value)
    return pad(struct.pack('<HHH', 6 + len(name) + len(value) + len(children), count, 1 if text else 0) + body)


def version_resource(strings):
    table = b''.join(block(k, (v + '\0').encode('utf-16-le'), text=True) for k, v in strings.items())
    string_table = block('040904b0', children=table, text=True)
    fixed = struct.pack('<13I', 0xFEEF04BD, 0x10000, *([0] * 11))
    return block('VS_VERSION_INFO', fixed, block('StringFileInfo', children=string_table, text=True))


def pe_with(resource):
    """A PE32+ file whose only section is .rsrc at RVA 0x1000, file offset 0x400."""
    rva, raw = 0x1000, 0x400
    root, level2, level3, entry = 0, 24, 48, 72
    data_at = 88
    tree = bytearray(data_at)
    struct.pack_into('<IIHHHH', tree, root, 0, 0, 0, 0, 0, 1)
    struct.pack_into('<II', tree, root + 16, 16, 0x80000000 | level2)
    struct.pack_into('<IIHHHH', tree, level2, 0, 0, 0, 0, 0, 1)
    struct.pack_into('<II', tree, level2 + 16, 1, 0x80000000 | level3)
    struct.pack_into('<IIHHHH', tree, level3, 0, 0, 0, 0, 0, 1)
    struct.pack_into('<II', tree, level3 + 16, 0x409, entry)
    struct.pack_into('<IIII', tree, entry, rva + data_at, len(resource), 0, 0)
    section = bytes(tree) + resource
    head = bytearray(raw)
    head[:2] = b'MZ'
    struct.pack_into('<I', head, 60, 0x80)
    pe = 0x80
    head[pe:pe + 4] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', head, pe + 4, 0x8664, 1, 0, 0, 0, 240, 0x22)
    optional = pe + 24
    struct.pack_into('<H', head, optional, 0x20b)
    struct.pack_into('<I', head, optional + 108, 16)
    struct.pack_into('<II', head, optional + 112 + 2 * 8, rva, len(section))
    table = optional + 240
    head[table:table + 8] = b'.rsrc\0\0\0'
    struct.pack_into('<IIII', head, table + 8, len(section), rva, len(section), raw)
    return bytes(head) + section


class VersionInfoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_it_reads_the_strings_a_vendor_puts_in_its_file(self):
        path = self.write('soothe64.vst3', pe_with(version_resource(
            {'CompanyName': 'oeksound', 'ProductName': 'soothe', 'FileVersion': '1.3.0'})))
        info = pe_version.version_info(path)
        self.assertEqual(info['CompanyName'], 'oeksound')
        self.assertEqual(info['ProductName'], 'soothe')
        self.assertEqual(info['FileVersion'], '1.3.0')

    def test_a_bundle_is_read_through_its_windows_module(self):
        self.write('Tape.vst3/Contents/x86_64-win/Tape.vst3',
                   pe_with(version_resource({'CompanyName': 'Softube AB'})))
        self.assertEqual(pe_version.version_info(self.root / 'Tape.vst3')['CompanyName'], 'Softube AB')

    def test_files_that_are_not_what_they_claim_give_nothing(self):
        self.assertEqual(pe_version.version_info(self.write('empty.vst3', b'')), {})
        self.assertEqual(pe_version.version_info(self.write('text.vst3', b'not a program' * 10)), {})
        whole = pe_with(version_resource({'CompanyName': 'X'}))
        self.assertEqual(pe_version.version_info(self.write('cut.vst3', whole[:600])), {})
        self.assertEqual(pe_version.version_info(self.root / 'missing.vst3'), {})

    def test_a_program_without_a_resource_section_gives_nothing(self):
        image = bytearray(pe_with(version_resource({'CompanyName': 'X'})))
        struct.pack_into('<II', image, 0x80 + 24 + 112 + 16, 0, 0)
        self.assertEqual(pe_version.version_info(self.write('bare.vst3', bytes(image))), {})


if __name__ == '__main__':
    unittest.main()
