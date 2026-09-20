import json
from pathlib import Path
import tempfile
import unittest
from plugg import bridge_requirements as bridge, recipe_engine as engine


class BridgeRequirementsTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.env = self.root / 'environment'
        self.drive = self.env / 'prefix/drive_c'
        self.drive.mkdir(parents=True)
        (self.env / 'session.json').write_text(json.dumps({'prefix': str(self.env / 'prefix'), 'graphics_backend': 'wined3d'}))
        self.module = 'Program Files/Common Files/VST3/Example.vst3'
        self.patch = 'a' * 64
        self.release = self.root / 'release'
        self.release.mkdir()
        files = {}
        for name in (*bridge.ARTIFACTS, 'libyabridge-chainloader-vst3.so'):
            path = self.release / name
            path.write_text(name)
            files[name] = bridge.digest(path)
        self.manifest = {'files': files, 'patches': {'fix.patch': self.patch}}
        (self.release / 'build.json').write_text(json.dumps(self.manifest))
        self.pub = self.publication('first', self.module, self.release)
        (self.env / 'bridge-deployment.json').write_text(json.dumps({'plugins': [{'publication': str(self.pub)}]}))

    def publication(self, name, module, release):
        publication = self.root / (name + '.vst3')
        native = publication / 'Contents/x86_64-linux'
        windows = publication / 'Contents/x86_64-win'
        native.mkdir(parents=True);windows.mkdir()
        (native / '.plugg-managed').write_text('1\n')
        target = self.drive / module
        target.parent.mkdir(parents=True, exist_ok=True);target.write_text('module')
        (windows / publication.name).symlink_to(target)
        for artifact in bridge.ARTIFACTS:
            (native / artifact).symlink_to(release / artifact)
        (native / (publication.stem + '.so')).write_bytes((release / 'libyabridge-chainloader-vst3.so').read_bytes())
        return publication

    def test_actual_module_mapping_works_with_other_unrelated_publications(self):
        # The unrelated publication need not carry this module-specific patch.
        other = self.root / 'other.vst3'
        (self.env / 'bridge-deployment.json').write_text(json.dumps({'plugins': [
            {'publication': str(self.pub)}, {'publication': str(other)}
        ]}))
        result = bridge.verify(self.env, {self.module: [self.patch]})
        self.assertEqual(result[0]['publication'], str(self.pub))
        self.assertEqual(result[0]['required_patches'], [self.patch])

    def test_missing_patch_and_tampered_binary_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'patch is missing'):
            bridge.verify(self.env, {self.module: ['b' * 64]})
        (self.release / 'yabridge-host.exe.so').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'artifact does not match'):
            bridge.verify(self.env, {self.module: [self.patch]})

    def test_wrong_module_cannot_be_satisfied_by_an_environment_wide_label(self):
        (self.drive / 'Other.vst3').write_text('different module')
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            bridge.verify(self.env, {'Other.vst3': [self.patch]})

    def test_change_between_plan_and_apply_is_rejected(self):
        component = {'data': {'id': 'local.fix', 'revision': 1, 'kind': 'component', 'requires': [], 'bridge_patch': {'sha256': self.patch}}, 'sha256': 'c' * 64}
        vendor = {'data': {'id': 'local.vendor', 'revision': 1, 'kind': 'vendor', 'requires': ['local.fix@1'],
                          'graphics': {'default': 'wined3d'}, 'bridge_requirements': {self.module: ['local.fix@1']}}, 'sha256': 'd' * 64}
        records = {'local.fix@1': component, 'local.vendor@1': vendor}
        plan = engine.plan(records, 'local.vendor@1', self.env)
        self.manifest['additional_metadata'] = 'different build record'
        (self.release / 'build.json').write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError, 'deployment changed'):
            engine.apply(plan)
        self.assertFalse((self.env / 'recipe-lock.json').exists())

    def test_requirement_must_be_a_reachable_patch_component(self):
        with self.assertRaisesRegex(ValueError, 'resolve to a bridge_patch'):
            engine.required_bridge_patches([{'data': {'id': 'local.vendor', 'revision': 1,
                                                      'bridge_requirements': {self.module: ['local.absent@1']}}}])

    def test_status_rechecks_published_bridge_without_configuration_change(self):
        session = self.env / 'session.json'
        lock = {'applied_session_sha256': bridge.digest(session), 'file_checks': [],
                'bridge_checks': bridge.verify(self.env, {self.module: [self.patch]})}
        (self.env / 'recipe-lock.json').write_text(json.dumps(lock))
        self.assertTrue(engine.status(self.env)['requirements_match_record'])
        (self.release / 'yabridge-host.exe.so').write_text('changed')
        report = engine.status(self.env)
        self.assertTrue(report['configuration_matches_record'])
        self.assertFalse(report['requirements_match_record'])
        self.assertIn('artifact does not match', report['requirement_issues'][0])
