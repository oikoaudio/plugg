"""The bridge patch series, and the build rule that is easy to lose.

The Windows host must be built with yabridge's own flags. A packaging
environment exports the flags of the machine it runs on, Meson passes them to
the Wine cross build, and a host compiled with `-march=native` overflows its
stack while a plug-in initialises. Every bridged plug-in then dies in the DAW
with nothing but a timeout. The build script clears those flags, and nothing
else would notice if that line went missing.
"""
import json
from pathlib import Path
import re
import unittest

REPO = Path(__file__).resolve().parents[1]
SERIES = json.loads((REPO / 'patches/yabridge-series.json').read_text())


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


class HostBuildFlagsTests(unittest.TestCase):
    def setUp(self):
        self.script = (REPO / 'scripts/build-bridge.sh').read_text()

    def test_the_build_clears_the_environment_flags_before_configuring(self):
        match = re.search(r'(?m)^unset (.*)$', self.script)
        self.assertIsNotNone(match, 'build-bridge.sh should unset the environment flags')
        for variable in ('CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS'):
            self.assertIn(variable, match.group(1).split())
        self.assertLess(match.start(), self.script.index('meson setup'),
                        'the flags must be cleared before Meson records them')

    def test_a_build_directory_configured_with_march_is_refused(self):
        self.assertIn("grep -q -- '-march=' \"$build_dir/compile_commands.json\"", self.script)
        self.assertLess(self.script.index("'-march='"), self.script.index('ninja -C'))

    def test_the_manifest_records_the_arguments_each_build_used(self):
        self.assertIn("'arguments': arguments", (REPO / 'scripts/bridge-manifest.py').read_text())

    def test_the_diagnosis_is_kept_with_the_evidence(self):
        notes = (REPO / 'diagnostics/host-stack/README.md').read_text()
        self.assertIn('0x20000-0x120000', notes)
        self.assertIn('-march=native', notes)
        self.assertIn('scripts/build-bridge.sh', notes)


if __name__ == '__main__':
    unittest.main()
