import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugg import archive_component, core


class ArchiveComponentTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.prefix = self.root / 'environment/prefix'
        (self.prefix / 'drive_c').mkdir(parents=True)
        self.destination = self.prefix / 'drive_c/Plugg/Tools/Archive'
        self.packages = {'archive': {'mingw64/bin/bsdtar.exe': b'tar',
                                     'mingw64/share/licenses/archive/LICENSE': b'notice'},
                         'dependency': {'mingw64/bin/support.dll': b'support'}}
        self.assets = [{'package': name} for name in self.packages]

    def install(self):
        def unpack(name, destination):
            for relative, contents in self.packages[name].items():
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents)
        with patch('plugg.artifacts.fetch', side_effect=lambda store, asset, *args: asset['package']), \
                patch('plugg.artifacts.unpack', side_effect=unpack):
            archive_component.install(None, self.prefix, self.assets, lambda _: None, lambda: None)

    def test_complete_component_and_repeat_preserve_notices_and_record(self):
        self.install()
        self.install()
        self.assertEqual((self.destination / 'tar.exe').read_bytes(), b'tar')
        self.assertEqual((self.destination / 'support.dll').read_bytes(), b'support')
        self.assertEqual((self.prefix.parent / 'component-licenses/archive/LICENSE').read_bytes(), b'notice')
        self.assertEqual(json.loads((self.prefix.parent / 'archive-components.json').read_text()), self.assets)

    def test_late_existing_conflict_does_not_install_earlier_package(self):
        self.destination.mkdir(parents=True)
        (self.destination / 'support.dll').write_bytes(b'existing')
        with self.assertRaisesRegex(core.HostError, 'Conflicting installed'):
            self.install()
        self.assertFalse((self.destination / 'bsdtar.exe').exists())
        self.assertFalse((self.prefix.parent / 'archive-components.json').exists())
        self.assertEqual((self.destination / 'support.dll').read_bytes(), b'existing')

    def test_package_conflict_and_missing_executable_do_not_write(self):
        self.packages['dependency']['mingw64/bin/bsdtar.exe'] = b'conflict'
        with self.assertRaisesRegex(core.HostError, 'Conflicting archive-tool'):
            self.install()
        self.assertFalse(self.destination.exists())
        del self.packages['dependency']['mingw64/bin/bsdtar.exe']
        del self.packages['archive']['mingw64/bin/bsdtar.exe']
        with self.assertRaisesRegex(core.HostError, 'does not provide'):
            self.install()
        self.assertFalse(self.destination.exists())

    def test_external_destination_symlink_is_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.prefix / 'drive_c/Plugg').symlink_to(outside)
        with self.assertRaisesRegex(core.HostError, 'escapes'):
            self.install()
        self.assertEqual(list(outside.iterdir()), [])
