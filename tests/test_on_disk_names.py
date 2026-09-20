"""The names written on disk.

What the code writes into an environment, a
published plug-in or the DAW's scan folder exists in installations that
already work, one of them is part of a recorded licensing identity, and a
plug-in that stops being found is a project that stops opening. Each name is
asserted here with the cost of changing it, so a rename has to come
with a migration rather than a search-and-replace.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'plugg'

NAMES = {
    '.plugg-runtime': 'marks the runtime in each prefix, and is read back as part of the licensing identity',
    '.plugg-managed': 'marks a native directory this project manages',
    'plugg.json': 'the manifest inside every published plug-in bundle',
    'plugg-scan': 'one of the six built bridge artifacts, named in every build manifest',
    'drive_c/Plugg': 'the directory inside each prefix that holds our launch scripts and tools',
    '.vst3/plugg': 'the DAW publication folder, which the DAW scans',
    'data_home / "plugg"': 'the library directory',
}


class OnDiskNames(unittest.TestCase):
    def test_every_on_disk_name_is_still_written(self):
        text = '\n'.join(path.read_text(encoding='utf-8') for path in sorted(PACKAGE.glob('*.py')))
        for name, why in NAMES.items():
            with self.subTest(name=name):
                self.assertIn(name, text, name + ' is ' + why +
                              '; it cannot be renamed without a migration for existing libraries')


if __name__ == '__main__':
    unittest.main()
