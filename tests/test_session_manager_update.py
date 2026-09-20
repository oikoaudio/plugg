"""Existing environments must be able to receive a fix in the session launcher.

An environment keeps the launcher it was created with, and its session records
that launcher's fingerprint. Without a way to refresh it, a fix in the launcher
reaches only environments made afterwards, which would mean reinstalling
software to get a bug fix. Refreshing touches the launcher and nothing else.
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugg import core, licensing, proton_session, recipes


class UpdateSessionManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / 'environments/job'
        (self.directory / 'prefix').mkdir(parents=True)
        self.config = {'prefix': str(self.directory / 'prefix'), 'proton': '/runtimes/proton',
                       'manager_sha256': '0' * 64, 'graphics_backend': 'dxvk'}
        core.atomic_json(self.directory / 'session.json', self.config)
        (self.directory / 'launch-plugin').write_text('#!/bin/sh\nexec old\n')
        (self.directory / 'session-manager-0000000000000000.py').write_text('old manager\n')

    def test_it_installs_the_current_launcher_and_records_its_fingerprint(self):
        result = recipes.update_session_manager(self.directory)
        digest = core.digest(Path(proton_session.__file__))
        self.assertTrue(result['updated'])
        config = json.loads((self.directory / 'session.json').read_text())
        self.assertEqual(config['manager_sha256'], digest)
        manager = self.directory / ('session-manager-' + digest[:16] + '.py')
        self.assertEqual(core.digest(manager), digest)
        self.assertIn(str(manager), (self.directory / 'launch-plugin').read_text())

    def test_it_keeps_what_was_there_before(self):
        recipes.update_session_manager(self.directory)
        backups = list((self.directory / 'configuration-history').iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'launch-plugin').read_text(), '#!/bin/sh\nexec old\n')
        self.assertEqual(json.loads((backups[0] / 'session.json').read_text())['manager_sha256'], '0' * 64)

    def test_it_changes_nothing_else_about_the_environment(self):
        recipes.update_session_manager(self.directory)
        config = json.loads((self.directory / 'session.json').read_text())
        self.assertEqual(config['prefix'], self.config['prefix'])
        self.assertEqual(config['proton'], self.config['proton'])
        self.assertEqual(config['graphics_backend'], 'dxvk')

    def test_repeating_it_does_nothing(self):
        recipes.update_session_manager(self.directory)
        self.assertEqual(recipes.update_session_manager(self.directory)['updated'], False)
        self.assertEqual(len(list((self.directory / 'configuration-history').iterdir())), 1)

    def test_it_asks_the_licensing_guard_first(self):
        refusal = licensing.LicensedEnvironmentError('refused')
        with patch.object(licensing, 'guard', side_effect=refusal) as guard:
            with self.assertRaises(licensing.LicensedEnvironmentError):
                recipes.update_session_manager(self.directory)
        guard.assert_called_once_with(self.directory, 'update_launcher')
        self.assertEqual(json.loads((self.directory / 'session.json').read_text())['manager_sha256'], '0' * 64)

    def test_updating_the_launcher_does_not_change_machine_identity(self):
        self.assertIn('update_launcher', licensing.IN_PLACE)
        self.assertNotIn('update_launcher', licensing.IDENTITY_CHANGING)


if __name__ == '__main__':
    unittest.main()
