import json
from pathlib import Path
import tempfile
import unittest
from plugg import provenance
from plugg.provenance import installation_source, import_recipe_summary, setup_recipe_summary, installation_progress


class ProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.job = {'id': 'helper', 'env_id': 'shared', 'kind': 'exe', 'hash': 'installer', 'installer': '/saved/UA Connect.exe'}
        self.setup = {'job': 'helper', 'recipe': 'pace-service-experiment', 'name': 'UA Connect'}
        self.plugin = {'env_id': 'shared', 'hash': 'plugin', 'metadata': json.dumps({'classes': [{'vendor': 'Soundtoys'}]})}

    def test_shared_licensing_does_not_attribute_soundtoys_to_ua_installer(self):
        source, owner = installation_source(self.plugin, [self.job], [self.setup])
        self.assertIn('iLok', source)
        self.assertIsNone(owner)

    def test_ua_product_can_refer_to_its_own_helper(self):
        self.plugin['metadata'] = json.dumps({'classes': [{'vendor': 'Universal Audio'}]})
        self.assertEqual(installation_source(self.plugin, [self.job], [self.setup])[1], self.job)

    def test_exact_import_takes_precedence_over_shared_helper(self):
        direct = {**self.job, 'id': 'direct', 'kind': 'vst3', 'hash': 'plugin', 'installer': '/saved/Example.vst3'}
        source, owner = installation_source(self.plugin, [self.job, direct], [self.setup])
        self.assertEqual(owner, direct)
        self.assertIn('Example.vst3', source)

    def test_summary_uses_recorded_revision_and_rejects_wrong_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = {**self.job, 'kind': 'vst3'}
            path = root / 'jobs/helper/recipe-lock.json'
            path.parent.mkdir(parents=True)
            record = {'operation': 'import_vst3', 'input_sha256': job['hash'], 'recipe': 'local.vendor@2',
                      'dependency': {'reference': 'local.vc@1'}, 'recipes': [
                          {'reference': 'local.vendor@2', 'resolved': {'name': 'Example', 'revision': 2}},
                          {'reference': 'local.vc@1', 'resolved': {'name': 'Microsoft VC', 'revision': 1}},
                      ]}
            path.write_text(json.dumps(record))
            self.assertEqual(import_recipe_summary(root, job), ['Setup recipe: Example (revision 2)', 'Required component: Microsoft VC'])
            job['hash'] = 'different'
            self.assertEqual(import_recipe_summary(root, job), ['Setup record does not match this import.'])

    def test_helper_summary_uses_saved_recipe_and_matching_installer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'jobs/helper/helper-recipe.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'reference': 'local.helper@2',
                'helper': {'installer_sha256': 'installer'}, 'recipes': [
                    {'reference': 'local.helper@2', 'resolved': {'name': 'Example Manager', 'revision': 2}}]}))
            self.assertEqual(setup_recipe_summary(root, self.job), ['Setup recipe: Example Manager (revision 2)'])
            changed = {**self.job, 'hash': 'different'}
            self.assertEqual(setup_recipe_summary(root, changed), ['Setup record does not match this installer.'])
            path.write_text('{')
            self.assertEqual(setup_recipe_summary(root, self.job), ['Setup record could not be read.'])

    def test_interrupted_progress_is_recorded_not_live_and_does_not_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'jobs/helper/helper-setup.json'
            path.parent.mkdir(parents=True)
            path.write_text('{"stage":"installing-helper"}')
            before = path.read_bytes()
            lines = installation_progress(root, {**self.job, 'status': 'needs_attention'})
            self.assertIn('Last recorded step: Running the vendor installer', lines)
            self.assertIn('activation data', lines[1])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(installation_progress(root, {**self.job, 'status': 'installing'})), 1)

    def test_progress_record_missing_malformed_and_oversized(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(installation_progress(root, self.job), [])
            path = root / 'jobs/helper/helper-setup.json'
            path.parent.mkdir(parents=True)
            for raw in ('[]', '{', '{"stage":[]}', ' ' * 65537):
                path.write_text(raw)
                self.assertIn('could not be read', installation_progress(root, self.job)[0])


class LicensingSummaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = self.root / 'environments' / 'one'
        (self.env / 'prefix').mkdir(parents=True)
        (self.env / 'prefix/system.reg').write_text(
            'WINE REGISTRY Version 2\n\n[Software\\\\Microsoft\\\\Cryptography] 1\n'
            '"MachineGuid"="0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"\n')

    def test_unprotected_environments_say_nothing(self):
        self.assertEqual(provenance.licensing_summary(self.root, 'one'), [])
        self.assertEqual(provenance.licensing_summary(self.root, 'missing'), [])

    def test_limited_activations_are_called_out_as_unrecoverable(self):
        from plugg import licensing
        licensing.protect(self.env, [{'name': 'ExampleSynth', 'recovery': 'limited-activations'}])
        lines = provenance.licensing_summary(self.root, 'one')
        self.assertIn('Holds activations for: ExampleSynth.', lines)
        self.assertTrue(any('cannot be recovered' in line for line in lines))

    def test_machine_bound_products_ask_for_deactivation_first(self):
        from plugg import licensing
        licensing.protect(self.env, [{'name': 'Bound', 'recovery': 'deactivate-first'}])
        self.assertTrue(any('Deactivate these products' in line
                            for line in provenance.licensing_summary(self.root, 'one')))

    def test_drift_is_shown_as_a_warning(self):
        from plugg import licensing
        licensing.protect(self.env, [{'name': 'Bound', 'recovery': 'deactivate-first'}])
        (self.env / 'prefix/system.reg').write_text(
            'WINE REGISTRY Version 2\n\n[Software\\\\Microsoft\\\\Cryptography] 1\n'
            '"MachineGuid"="999e2d3c-f41a-4974-b30e-74c830008ade"\n')
        lines = provenance.licensing_summary(self.root, 'one')
        self.assertTrue(any('no longer matches' in line and 'machine_guid' in line for line in lines))

    def test_a_damaged_record_is_treated_as_protected(self):
        from plugg import licensing
        licensing.protect(self.env, [{'name': 'Bound', 'recovery': 'deactivate-first'}])
        (self.env / licensing.RECORD).write_text('{ not json')
        lines = provenance.licensing_summary(self.root, 'one')
        self.assertTrue(any('could not be read' in line for line in lines))

    def test_no_identity_value_is_ever_displayed(self):
        from plugg import licensing
        licensing.protect(self.env, [{'name': 'Bound', 'recovery': 'deactivate-first'}])
        (self.env / 'prefix/system.reg').write_text(
            'WINE REGISTRY Version 2\n\n[Software\\\\Microsoft\\\\Cryptography] 1\n'
            '"MachineGuid"="999e2d3c-f41a-4974-b30e-74c830008ade"\n')
        joined = ' '.join(provenance.licensing_summary(self.root, 'one'))
        self.assertNotIn('999e2d3c', joined)
        self.assertNotIn('0f1e2d3c', joined)
