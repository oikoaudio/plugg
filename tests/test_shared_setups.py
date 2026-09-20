"""Recipe data cannot introduce commands or bypass shared-environment checks."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
from plugg import recipe_engine as engine, recipe_report, shared_setups, softube_setup


class SharedSetupTests(unittest.TestCase):
    def setUp(self):
        self.records = engine.catalogue([Path(engine.__file__).parent / 'recipes/community'])
        self.ref = 'plugg.softube@1'

    def test_shipped_recipe_resolves_to_reviewed_adapter(self):
        data = shared_setups.validate(self.records, self.ref)
        self.assertEqual(data['adapter'], 'softube')
        self.assertEqual(len(data['components']), 4)
        report = recipe_report.report(self.records, self.ref)
        self.assertIn('setup-softube-existing', report['capabilities'])
        self.assertEqual(recipe_report.catalogue_badge(report)[0], 'Setup in existing iLok environment')

    def test_recipe_calls_guarded_join_only(self):
        with patch.object(softube_setup, 'join', return_value={'identity_preserved': True}) as join:
            result = shared_setups.execute(self.records, self.ref, '/installer', '/existing')
            join.assert_called_once_with('/installer', '/existing', vc_assets=[])
            self.assertEqual(result['recipe']['reference'], self.ref)

    def test_revision_2_installs_the_visual_cpp_runtime_it_declares(self):
        # Softube's product installers stalled on their own silent vcredist
        # step in an environment without the runtime.
        records = self.records
        data = shared_setups.validate(records, 'plugg.softube@2')
        self.assertEqual(len(data['components']), 5)
        vc = records['plugg.vc2022-x64@1']['data']['vc_runtime']
        with patch.object(softube_setup, 'join', return_value={'identity_preserved': True}) as join:
            shared_setups.execute(records, 'plugg.softube@2', '/installer', '/existing')
        join.assert_called_once_with('/installer', '/existing', vc_assets=[vc])

    def test_component_modification_is_rejected_before_execution(self):
        records = copy.deepcopy(self.records)
        records['plugg.powershell@1']['sha256'] = 'different'
        with patch.object(softube_setup, 'join') as join, self.assertRaisesRegex(ValueError, 'differs'):
            shared_setups.execute(records, self.ref, '/installer', '/env')
        join.assert_not_called()

    def test_additional_operations_are_not_silently_ignored(self):
        self.records[self.ref]['data']['graphics'] = {'default': 'wined3d'}
        with self.assertRaisesRegex(ValueError, 'ignore'):
            shared_setups.validate(self.records, self.ref)

    def test_unreviewed_community_recipe_cannot_join(self):
        self.records[self.ref]['source'] = '/tmp/recipes/community/custom.toml'
        with self.assertRaisesRegex(ValueError, 'tier'):
            shared_setups.validate(self.records, self.ref)

    def test_generic_apply_still_cannot_provision_pace(self):
        with self.assertRaisesRegex(ValueError, 'Documentation only'):
            engine.plan(self.records, self.ref, '/unused')
