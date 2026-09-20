import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from plugg import recipe_engine as engine

class RecipesTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.env=self.root/'env';self.env.mkdir()
        (self.env/'prefix/drive_c').mkdir(parents=True)
        self.cfg={'prefix':str(self.env/'prefix'),'graphics_backend':'wined3d'}
        (self.env/'session.json').write_text(json.dumps(self.cfg))
    def record(self,name,requires=(),graphics=None,revision=1):
        return {'data':{'schema':1,'id':name,'revision':revision,'kind':'component','name':name,'requires':list(requires),**({'graphics':graphics} if graphics else {})},'sha256':'0'*64,'source':'test'}
    def test_graph_deduplicates_shared_components(self):
        records={'local.base@1':self.record('local.base'), 'local.a@1':self.record('local.a',['local.base@1']), 'local.b@1':self.record('local.b',['local.base@1']), 'local.root@1':self.record('local.root',['local.a@1','local.b@1'])}
        self.assertEqual([engine.reference(r) for r in engine.resolve(records,'local.root@1')],['local.base@1','local.a@1','local.b@1','local.root@1'])
    def test_cycles_missing_and_revision_conflicts_fail(self):
        cases=[{'local.a@1':self.record('local.a',['local.a@1'])}, {'local.a@1':self.record('local.a',['local.missing@1'])}, {'local.a@1':self.record('local.a',['local.b@1','local.b@2']),'local.b@1':self.record('local.b'),'local.b@2':self.record('local.b',revision=2)}]
        for records in cases:
            with self.assertRaises(ValueError):engine.resolve(records,'local.a@1')
    def test_unknown_operations_and_duplicate_ids_rejected(self):
        path=self.root/'one.toml'
        base='schema=1\nid="local.example"\nrevision=1\nkind="vendor"\nname="Example"\n'
        path.write_text(base+'shell="echo bad"\n')
        with self.assertRaisesRegex(ValueError,'Unknown'):engine.load(path)
        path.write_text(base);(self.root/'two.toml').write_text(base)
        with self.assertRaisesRegex(ValueError,'Duplicate'):engine.catalogue([self.root])
    def test_plan_is_read_only_preserves_local_overrides_and_detects_drift(self):
        self.cfg['graphics_policy']={'schema':1,'default':'wined3d','plugins':{'Local.vst3':'wined3d'}}
        (self.env/'session.json').write_text(json.dumps(self.cfg));before=(self.env/'session.json').read_bytes()
        records={'local.pa@1':self.record('local.pa',graphics={'default':'wined3d'})}
        plan=engine.plan(records,'local.pa@1',self.env)
        self.assertFalse(plan['changed']);self.assertEqual(plan['after']['plugins'],{'Local.vst3':'wined3d'})
        self.assertEqual((self.env/'session.json').read_bytes(),before)
        self.assertFalse((self.env/'recipe-lock.json').exists())
        with patch('plugg.recipes.configure_graphics') as configure:
            result=engine.apply(plan);configure.assert_not_called()
        self.assertFalse(result['changed']);self.assertTrue((self.env/'recipe-lock.json').exists())
        (self.env/'session.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'changed'):engine.apply(plan)
    def test_conflicting_component_graphics_are_not_order_dependent(self):
        records={'local.a@1':self.record('local.a',['local.b@1'],{'default':'wined3d'}),'local.b@1':self.record('local.b',graphics={'default':'dxvk'})}
        with self.assertRaisesRegex(ValueError,'Conflicting'):engine.plan(records,'local.a@1',self.env)
    def test_builtin_recipes_load(self):
        records=engine.catalogue([Path(engine.__file__).parent/'recipes/community'])
        self.assertEqual(len(engine.resolve(records,'plugg.plugin-alliance@1')),2)

    def test_catalogue_check_needs_no_environment(self):
        records = {
            'local.override@1': self.record('local.override', graphics={'plugins': {'Example.vst3': 'dxvk'}}),
            'local.vendor@1': self.record('local.vendor', ['local.override@1'], {'default': 'wined3d'}),
        }
        records['local.vendor@1']['data']['kind'] = 'vendor'
        with patch.object(engine, 'plan', side_effect=AssertionError('Must not plan an installation')):
            checked = engine.check(records)
        self.assertEqual(checked[1]['dependencies'], ['local.override@1'])
        records['local.vendor@1']['data']['graphics'].pop('default')
        with self.assertRaisesRegex(ValueError, 'declare a graphics default'):
            engine.check(records)

    def test_component_conflict_fails_without_installation(self):
        records = {
            'local.base@1': self.record('local.base', graphics={'plugins': {'Example.vst3': 'dxvk'}}),
            'local.other@1': self.record('local.other', ['local.base@1'], {'plugins': {'Example.vst3': 'wined3d'}}),
        }
        with self.assertRaisesRegex(ValueError, 'Conflicting graphics requirements'):
            engine.check(records)

    def test_plan_fingerprint_matches_the_settings_read(self):
        import hashlib
        initial = (self.env / 'session.json').read_bytes()
        records = {'local.example@1': self.record('local.example', graphics={'default': 'wined3d'})}
        def mutate_during_preparation(_):
            (self.env / 'session.json').write_text(json.dumps({**self.cfg, 'idle_seconds': 999}))
        with patch.object(engine.proton_session, 'prepare_graphics', side_effect=mutate_during_preparation):
            planned = engine.plan(records, 'local.example@1', self.env)
        self.assertEqual(planned['session_sha256'], hashlib.sha256(initial).hexdigest())
        with self.assertRaisesRegex(ValueError, 'changed since planning'):
            engine.apply(planned)

    def test_vc_component_rejects_untrusted_host_hash_and_extra_arguments(self):
        path = self.root / 'vc.toml'
        base = 'schema=1\nid="local.vc"\nrevision=1\nkind="component"\nname="VC"\n'
        valid = {'url': 'https://download.microsoft.com/vc.exe', 'sha256': 'a' * 64, 'source': 'https://learn.microsoft.com/'}
        for modification in ({'url': 'https://example.com/vc.exe'}, {'sha256': 'bad'}, {'args': '/arbitrary'}, {'url': 'https://user:password@download.microsoft.com/vc.exe'}):
            asset = {**valid, **modification}
            path.write_text(base + '[vc_runtime]\n' + '\n'.join(f'{key}={json.dumps(value)}' for key, value in asset.items()))
            with self.assertRaises(ValueError):
                engine.load(path)

    def test_import_requires_a_reachable_vc_component(self):
        record = self.record('local.vendor', graphics={'default': 'dxvk'})
        record['data'].update(kind='vendor', vendor='Example', modules={'a' * 64: {'name': 'Example', 'dependency': 'local.missing@1'}})
        with self.assertRaisesRegex(ValueError, 'resolve to a vc_runtime'):
            engine.standalone_catalogue({'local.vendor@1': record})

    def test_match_unknown_input_is_read_only(self):
        from test_core import fake_pe
        source = fake_pe(self.root / 'Unknown.vst3')
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        result = engine.match_input({}, source)
        self.assertFalse(result['matched'])
        self.assertIsNone(result['recipe'])
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')))

    def changed_plan(self):
        # Add a WineD3D override: no real runtime or DXVK payload is needed.
        records = {'local.example@1': self.record('local.example', graphics={'default': 'wined3d', 'plugins': {'Example.vst3': 'wined3d'}})}
        return engine.plan(records, 'local.example@1', self.env)

    def test_helper_and_direct_graphics_locks_block_recipe_apply(self):
        from plugg import core
        for name in ('helper.lock', 'graphics-policy.lock'):
            with core.lock(self.env / name):
                with self.assertRaises(core.HostError):
                    engine.apply(self.changed_plan())
            self.assertFalse((self.env / 'recipe-application.json').exists())

    def test_partial_application_requires_inspection_and_never_replays(self):
        from plugg import recipes
        planned = self.changed_plan()
        def interrupted(directory, policy):
            (directory / 'session.json').write_text(json.dumps({**self.cfg, 'graphics_policy': policy}))
            raise OSError('simulated launcher write failure')
        with patch.object(recipes, '_configure_graphics_locked', side_effect=interrupted) as configure:
            with self.assertRaisesRegex(OSError, 'launcher write'):
                engine.apply(planned)
            report = engine.status(self.env)
            self.assertTrue(report['needs_inspection'])
            with self.assertRaisesRegex(ValueError, 'needs inspection'):
                engine.apply(self.changed_plan())
            self.assertEqual(configure.call_count, 1)
        self.assertFalse((self.env / 'recipe-lock.json').exists())

    def test_failure_before_configuration_change_is_retryable(self):
        from plugg import recipes
        with patch.object(recipes, '_configure_graphics_locked', side_effect=RuntimeError('DAW busy')):
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError, 'DAW busy'):
                    engine.apply(self.changed_plan())
        self.assertEqual(engine.status(self.env)['application_status'], 'failed')
        self.assertFalse(engine.status(self.env)['needs_inspection'])

    def test_status_detects_external_changes_after_success(self):
        records = {'local.example@1': self.record('local.example', graphics={'default': 'wined3d'})}
        engine.apply(engine.plan(records, 'local.example@1', self.env))
        self.assertTrue(engine.status(self.env)['configuration_matches_record'])
        self.assertEqual(engine.status(self.env)['application_status'], 'complete')
        (self.env / 'session.json').write_text(json.dumps({**self.cfg, 'idle_seconds': 123}))
        self.assertFalse(engine.status(self.env)['configuration_matches_record'])

    def test_status_distinguishes_live_operation_from_interrupted_intent(self):
        from plugg import core
        (self.env / 'recipe-application.json').write_text(json.dumps({'status': 'applying'}))
        with core.lock(self.env / 'graphics-policy.lock'):
            self.assertTrue(engine.status(self.env)['operation_busy'])
            self.assertFalse(engine.status(self.env)['needs_inspection'])
        self.assertFalse(engine.status(self.env)['operation_busy'])
        self.assertTrue(engine.status(self.env)['needs_inspection'])

    def test_existing_setup_status_is_read_only_and_omits_private_fields(self):
        metadata = {'recipe': 'pace-service-experiment', 'runtime': 'Example runtime',
                    'helper_launcher': '/helper', 'ilok_launcher': '/ilok',
                    'account_token': 'DO-NOT-DISPLAY'}
        (self.env / 'environment.json').write_text(json.dumps(metadata))
        (self.env / 'dependencies.json').write_text(json.dumps([
            {'url': 'https://user:DO-NOT-DISPLAY@example.invalid/download?token=secret', 'sha256': 'a' * 64}
        ]))
        before = {str(p): p.read_bytes() for p in self.env.rglob('*') if p.is_file()}
        report = engine.status(self.env)
        setup = report['recorded_setup']
        self.assertEqual(setup['profile'], 'pace-service-experiment')
        self.assertTrue(setup['helper_configured'])
        self.assertTrue(setup['ilok_manager_configured'])
        self.assertNotIn('DO-NOT-DISPLAY', json.dumps(report))
        self.assertNotIn('token=secret', json.dumps(report))
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.env.rglob('*') if p.is_file()})

    def test_malformed_optional_records_do_not_hide_session_status(self):
        (self.env / 'dependencies.json').write_text('not json')
        (self.env / 'environment.json').write_text('[]')
        report = engine.status(self.env)
        self.assertEqual(len(report['recorded_setup']['record_issues']), 2)
        self.assertEqual(report['application_status'], 'not-recorded')

    def test_conflicting_revisions_explain_both_requirement_paths(self):
        records = {
            'local.vendor@1': self.record('local.vendor', ['local.auth@1', 'local.helper@1']),
            'local.auth@1': self.record('local.auth', ['local.runtime@1']),
            'local.helper@1': self.record('local.helper', ['local.runtime@2']),
            'local.runtime@1': self.record('local.runtime'),
            'local.runtime@2': self.record('local.runtime', revision=2),
        }
        with self.assertRaises(ValueError) as caught:
            engine.resolve(records, 'local.vendor@1')
        self.assertIn('local.vendor@1 -> local.auth@1 -> local.runtime@1', str(caught.exception))
        self.assertIn('local.vendor@1 -> local.helper@1 -> local.runtime@2', str(caught.exception))
        del records['local.runtime@1']
        with self.assertRaises(ValueError) as caught:
            engine.resolve(records, 'local.vendor@1')
        self.assertIn('Missing recipe dependency: local.vendor@1 -> local.auth@1 -> local.runtime@1', str(caught.exception))

    def test_graphics_conflict_identifies_both_components_and_values(self):
        records = [self.record('local.first', graphics={'default': 'dxvk'}),
                   self.record('local.second', graphics={'default': 'wined3d'})]
        with self.assertRaises(ValueError) as caught:
            engine.graphics_requirements(records)
        self.assertIn('local.first@1 (dxvk)', str(caught.exception))
        self.assertIn('local.second@1 (wined3d)', str(caught.exception))

    def test_graphics_plan_cannot_silently_skip_installer_components(self):
        vendor = self.record('local.vendor', ['local.vc@1'], {'default': 'dxvk'})
        component = self.record('local.vc')
        component['data']['vc_runtime'] = {'url': 'unused', 'sha256': 'a' * 64, 'source': 'unused'}
        records = {'local.vendor@1': vendor, 'local.vc@1': component}
        with self.assertRaisesRegex(ValueError, 'cannot install VC'):
            engine.plan(records, 'local.vendor@1', self.root / 'missing-environment')
        self.assertFalse((self.env / 'recipe-lock.json').exists())

    def test_plan_reports_licensing_and_apply_refuses_a_drifted_protected_environment(self):
        from plugg import licensing
        (self.env / 'prefix/system.reg').write_text(
            'WINE REGISTRY Version 2\n\n[Software\\\\Microsoft\\\\Cryptography] 1\n'
            '"MachineGuid"="0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"\n')
        records = {'local.pa@1': self.record('local.pa', graphics={'default': 'wined3d'})}
        plan = engine.plan(records, 'local.pa@1', self.env)
        self.assertFalse(plan['licensing']['protected'])
        licensing.protect(self.env, [{'name': 'ExampleSynth', 'recovery': 'limited-activations',
                                      'activations_remaining': 3}])
        plan = engine.plan(records, 'local.pa@1', self.env)
        self.assertTrue(plan['licensing']['protected'])
        self.assertEqual(plan['licensing']['severity'], 'limited-activations')
        # Protected but unchanged: graphics configuration is still allowed.
        engine.apply(plan)
        self.assertTrue(json.loads((self.env / 'recipe-lock.json').read_text())['licensing']['protected'])
        # Something changed the identity outside our control: stop writing.
        (self.env / 'prefix/system.reg').write_text(
            'WINE REGISTRY Version 2\n\n[Software\\\\Microsoft\\\\Cryptography] 1\n'
            '"MachineGuid"="999e2d3c-f41a-4974-b30e-74c830008ade"\n')
        plan = engine.plan(records, 'local.pa@1', self.env)
        self.assertFalse(plan['licensing']['matches_recorded_identity'])
        with self.assertRaises(licensing.LicensedEnvironmentError) as caught:
            engine.apply(plan)
        self.assertIn('machine_guid', str(caught.exception))

    def test_status_includes_the_licensing_position(self):
        report = engine.status(self.env)
        self.assertFalse(report['licensing']['protected'])
        self.assertIsNone(report['licensing']['matches_recorded_identity'])
