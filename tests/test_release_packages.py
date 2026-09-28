"""The .deb/.rpm/tarball builder: version conversion, staging tree and refusals.

Nothing here runs nfpm or a package manager; packaging/test-packages.py does
that in containers.
"""
import functools
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import zipfile

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_release_packages', REPO / 'scripts/build-release-packages.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

from plugg import bridge_bundle, powershell_component  # noqa: E402

VERSION = '1.2.0rc1'

#: Ascending in PEP 440; the converted versions must sort the same way in dpkg and rpm.
ORDERED = ['0.1.0.dev0', '0.1.0a1.dev0', '0.1.0a1', '0.1.0b1', '0.1.0rc1.dev1', '0.1.0rc1',
           '0.1.0rc1.post1', '0.1.0', '0.1.0.post1.dev0', '0.1.0.post1', '0.1.1.dev0', '0.1.1',
           '0.1.10', '0.2.0', '1.0.0']


def dpkg_compare(a, b):
    """dpkg's upstream-version comparison (verrevcmp in lib/dpkg/version.c)."""
    def order(c):
        if c.isdigit():
            return 0
        if c.isalpha():
            return ord(c)
        if c == '~':
            return -1
        return ord(c) + 256 if c else 0
    i = j = 0
    while i < len(a) or j < len(b):
        difference = 0
        while (i < len(a) and not a[i].isdigit()) or (j < len(b) and not b[j].isdigit()):
            ac = order(a[i]) if i < len(a) else 0
            bc = order(b[j]) if j < len(b) else 0
            if ac != bc:
                return ac - bc
            i, j = i + 1, j + 1
        while i < len(a) and a[i] == '0':
            i += 1
        while j < len(b) and b[j] == '0':
            j += 1
        while i < len(a) and a[i].isdigit() and j < len(b) and b[j].isdigit():
            if not difference:
                difference = ord(a[i]) - ord(b[j])
            i, j = i + 1, j + 1
        if i < len(a) and a[i].isdigit():
            return 1
        if j < len(b) and b[j].isdigit():
            return -1
        if difference:
            return difference
    return 0


def rpm_compare(a, b):
    """rpm's version comparison (rpmvercmp in rpmio/rpmvercmp.c), tilde and caret included."""
    if a == b:
        return 0
    i = j = 0
    while i < len(a) or j < len(b):
        while i < len(a) and not a[i].isalnum() and a[i] not in '~^':
            i += 1
        while j < len(b) and not b[j].isalnum() and b[j] not in '~^':
            j += 1
        if (i < len(a) and a[i] == '~') or (j < len(b) and b[j] == '~'):
            if not (i < len(a) and a[i] == '~'):
                return 1
            if not (j < len(b) and b[j] == '~'):
                return -1
            i, j = i + 1, j + 1
            continue
        if (i < len(a) and a[i] == '^') or (j < len(b) and b[j] == '^'):
            if i == len(a):
                return -1
            if j == len(b):
                return 1
            if a[i] != '^':
                return 1
            if b[j] != '^':
                return -1
            i, j = i + 1, j + 1
            continue
        if not (i < len(a) and j < len(b)):
            break
        pattern = r'[0-9]+' if a[i].isdigit() else r'[A-Za-z]+'
        one = re.match(pattern, a[i:]).group()
        two = re.match(pattern, b[j:])
        if not two:
            return 1 if a[i].isdigit() else -1
        two = two.group()
        i, j = i + len(one), j + len(two)
        if a[i - len(one)].isdigit():
            one, two = one.lstrip('0'), two.lstrip('0')
            if len(one) != len(two):
                return 1 if len(one) > len(two) else -1
        if one != two:
            return 1 if one > two else -1
    if i >= len(a) and j >= len(b):
        return 0
    return -1 if i >= len(a) else 1


