import hashlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from plugg import artifacts, core

from webfixture import serve

#: Loopback policy for tests. No built-in source permits plain HTTP.
LOOPBACK = artifacts.Source(('127.0.0.1',), ('http',), any_port=True)


def urlhost(base):
    return urlsplit(base).hostname


class ArtifactCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = SimpleNamespace(root=self.root / 'store')
        self.store.root.mkdir()

    def fetch(self, asset, source=LOOPBACK):
        return artifacts.fetch(self.store, asset, lambda _: None, lambda: None, source)

    def test_same_filename_different_versions_keep_distinct_verified_paths(self):
        first, second = b'first', b'second'
        with serve({'/a/setup.exe': first, '/b/setup.exe': second}) as base:
            def asset(path, body):
                return {'url': base + path, 'sha256': hashlib.sha256(body).hexdigest()}
            old_path = self.fetch(asset('/a/setup.exe', first))
            new_path = self.fetch(asset('/b/setup.exe', second))
            self.assertNotEqual(old_path, new_path)
            self.assertEqual(old_path.read_bytes(), first)
            self.assertEqual(new_path.read_bytes(), second)
            self.assertEqual(self.fetch(asset('/a/setup.exe', first)), old_path)

    def test_legacy_cache_is_copied_without_network_or_removal(self):
        cache = self.store.root / 'downloads'
        cache.mkdir()
        legacy = cache / 'setup.exe'
        legacy.write_bytes(b'cached')
        asset = {'url': 'http://127.0.0.1:1/setup.exe', 'sha256': hashlib.sha256(b'cached').hexdigest()}
        with patch('plugg.artifacts.open_verified', side_effect=AssertionError('network')):
            target = self.fetch(asset)
        self.assertNotEqual(target, legacy)
        self.assertEqual(target.read_bytes(), b'cached')
        self.assertEqual(legacy.read_bytes(), b'cached')

    def test_invalid_hash_cannot_choose_a_cache_path(self):
        asset = {'url': 'http://127.0.0.1:1/setup.exe', 'sha256': '../invalid'}
        with self.assertRaisesRegex(core.HostError, 'exact SHA-256'):
            self.fetch(asset)
        self.assertFalse((self.store.root / 'downloads').exists())


