"""The AUR packages in packaging/aur and scripts/update-aur.py, which keeps them current."""
import contextlib
import importlib.util
import io
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('update_aur', REPO / 'scripts/update-aur.py')
update_aur = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update_aur)

RELEASE = (REPO / 'packaging/aur/plugg/PKGBUILD').read_text()
GIT = (REPO / 'packaging/aur/plugg-git/PKGBUILD').read_text()
HASH = 'ab' * 32


def array(text, name):
    match = re.search(rf'^{name}=\((.*?)\)', text, re.MULTILINE | re.DOTALL)
    return re.findall(r"'([^']*)'|\"([^\"]*)\"|([^\s'\"]+)", match.group(1)) if match else None


def values(text, name):
    return [next(part for part in item if part) for item in array(text, name)]


def function(text, name):
    body = re.search(rf'^{name}\(\) {{\n(.*?)^}}', text, re.MULTILINE | re.DOTALL).group(1)
    # The one difference: the release unpacks to plugg-<version>, the git
    # package clones to plugg.
    return body.replace('cd "$pkgname-$pkgver"', 'cd plugg')


def srcinfo_values(text, key):
    return re.findall(rf'^\t?{key} = (.*)$', text, re.MULTILINE)


class TagTest(unittest.TestCase):
    def test_a_release_tag_names_its_version(self):
        self.assertEqual(update_aur.version_from_tag('v0.1.0'), '0.1.0')
        self.assertEqual(update_aur.version_from_tag('v0.2.0rc1'), '0.2.0rc1')

    def test_anything_else_is_refused(self):
        for tag in ('0.1.0', 'v', 'v0.1-1', 'v0.1 0', 'refs/tags/v0.1.0', 'vx.1', 'v0.1.0/'):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                update_aur.version_from_tag(tag)


class RewriteTest(unittest.TestCase):
    def test_a_new_version_sets_the_hash_and_starts_at_pkgrel_1(self):
        text = update_aur.set_field(RELEASE, 'pkgrel', '3')
        new = update_aur.rewrite(text, '0.2.0', HASH)
        self.assertEqual(update_aur.read_field(new, 'pkgver'), '0.2.0')
        self.assertEqual(update_aur.read_field(new, 'pkgrel'), '1')
        self.assertEqual(values(new, 'sha256sums'), [HASH, values(RELEASE, 'sha256sums')[1]])

    def test_only_pkgver_and_the_hash_change(self):
        # From pkgrel=1, so the reset to 1 for a new version changes nothing.
        old = update_aur.set_field(RELEASE, 'pkgrel', '1')
        new = update_aur.rewrite(old, '0.2.0', HASH)
        changed = [(a, b) for a, b in zip(old.splitlines(), new.splitlines()) if a != b]
        self.assertEqual(len(old.splitlines()), len(new.splitlines()))
        self.assertEqual([b for _, b in changed], ['pkgver=0.2.0', f"sha256sums=('{HASH}'"])

    def test_the_same_version_keeps_its_pkgrel_unless_one_is_given(self):
        text = update_aur.set_field(RELEASE, 'pkgrel', '2')
        version = update_aur.read_field(text, 'pkgver')
        self.assertEqual(update_aur.read_field(update_aur.rewrite(text, version, HASH), 'pkgrel'), '2')
        self.assertEqual(update_aur.read_field(update_aur.rewrite(text, version, HASH, '3'), 'pkgrel'), '3')

    def test_bad_values_are_refused(self):
        for version, sha256, pkgrel in [('0.2-0', HASH, None), ('0.2.0', 'SKIP', None), ('0.2.0', HASH.upper(), None),
                                        ('0.2.0', HASH[:-1], None), ('0.2.0', HASH, '0'), ('0.2.0', HASH, '1-1')]:
            with self.subTest(version=version, sha256=sha256, pkgrel=pkgrel), self.assertRaises(ValueError):
                update_aur.rewrite(RELEASE, version, sha256, pkgrel)

    def test_a_field_must_be_assigned_exactly_once(self):
        with self.assertRaises(ValueError):
            update_aur.set_field('pkgname=plugg\n', 'pkgver', '1')
        with self.assertRaises(ValueError):
            update_aur.set_field('pkgver=1\npkgver=2\n', 'pkgver', '3')
        with self.assertRaises(ValueError):
            update_aur.set_first_checksum('pkgver=1\n', HASH)

    def test_the_archive_url_is_the_tag_archive(self):
        self.assertEqual(update_aur.archive_url(RELEASE, '0.2.0'),
                         'https://github.com/oikoaudio/plugg/archive/refs/tags/v0.2.0.tar.gz')


