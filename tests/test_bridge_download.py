"""A released package downloads its own bridge once, and only the exact bytes it was released with."""
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from plugg import artifacts, bridge_bundle, bridge_download, core

from webfixture import serve

LOOPBACK = artifacts.Source(('127.0.0.1',), ('http',), any_port=True)
#: The built-in policy, kept before the tests swap in loopback.
RELEASES = artifacts.RUNTIME_RELEASES
VERSION = '0.1.0'
TOP = 'plugg-bridge-' + VERSION + '-x86_64'


def archive(tamper=False):
    """A bridge archive laid out as scripts/build-release-bridge.py packs one."""
    files, contents = {}, {}
    for name in bridge_bundle.ARTIFACTS:
        contents[name] = ('fixture ' + name).encode()
        files[name] = hashlib.sha256(contents[name]).hexdigest()
    contents['build.json'] = json.dumps({'files': files}).encode()
    if tamper:
        contents[bridge_bundle.ARTIFACTS[0]] = b'not what the manifest says'
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w:gz') as tar:
        for name, data in contents.items():
            info = tarfile.TarInfo(TOP + '/' + name)
            info.size, info.mode = len(data), 0o755
            tar.addfile(info, io.BytesIO(data))
    return raw.getvalue()


class BridgeDownloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = SimpleNamespace(root=self.root / 'library')
        self.store.root.mkdir()
        self.pinned = self.root / 'bridge-release.json'
        for patcher in (patch.object(bridge_download, 'PINNED', self.pinned),
                        patch.object(artifacts, 'RUNTIME_RELEASES', LOOPBACK),
                        patch.dict(os.environ, {'XDG_DATA_HOME': str(self.root / 'data')})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def pin(self, base, body, sha256=None):
        self.pinned.write_text(json.dumps({'version': VERSION, 'url': base + '/' + TOP + '.tar.gz',
                                           'sha256': sha256 or hashlib.sha256(body).hexdigest()}))

    def test_a_checkout_has_nothing_pinned_and_says_to_build(self):
        self.assertIsNone(bridge_download.pinned())
        self.assertIsNone(bridge_download.downloaded())
        with self.assertRaisesRegex(core.HostError, 'build-bridge.sh'):
            bridge_download.provision(self.store)

    def test_the_pinned_bridge_is_downloaded_once_and_passes_inspection(self):
        body = archive()
        with serve({'/' + TOP + '.tar.gz': body}) as base:
            self.pin(base, body)
            directory = bridge_download.provision(self.store)
        self.assertEqual(directory.name, TOP)
        self.assertEqual(bridge_download.downloaded(), directory)
        bridge_bundle.inspect(directory)
        # The server is gone: a second call must not need it.
        self.assertEqual(bridge_download.provision(self.store), directory)

    def test_bytes_other_than_the_pinned_ones_are_refused(self):
        body = archive()
        with serve({'/' + TOP + '.tar.gz': body}) as base:
            self.pin(base, body, sha256='0' * 64)
            with self.assertRaisesRegex(core.HostError, 'checksum mismatch'):
                bridge_download.provision(self.store)
        self.assertIsNone(bridge_download.downloaded())

    def test_an_archive_that_disagrees_with_its_manifest_is_not_kept(self):
        body = archive(tamper=True)
        with serve({'/' + TOP + '.tar.gz': body}) as base:
            self.pin(base, body)
            with self.assertRaisesRegex(core.HostError, 'changed artifact'):
                bridge_download.provision(self.store)
        self.assertIsNone(bridge_download.downloaded())

    def test_a_malformed_pin_is_an_error_not_a_silent_fallback(self):
        self.pinned.write_text(json.dumps({'version': VERSION, 'url': 'x', 'sha256': 'short'}))
        with self.assertRaisesRegex(core.HostError, 'malformed'):
            bridge_download.pinned()

    def test_only_this_projects_releases_may_serve_it(self):
        artifacts.validate_entry_url('https://github.com/oikoaudio/plugg/releases/download/v0.1.0/' + TOP + '.tar.gz',
                                     RELEASES)
        with self.assertRaises(ValueError):
            artifacts.validate_entry_url('https://github.com/someone/plugg/releases/download/v0.1.0/x.tar.gz', RELEASES)

if __name__ == '__main__':
    unittest.main()
