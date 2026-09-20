"""The bridge patch series, and the one thing in it that is easy to lose.

The Windows host runs plug-in code on threads yabridge creates. Started the way
Plugg starts it, through Proton inside the runtime container, those threads get
the executable's default stack of one megabyte rather than the Unix stack of
about eight. Plug-ins that work while initialising then overflow it and take
the host process down, and the DAW waits on a process that no longer exists.

Upstream has no reason to set a size, so a future rebase onto upstream would
drop this without anything else noticing.
"""
import json
from pathlib import Path
import re
import unittest

REPO = Path(__file__).resolve().parents[1]
SERIES = json.loads((REPO / 'patches/yabridge-series.json').read_text())
STACK_PATCH = '0005-wine-host-plugin-thread-stack.patch'


class SeriesTests(unittest.TestCase):
    def test_every_patch_in_the_series_exists(self):
        for name in SERIES:
            self.assertTrue((REPO / 'patches' / name).is_file(), name)

    def test_the_series_has_no_duplicates_and_keeps_its_order(self):
        self.assertEqual(len(SERIES), len(set(SERIES)))
        self.assertEqual(SERIES, sorted(SERIES))

    def test_patch_files_are_not_in_the_series_by_accident(self):
        """The Wine patches live beside these and are applied to a different tree."""
        for path in (REPO / 'patches').glob('*.patch'):
            if path.name.startswith('0004-ole32'):
                self.assertNotIn(path.name, SERIES)


class PatchFormatTests(unittest.TestCase):
    """The build applies these with `git apply -p1`, which strips one path component.

    A patch generated without the a/ and b/ prefixes loses "src/" instead, and
    the build fails with "does not exist in index".
    """

    def test_every_patch_uses_the_prefixes_git_apply_expects(self):
        for name in SERIES:
            text = (REPO / 'patches' / name).read_text()
            with self.subTest(patch=name):
                self.assertRegex(text, r'(?m)^--- a/')
                self.assertRegex(text, r'(?m)^\+\+\+ b/')
                for line in text.splitlines():
                    if line.startswith('--- a/') or line.startswith('+++ b/'):
                        self.assertTrue(line[6:].startswith('src/'),
                                        name + ' should patch paths under src/: ' + line)


class PluginThreadStackTests(unittest.TestCase):
    def setUp(self):
        self.patch = (REPO / 'patches' / STACK_PATCH).read_text()

    def test_the_stack_patch_is_applied_to_the_bridge(self):
        self.assertIn(STACK_PATCH, SERIES)

    def test_it_replaces_the_default_stack_size_in_createthread(self):
        self.assertIn('src/wine-host/utils.h', self.patch)
        self.assertIn('-                      0,', self.patch)
        self.assertIn('+                      stack_size,', self.patch)

    def test_the_size_is_larger_than_the_one_megabyte_default(self):
        match = re.search(r'stack_size = (\d+) \* 1024 \* 1024', self.patch)
        self.assertIsNotNone(match, 'the patch should define stack_size in megabytes')
        self.assertGreaterEqual(int(match.group(1)), 8)

    def test_it_records_why_upstream_does_not_need_this(self):
        for phrase in ('start.exe', 'one megabyte', 'diagnostics/host-stack'):
            self.assertIn(phrase, self.patch)

    def test_the_diagnosis_is_kept_with_the_evidence(self):
        notes = (REPO / 'diagnostics/host-stack/README.md').read_text()
        self.assertIn('0x20000-0x120000', notes)
        self.assertIn('patches/0005-wine-host-plugin-thread-stack.patch', notes)


if __name__ == '__main__':
    unittest.main()