class DownloadPolicyTests(unittest.TestCase):
    """The allowlist is the only control over whose bytes may later be executed."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = SimpleNamespace(root=Path(temporary.name) / 'store')
        self.store.root.mkdir()

    def fetch(self, url, body, source=LOOPBACK):
        return artifacts.fetch(self.store, {'url': url, 'sha256': hashlib.sha256(body).hexdigest()},
                               lambda _: None, lambda: None, source)

    def cached(self):
        cache = self.store.root / 'downloads'
        return sorted(path.name for path in cache.glob('*')) if cache.exists() else []

    def test_every_built_in_source_is_https_only_on_its_default_port(self):
        for source in (artifacts.MICROSOFT_DOWNLOADS, artifacts.RUNTIME_RELEASES,
                       artifacts.ARCHIVE_PACKAGES):
            self.assertEqual(source.schemes, ('https',))
            self.assertFalse(source.any_port)

    def test_runtime_download_entry_is_project_scoped_and_cdn_is_redirect_only(self):
        source = artifacts.RUNTIME_RELEASES
        artifacts.validate_entry_url('https://github.com/Open-Wine-Components/umu-proton/releases/download/v1/runtime.tar.gz', source)
        artifacts.validate_url('https://release-assets.githubusercontent.com/asset', source)
        for url in ('https://github.com/someone/anything/releases/download/v1/runtime.tar.gz',
                    'https://release-assets.githubusercontent.com/asset',
                    'https://github.com/Open-Wine-Components/umu-proton/releases/download/%2e%2e/x',
                    'https://repo.steampowered.com/unrelated/file'):
            with self.assertRaises(ValueError):
                artifacts.validate_entry_url(url, source)

    def test_a_recipe_may_only_name_microsoft_download_hosts(self):
        for url in ('https://evil.test/vc.exe',
                    'http://download.microsoft.com/vc.exe',
                    'https://download.microsoft.com@evil.test/vc.exe',
                    'https://download.microsoft.com.evil.test/vc.exe',
                    'https://download.microsoft.com./vc.exe',
                    'https://download.microsoft.com/vc.exe#@evil.test',
                    'https://user:pass@download.microsoft.com/vc.exe',
                    'file:///etc/passwd',
                    'ftp://download.microsoft.com/vc.exe',
                    'https://download.microsoft.com:8443/vc.exe'):
            with self.assertRaises(ValueError, msg=url):
                artifacts.validate_url(url, artifacts.MICROSOFT_DOWNLOADS)

    def test_fetch_refuses_a_url_its_source_does_not_allow(self):
        with self.assertRaises(core.HostError):
            self.fetch('file:///etc/passwd', b'x')
        self.assertEqual(self.cached(), [])

    def test_a_redirect_off_the_allowed_host_is_refused(self):
        payload = b'attacker payload'
        with serve({'/evil.exe': payload}, host='127.0.0.2') as elsewhere:
            with serve({}, redirects={'/vc.exe': elsewhere + '/evil.exe'}) as base:
                # The declared host is allowed; the redirect target is not.
                source = artifacts.Source((urlhost(base),), ('http',), any_port=True)
                with self.assertRaises(Exception):
                    self.fetch(base + '/vc.exe', payload, source)
        self.assertEqual(self.cached(), [])

    def test_a_redirect_to_an_allowed_host_still_works(self):
        payload = b'legitimate payload'
        with serve({'/real.exe': payload}) as base:
            with serve({}, redirects={'/vc.exe': base + '/real.exe'}) as front:
                source = artifacts.Source((urlhost(base), urlhost(front)), ('http',), any_port=True)
                target = self.fetch(front + '/vc.exe', payload, source)
        self.assertEqual(target.read_bytes(), payload)

    def test_a_redirect_downgrading_the_scheme_is_refused(self):
        handler = artifacts._AllowedRedirects(artifacts.Source(('127.0.0.1',), ('https',), any_port=True))
        with self.assertRaises(Exception):
            handler.redirect_request(None, None, 302, 'Found', {}, 'http://127.0.0.1/x')

    def test_only_a_mirror_pool_may_land_on_an_unlisted_host(self):
        # MSYS2 publishes one URL that redirects to a different mirror on each
        # request, with no list anyone could enumerate. Refusing that refused
        # the only URL the project publishes -- and it is the pinned SHA-256,
        # not the hostname, that decides whether the bytes are used.
        payload = b'package bytes'
        with serve({'/pkg.zst': payload}, host='127.0.0.2') as mirror:
            with serve({}, redirects={'/pkg.zst': mirror + '/pkg.zst'}) as front:
                strict = artifacts.Source((urlhost(front),), ('http',), any_port=True)
                pool = strict._replace(mirrors=True)
                with self.assertRaises(Exception):
                    self.fetch(front + '/pkg.zst', payload, strict)
                target = self.fetch(front + '/pkg.zst', payload, pool)
        self.assertEqual(target.read_bytes(), payload)

    def test_a_mirror_redirect_still_obeys_every_other_rule(self):
        # Only the host list is relaxed. Scheme, port and credentials are not.
        pool = artifacts.Source(('127.0.0.1',), ('https',), mirrors=True)
        handler = artifacts._AllowedRedirects(pool)
        for target in ('http://mirror.test/x', 'https://user:pass@mirror.test/x',
                       'https://mirror.test:8443/x', 'ftp://mirror.test/x'):
            with self.assertRaises(Exception, msg=target):
                handler.redirect_request(None, None, 302, 'Found', {}, target)

    def test_the_packages_are_the_only_source_that_follows_mirrors(self):
        for source in (artifacts.MICROSOFT_DOWNLOADS, artifacts.RUNTIME_RELEASES):
            self.assertFalse(source.mirrors, source.describe())
        self.assertTrue(artifacts.ARCHIVE_PACKAGES.mirrors)

    def test_mismatched_bytes_are_never_cached(self):
        with serve({'/vc.exe': b'not what was pinned'}) as base:
            with self.assertRaisesRegex(core.HostError, 'checksum mismatch'):
                self.fetch(base + '/vc.exe', b'what was pinned')
        self.assertEqual(self.cached(), [])


if __name__ == '__main__':
    unittest.main()
