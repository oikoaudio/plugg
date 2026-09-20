"""In the iLok environment, an install loads only what it installed; waiting plug-ins are left alone."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugg import core, vendors
from test_core import fake_pe


class IlokInstallFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = core.Store(self.root / 'store', self.root / 'published')
        self.job = self.store.ingest(fake_pe(self.root / 'installer.exe'))
        self.prefix = self.store.prefix(self.job)
        self.envdir = self.prefix.parent
        self.envdir.mkdir(parents=True)
        self.launcher = self.envdir / 'launch-helper'
        core.atomic_json(self.envdir / 'environment.json', {
            'recipe': 'managed-helper', 'helper_launcher': str(self.launcher), 'ilok_launcher': str(self.launcher),
            'licensing_group': 'ilok', 'helper_job': self.job})
        self.vst3 = self.prefix / 'drive_c/Program Files/Common Files/VST3'

    def plugin(self, name):
        return fake_pe(self.vst3 / (name + '.vst3'))

    def test_only_what_an_install_changed_is_loaded(self):
        self.plugin('Waiting')
        before = vendors.snapshot(self.prefix)
        self.plugin('New')
        changed = vendors.changed_since(self.prefix, before)
        self.assertEqual({Path(path).stem for path in changed}, {'New'})
        with patch('plugg.core.probe', side_effect=core.HostError('needs activation')) as probe:
            result = vendors.refresh_library(self.store, self.job, probe_only=changed)
        self.assertEqual([call.args[1].stem for call in probe.call_args_list], ['New'])
        self.assertEqual(result['waiting'], ['Waiting'])
        self.assertEqual(len(result['failures']), 1)

    def test_a_full_refresh_loads_everything_waiting(self):
        self.plugin('One')
        self.plugin('Two')
        with patch('plugg.core.probe', side_effect=core.HostError('needs activation')) as probe:
            result = vendors.refresh_library(self.store, self.job)
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(result['waiting'], [])

    def test_vendor_managers_in_the_ilok_environment_load_only_their_own_changes(self):
        self.plugin('Waiting')
        before = vendors.snapshot(self.prefix)
        self.assertEqual(vendors.probe_scope(self.envdir, before), set())
        core.atomic_json(self.envdir / 'environment.json', {'recipe': 'klevgrand', 'helper_launcher': 'x'})
        self.assertIsNone(vendors.probe_scope(self.envdir, before))

    def test_the_message_points_at_activation(self):
        self.plugin('Waiting')
        with patch('plugg.vendors.applications', return_value=[]), \
                patch('plugg.core.probe', side_effect=core.HostError('needs activation')), \
                patch('plugg.vendors.time.sleep'), patch('plugg.vendors.time.monotonic', side_effect=range(0, 10000, 10)):
            vendors.finish_installation(self.store, self.job)
        import json
        state = json.loads((self.envdir / 'helper-state.json').read_text())
        self.assertIn('Activate them in iLok License Manager', state['message'])

    def test_managers_are_listed_from_their_setup_records(self):
        self.assertEqual(list(vendors.managers(self.envdir)), ['iLok License Manager'])
        (self.envdir / 'launch-ua-connect').write_text('#!/bin/sh\n')
        (self.envdir / 'ua-connect-launch.json').write_text('{}')
        self.assertEqual(list(vendors.managers(self.envdir)), ['iLok License Manager', 'UA Connect'])
        with self.assertRaisesRegex(core.HostError, 'not set up'):
            vendors.open_manager(self.store, self.job, 'Softube Central')

    def test_opening_ilok_goes_through_the_helper_worker_so_closing_it_refreshes(self):
        with patch('plugg.vendors.start', return_value=1) as start:
            vendors.open_manager(self.store, self.job, 'iLok License Manager')
        start.assert_called_once_with(self.store, self.job)


if __name__ == '__main__':
    unittest.main()
