import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from plugg import bridge_bundle, core


class BridgeSelectionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = self.root / 'bridge'
        self.bundle.mkdir()
        files = {}
        for name in bridge_bundle.ARTIFACTS:
            content = ('fixture ' + name).encode()
            (self.bundle / name).write_bytes(content)
            files[name] = hashlib.sha256(content).hexdigest()
        (self.bundle / 'build.json').write_text(json.dumps({'files': files}))

    def create(self):
        return core.Store(self.root / 'library', self.root / 'published', self.bundle)

    def test_selection_survives_worker_reopening_without_cli_option(self):
        store = self.create()
        self.assertEqual(store.bridge_source(), self.bundle)
        reopened = core.Store(store.root)
        self.assertEqual(reopened.bridge_source(), self.bundle)
        self.assertIsNone(core.doctor(reopened)['bridge_error'])

    def test_changed_artifact_and_rewritten_manifest_are_rejected(self):
        store = self.create()
        name = bridge_bundle.ARTIFACTS[0]
        (self.bundle / name).write_bytes(b'changed')
        with self.assertRaisesRegex(core.HostError, 'changed artifact'):
            store.bridge()
        self.assertIsNotNone(core.doctor(store)['bridge_error'])
        manifest = json.loads((self.bundle / 'build.json').read_text())
        manifest['files'][name] = hashlib.sha256(b'changed').hexdigest()
        (self.bundle / 'build.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(core.HostError, 'manifest changed'):
            core.Store(store.root).bridge()

    def test_a_host_built_for_the_packagers_cpu_is_refused(self):
        manifest = json.loads((self.bundle / 'build.json').read_text())
        manifest['build_inputs'] = {'arguments': {'host.cpp_args': ['-O3', '-march=native'], 'build.cpp_args': ['-march=native']}}
        (self.bundle / 'build.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(core.HostError, '-march=native'):
            self.create()
        manifest['build_inputs']['arguments']['host.cpp_args'] = ['-O3']
        (self.bundle / 'build.json').write_text(json.dumps(manifest))
        self.assertEqual(self.create().bridge_source(), self.bundle)

    def test_failed_selection_does_not_create_library(self):
        (self.bundle / 'COPYING.yabridge').unlink()
        with self.assertRaises(core.HostError):
            self.create()
        self.assertFalse((self.root / 'library').exists())

    def test_explicit_selection_cannot_change_existing_library(self):
        store = self.create()
        before = (store.root / 'settings.json').read_bytes()
        with self.assertRaisesRegex(core.HostError, 'already has a bridge selection'):
            core.Store(store.root, bridge_dir=self.root / 'other')
        self.assertEqual((store.root / 'settings.json').read_bytes(), before)
        legacy = core.Store(self.root / 'legacy', self.root / 'old-publication')
        with self.assertRaises(core.HostError):
            core.Store(legacy.root, bridge_dir=self.bundle)
        self.assertIsNone(core.Store(legacy.root).bridge_selection)

    def test_linked_artifact_is_not_accepted_as_pinned_build(self):
        artifact = self.bundle / bridge_bundle.ARTIFACTS[0]
        outside = self.root / 'other-file'
        outside.write_bytes(artifact.read_bytes())
        artifact.unlink()
        artifact.symlink_to(outside)
        with self.assertRaisesRegex(core.HostError, 'linked'):
            self.create()
