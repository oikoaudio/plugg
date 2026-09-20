"""Creating the iLok environment refuses everything it cannot do safely, before creating anything."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugg import core, ilok_setup, licensing, runtime_overlay
from test_licensing import REGISTRY

MSI = bytes.fromhex('d0cf11e0a1b11ae1') + b'not really pace'


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = core.Store(root / 'library', publication=root / 'published')
        self.msi = root / 'PACE.msi'
        self.msi.write_bytes(MSI)
        patcher = patch.object(ilok_setup, 'PACE_SHA256', core.digest(self.msi))
        patcher.start()
        self.addCleanup(patcher.stop)

    def select_runtime(self):
        settings = self.store.root / 'settings.json'
        core.atomic_json(settings, {**json.loads(settings.read_text()), runtime_overlay.SETTING: 'plugg-1'})

    def environments(self):
        return sorted(path.name for path in (self.store.root / 'environments').glob('*'))

    def test_an_untested_pace_installer_is_refused(self):
        other = Path(self.tmp.name) / 'Other.msi'
        other.write_bytes(MSI + b'!')
        with self.assertRaisesRegex(core.HostError, 'not the PACE installer that has been tested'):
            ilok_setup.preflight(self.store, other)

    def test_the_patched_runtime_must_be_selected(self):
        with self.assertRaisesRegex(core.HostError, 'runtime select plugg-1'):
            ilok_setup.preflight(self.store, self.msi)

    def test_an_environment_that_still_records_activations_blocks_replacement(self):
        self.select_runtime()
        old = self.store.root / 'environments/old'
        (old / 'prefix').mkdir(parents=True)
        (old / 'prefix/system.reg').write_text(REGISTRY)
        licensing.protect(old, [{'name': 'Example Suite', 'recovery': 'deactivate-first'}])
        core.atomic_json(self.store.root / ilok_setup.GROUPS,
                         {'schema': 1, 'groups': {'ilok': {'environment': 'old', 'vendors': []}}})
        with patch.object(runtime_overlay, 'verify'), \
                self.assertRaisesRegex(core.HostError, 'still records activations \\(Example Suite\\)'):
            ilok_setup.preflight(self.store, self.msi)
        licensing.deactivated(old, ['Example Suite'], 'I have deactivated Example Suite')
        with patch.object(runtime_overlay, 'verify'), \
                patch('plugg.proton_session.foreign_prefix_processes', return_value=[]):
            plan = ilok_setup.preflight(self.store, self.msi)
        self.assertEqual(plan['replaces'], str(old))
        self.assertEqual(self.environments(), ['old'])

    def test_the_group_record_keeps_what_it_replaced(self):
        core.atomic_json(self.store.root / ilok_setup.GROUPS,
                         {'schema': 1, 'groups': {'ilok': {'environment': 'old', 'vendors': ['Softube']}}})
        new = self.store.root / 'environments/new'
        ilok_setup._record_group(self.store, new, str(self.store.root / 'environments/old'))
        entry = ilok_setup.groups(self.store)['groups']['ilok']
        self.assertEqual(entry['environment'], 'new')
        self.assertEqual(entry['previous'][0]['environment'], 'old')
        self.assertEqual(entry['previous'][0]['vendors'], ['Softube'])
        self.assertEqual(ilok_setup.current(self.store), new)


if __name__ == '__main__':
    unittest.main()