class VersionTest(unittest.TestCase):
    def test_conversions(self):
        for pep440, expected in [('0.1.0', '0.1.0'), ('0.1.0.dev0', '0.1.0~~dev0'), ('0.1.0a1', '0.1.0~a1'),
                                 ('0.1.0b2', '0.1.0~b2'), ('0.1.0rc1', '0.1.0~rc1'),
                                 ('0.1.0rc1.dev3', '0.1.0~rc1~dev3'), ('0.1.0.post2', '0.1.0+post2'),
                                 ('0.1.0.post2.dev1', '0.1.0+post2~dev1'), ('2024.10', '2024.10')]:
            self.assertEqual(build.package_version(pep440), expected, pep440)

    def test_dpkg_and_rpm_order_them_as_pep_440_does(self):
        converted = [build.package_version(version) for version in ORDERED]
        for compare in (dpkg_compare, rpm_compare):
            shuffled = list(reversed(converted))
            self.assertEqual(sorted(shuffled, key=functools.cmp_to_key(compare)), converted, compare.__name__)

    def test_the_comparators_agree_with_known_results(self):
        # From dpkg's and rpm's own test suites.
        self.assertLess(dpkg_compare('1.0~rc1', '1.0'), 0)
        self.assertLess(dpkg_compare('1.0~~', '1.0~~a'), 0)
        self.assertLess(dpkg_compare('1.0', '1.0.1'), 0)
        self.assertGreater(dpkg_compare('1.0a', '1.0'), 0)
        self.assertLess(rpm_compare('1.0~rc1', '1.0'), 0)
        self.assertLess(rpm_compare('1.0~rc1~git123', '1.0~rc1'), 0)
        self.assertGreater(rpm_compare('1.0^', '1.0'), 0)
        self.assertLess(rpm_compare('1.0a', '1.0.1'), 0)
        self.assertEqual(rpm_compare('1.0', '1.0'), 0)

    def test_epochs_local_versions_and_unnormalised_versions_are_refused(self):
        for version in ('1!0.1.0', '0.1.0+local', 'v0.1.0', '0.1.0-rc1', '0.1.0.RC1', '0.1.0c1', ''):
            with self.assertRaises(ValueError, msg=version):
                build.package_version(version)

    def test_the_declared_version_converts(self):
        build.package_version(build.declared_version())


class StagingTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def wheel(self, extra=None):
        path = self.root / ('plugg-' + VERSION + '-py3-none-any.whl')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('plugg/__init__.py', '__version__ = "' + VERSION + '"\n')
            archive.writestr('plugg/__main__.py', 'print("plugg")\n')
            archive.writestr('plugg/recipes/community/example.toml', 'schema = 1\n')
            archive.writestr('plugg-' + VERSION + '.dist-info/METADATA', 'Name: plugg\n')
            for name, data in (extra or {}).items():
                archive.writestr(name, data)
        return path

    def bridge(self, extra=None, version=VERSION):
        top = 'plugg-bridge-' + version + '-x86_64'
        files = {name: ('binary ' + name).encode() for name in bridge_bundle.ARTIFACTS}
        files['build.json'] = json.dumps({'files': {name: hashlib.sha256(data).hexdigest()
                                                    for name, data in files.items()}}).encode()
        files['NOTICE.md'] = b'notice\n'
        files['licenses/asio/LICENSE'] = b'licence\n'
        files.update(extra or {})
        path = self.root / (top + '.tar.gz')
        with tarfile.open(path, 'w:gz') as archive:
            for name, data in files.items():
                info = tarfile.TarInfo(name if name.startswith('../') else top + '/' + name)
                info.size = len(data)
                info.mode = 0o755 if name in ('plugg-scan', 'libyabridge-vst3.so') else 0o644
                archive.addfile(info, io.BytesIO(data))
        return path

    def forwarder(self, tamper=False):
        path = self.root / 'forwarder'
        path.mkdir()
        files = {}
        for name in build.FORWARDER_FILES:
            (path / name).write_bytes(name.encode())
            files[name] = hashlib.sha256(name.encode()).hexdigest()
        (path / 'build.json').write_text(json.dumps({
            'source_sha256': powershell_component.FORWARDER_SOURCE_SHA256, 'compiler': 'go test', 'files': files}))
        if tamper:
            (path / 'powershell64.exe').write_bytes(b'changed')
        return path

    def stage(self, **inputs):
        staging = self.root / 'staging'
        tree = build.stage(REPO, inputs.get('wheel') or self.wheel(), inputs.get('bridge') or self.bridge(),
                           inputs.get('forwarder') or self.forwarder(), VERSION, staging)
        return staging, tree

    def test_the_tree_has_the_decided_layout(self):
        staging, tree = self.stage()
        names = {path.relative_to(tree).as_posix() for path in tree.rglob('*') if path.is_file()}
        self.assertEqual(names, {
            'usr/bin/plugg',
            'usr/lib/plugg/app/plugg/__init__.py', 'usr/lib/plugg/app/plugg/__main__.py',
            'usr/lib/plugg/app/plugg/recipes/community/example.toml',
            *('usr/lib/plugg/bridge/' + name for name in bridge_bundle.ARTIFACTS),
            'usr/lib/plugg/bridge/build.json', 'usr/lib/plugg/bridge/NOTICE.md',
            'usr/lib/plugg/bridge/licenses/asio/LICENSE',
            *('usr/lib/plugg/powershell-forwarder/' + name for name in build.FORWARDER_FILES),
            'usr/lib/plugg/powershell-forwarder/build.json',
            'usr/share/applications/com.oikoaudio.Plugg.desktop',
            'usr/share/doc/plugg/README.md', 'usr/share/doc/plugg/third-party.md',
            'usr/share/licenses/plugg/LICENSE'})
        self.assertEqual((tree / 'usr/bin/plugg').stat().st_mode & 0o777, 0o755)
        self.assertEqual((tree / 'usr/lib/plugg/bridge/plugg-scan').stat().st_mode & 0o777, 0o755)
        self.assertEqual((tree / 'usr/lib/plugg/bridge/NOTICE.md').stat().st_mode & 0o777, 0o644)
        self.assertEqual((tree / 'usr/lib/plugg/powershell-forwarder/powershell32.exe').stat().st_mode & 0o777, 0o755)
        self.assertEqual((tree / 'usr/share/licenses/plugg/LICENSE').read_bytes(), (REPO / 'LICENSE').read_bytes())
        copyright = (staging / 'deb/copyright').read_bytes()
        self.assertTrue(copyright.endswith((REPO / 'LICENSE').read_bytes()))
        self.assertIn(b'tag v' + VERSION.encode(), copyright)
        bridge_bundle.inspect(tree / 'usr/lib/plugg/bridge')

    def test_every_file_the_nfpm_config_names_is_staged(self):
        staging, _ = self.stage()
        config = (REPO / 'packaging/nfpm.yaml').read_text()
        sources = re.findall(r'^\s+(?:- )?src: (\S+)$', config, re.M)
        scripts = re.findall(r'^\s+(?:postinstall|preremove): (\S+)$', config, re.M)
        self.assertIn('tree/usr/lib/plugg', sources)
        self.assertEqual(len(scripts), 2)
        for source in sources + scripts:
            self.assertTrue((staging / source).exists(), source)
        for script in scripts:
            self.assertEqual((staging / script).stat().st_mode & 0o777, 0o755)

    def test_the_launcher_starts_the_staged_app(self):
        _, tree = self.stage()
        python = shutil.which('python3', path='/usr/bin')
        if python is None:
            self.skipTest('no /usr/bin/python3')
        launcher = (tree / 'usr/bin/plugg').read_text()
        self.assertTrue(launcher.startswith('#!/bin/sh\n'))
        local = launcher.replace('"/usr/lib/plugg/app"', json.dumps(str(tree / 'usr/lib/plugg/app')))
        result = subprocess.run(['sh', '-c', local, 'plugg'], capture_output=True, text=True, cwd=self.root)
        self.assertEqual((result.returncode, result.stdout), (0, 'plugg\n'), result.stderr)

    def test_the_tarball_holds_the_tree_and_install_notes_and_is_repeatable(self):
        _, tree = self.stage()
        first, second = self.root / 'one', self.root / 'two'
        first.mkdir()
        second.mkdir()
        one = build.tarball(tree, VERSION, first, 1700000000)
        two = build.tarball(tree, VERSION, second, 1700000000)
        self.assertEqual(one.name, 'plugg-' + VERSION + '-x86_64.tar.gz')
        self.assertEqual(one.read_bytes(), two.read_bytes())
        with tarfile.open(one) as archive:
            members = {member.name: member for member in archive.getmembers()}
        top = 'plugg-' + VERSION + '-x86_64'
        self.assertIn(top + '/INSTALL.md', members)
        self.assertIn(top + '/usr/lib/plugg', members)
        self.assertTrue(members[top + '/usr/lib/plugg'].isdir())
        self.assertEqual(members[top + '/usr/bin/plugg'].mode, 0o755)
        self.assertTrue(all(name == top or name.startswith(top + '/') for name in members))
        self.assertTrue(all(member.mtime == 1700000000 and member.uid == 0 for member in members.values()))

    def test_a_wheel_with_files_outside_the_package_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'Unexpected path'):
            self.stage(wheel=self.wheel({'sitecustomize.py': 'import os\n'}))

    def test_a_wheel_of_another_version_is_refused(self):
        other = self.wheel().rename(self.root / 'plugg-9.9.9-py3-none-any.whl')
        with self.assertRaisesRegex(ValueError, 'Expected the wheel'):
            self.stage(wheel=other)

    def test_a_bridge_archive_with_a_path_outside_its_directory_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'Unexpected path'):
            self.stage(bridge=self.bridge({'../escape': b'x'}))

    def test_a_bridge_that_disagrees_with_its_manifest_is_refused(self):
        with self.assertRaisesRegex(Exception, 'plugg-scan'):
            self.stage(bridge=self.bridge({'plugg-scan': b'changed'}))

    def test_a_bridge_archive_that_does_not_match_its_checksum_file_is_refused(self):
        bridge = self.bridge()
        bridge.with_name(bridge.name + '.sha256').write_text('0' * 64 + '  ' + bridge.name + '\n')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.stage(bridge=bridge)

    def test_a_bridge_of_another_version_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'Expected the bridge archive'):
            self.stage(bridge=self.bridge(version='9.9.9'))

    def test_a_changed_forwarder_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'powershell64.exe'):
            self.stage(forwarder=self.forwarder(tamper=True))


if __name__ == '__main__':
    unittest.main()