class ArchiveTest(unittest.TestCase):
    def archive(self, entries):
        temp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = temp / 'plugg.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            for name, data in entries.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return path

    def test_the_tag_layout_with_the_tag_version_passes(self):
        path = self.archive({'plugg-0.2.0/plugg/__init__.py': b'__version__ = "0.2.0"\n',
                             'plugg-0.2.0/README.md': b''})
        update_aur.check_archive(path, '0.2.0')

    def test_another_version_or_layout_is_refused(self):
        for entries in [{'plugg-0.2.0/plugg/__init__.py': b'__version__ = "0.2.0.dev0"\n'},
                        {'plugg-0.1.0/plugg/__init__.py': b'__version__ = "0.2.0"\n'},
                        {'plugg-0.2.0/plugg/__init__.py': b'__version__ = "0.2.0"\n', 'stray': b''}]:
            with self.subTest(entries=list(entries)), self.assertRaises(ValueError):
                update_aur.check_archive(self.archive(entries), '0.2.0')


class PublishTest(unittest.TestCase):
    def test_the_release_package_is_refused_before_it_has_a_hash(self):
        text = update_aur.set_first_checksum(RELEASE, update_aur.PLACEHOLDER)
        self.assertIn('no source hash', update_aur.publishable('plugg', text, 'info', 'info', ''))
        self.assertIsNone(update_aur.publishable('plugg', update_aur.set_first_checksum(RELEASE, HASH),
                                                 'info', 'info', ''))

    def test_a_stale_srcinfo_or_uncommitted_change_is_refused(self):
        self.assertIn('.SRCINFO', update_aur.publishable('plugg-git', GIT, 'old', 'new', ''))
        self.assertIn('uncommitted', update_aur.publishable('plugg-git', GIT, 'info', 'info', ' M PKGBUILD\n'))
        self.assertIsNone(update_aur.publishable('plugg-git', GIT, 'info', 'info', ''))


class ReleaseCommandTest(unittest.TestCase):
    def setUp(self):
        self.aur = Path(self.enterContext(tempfile.TemporaryDirectory())) / 'aur'
        # Only the package files: a local makepkg run leaves src/ and pkg/ here.
        for package in update_aur.PACKAGES:
            (self.aur / package).mkdir(parents=True)
            for name in ('PKGBUILD', '.SRCINFO'):
                shutil.copy2(REPO / 'packaging/aur' / package / name, self.aur / package / name)
        self.enterContext(patch.object(update_aur, 'AUR', self.aur))
        self.enterContext(patch.object(update_aur, 'srcinfo',
                                       lambda text, container=False: 'pkgver = ' + update_aur.read_field(text, 'pkgver') + '\n'))

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            status = update_aur.main(list(argv))
        return status, out.getvalue()

    def test_a_dry_run_reports_and_writes_nothing(self):
        before = (self.aur / 'plugg/PKGBUILD').read_text(), (self.aur / 'plugg/.SRCINFO').read_text()
        status, out = self.run_main('release', 'v0.2.0', '--sha256', HASH, '--dry-run')
        self.assertEqual(status, 0)
        self.assertIn('+pkgver=0.2.0', out)
        self.assertIn('+pkgver = 0.2.0', out)
        self.assertEqual(before, ((self.aur / 'plugg/PKGBUILD').read_text(), (self.aur / 'plugg/.SRCINFO').read_text()))

    def test_a_release_writes_the_pkgbuild_and_srcinfo(self):
        status, _ = self.run_main('release', 'v0.2.0', '--sha256', HASH)
        self.assertEqual(status, 0)
        text = (self.aur / 'plugg/PKGBUILD').read_text()
        self.assertEqual(update_aur.read_field(text, 'pkgver'), '0.2.0')
        self.assertEqual(update_aur.first_checksum(text), HASH)
        self.assertEqual((self.aur / 'plugg/.SRCINFO').read_text(), 'pkgver = 0.2.0\n')
        self.assertEqual((self.aur / 'plugg-git/PKGBUILD').read_text(), GIT)

    def test_a_bad_tag_is_an_error_not_a_traceback(self):
        status, _ = self.run_main('release', '0.2.0', '--sha256', HASH)
        self.assertEqual(status, 2)


class PackagesTest(unittest.TestCase):
    """The two PKGBUILDs are separate files, because the AUR takes one per
    repository, but they must build the same thing the same way."""

    def test_they_share_everything_but_the_plugg_source(self):
        for name in ('pkgdesc', 'url', '_yabridge'):
            self.assertEqual(update_aur.read_field(RELEASE, name), update_aur.read_field(GIT, name), name)
        for name in ('arch', 'license', 'depends', 'makedepends', 'options'):
            self.assertEqual(values(RELEASE, name), values(GIT, name), name)
        self.assertEqual(values(RELEASE, 'source')[1], values(GIT, 'source')[1])
        self.assertEqual(values(RELEASE, 'sha256sums')[1], values(GIT, 'sha256sums')[1])
        for name in ('prepare', 'build', 'check', 'package'):
            self.assertEqual(function(RELEASE, name), function(GIT, name), name)

    def test_the_bridge_is_built_as_the_hashes_and_the_host_need(self):
        self.assertEqual(values(RELEASE, 'options'), ['!lto', '!debug', '!strip'])

    def test_yabridge_is_the_commit_the_bridge_build_pins(self):
        pinned = re.search(r'^revision=(\w+)$', (REPO / 'scripts/build-bridge.sh').read_text(), re.MULTILINE).group(1)
        self.assertEqual(update_aur.read_field(RELEASE, '_yabridge'), pinned)
        self.assertTrue(values(RELEASE, 'source')[1].endswith('#commit=$_yabridge'))
        self.assertRegex(values(RELEASE, 'sha256sums')[1], r'^[0-9a-f]{64}$')

    def test_the_release_builds_the_tag_archive_pinned_by_hash(self):
        self.assertEqual(values(RELEASE, 'source')[0], '$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz')
        self.assertRegex(update_aur.first_checksum(RELEASE), r'^[0-9a-f]{64}$')
        self.assertEqual(update_aur.read_field(RELEASE, 'pkgname'), 'plugg')
        self.assertEqual(values(RELEASE, 'conflicts'), ['plugg-git'])

    def test_the_git_package_stands_in_for_the_release(self):
        self.assertEqual(update_aur.read_field(GIT, 'pkgname'), 'plugg-git')
        self.assertEqual(values(GIT, 'provides'), ['plugg'])
        self.assertEqual(values(GIT, 'conflicts'), ['plugg'])

    def test_each_srcinfo_matches_its_pkgbuild(self):
        # The full comparison needs makepkg: scripts/update-aur.py srcinfo
        # --check, which packaging/test-aur.py also runs.
        for package, text in (('plugg', RELEASE), ('plugg-git', GIT)):
            info = (REPO / 'packaging/aur' / package / '.SRCINFO').read_text()
            with self.subTest(package=package):
                self.assertEqual(srcinfo_values(info, 'pkgname'), [package])
                self.assertEqual(srcinfo_values(info, 'pkgver'), [update_aur.read_field(text, 'pkgver')])
                self.assertEqual(srcinfo_values(info, 'pkgrel'), [update_aur.read_field(text, 'pkgrel')])
                self.assertEqual(srcinfo_values(info, 'sha256sums'), values(text, 'sha256sums'))
                self.assertEqual(srcinfo_values(info, 'depends'), values(text, 'depends'))


if __name__ == '__main__':
    unittest.main()
