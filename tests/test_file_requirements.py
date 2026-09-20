import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from plugg import file_requirements as files, recipe_engine as engine


class FileRequirementsTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir()
        self.env = self.root / 'environment'
        self.prefix = self.env / 'prefix'
        (self.prefix / 'drive_c').mkdir(parents=True)
        self.cfg = {'proton': str(self.runtime / 'proton'), 'prefix': str(self.prefix), 'graphics_backend': 'wined3d'}
        (self.env / 'session.json').write_text(json.dumps(self.cfg))
        self.digest = hashlib.sha256(b'patched').hexdigest()
        self.requirements = {'runtime': {'library.dll': self.digest}, 'prefix': {'library.dll': self.digest}}
        for root in (self.runtime, self.prefix / 'drive_c'):
            (root / 'library.dll').write_bytes(b'patched')

    def test_checks_both_runtime_and_installed_copy(self):
        self.assertEqual(len(files.verify(self.cfg, self.requirements)), 2)
        (self.prefix / 'drive_c/library.dll').write_bytes(b'original')
        with self.assertRaisesRegex(ValueError, 'differs'):
            files.verify(self.cfg, self.requirements)

    def test_traversal_and_external_symlink_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'scope root'):
            files.validate({'runtime': {'../library.dll': self.digest}})
        (self.runtime / 'library.dll').unlink()
        (self.runtime / 'library.dll').symlink_to(self.prefix / 'drive_c/library.dll')
        with self.assertRaisesRegex(ValueError, 'escapes'):
            files.verify(self.cfg, self.requirements)

    def test_conflicting_components_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            files.resolve([{'data': {'required_files': {'runtime': {'library.dll': self.digest}}}},
                           {'data': {'required_files': {'runtime': {'library.dll': '0' * 64}}}}])

    def test_apply_rechecks_files_after_plan(self):
        record = {'data': {'id': 'local.test', 'revision': 1, 'kind': 'vendor', 'requires': [],
                           'required_files': self.requirements, 'graphics': {'default': 'wined3d'}}, 'sha256': 'a' * 64}
        plan = engine.plan({'local.test@1': record}, 'local.test@1', self.env)
        (self.runtime / 'library.dll').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'differs'):
            engine.apply(plan)
        self.assertFalse((self.env / 'recipe-lock.json').exists())

    def test_status_detects_file_drift_without_configuration_change(self):
        record = {'data': {'id': 'local.test', 'revision': 1, 'kind': 'vendor', 'requires': [],
                           'required_files': self.requirements, 'graphics': {'default': 'wined3d'}}, 'sha256': 'a' * 64}
        engine.apply(engine.plan({'local.test@1': record}, 'local.test@1', self.env))
        self.assertTrue(engine.status(self.env)['requirements_match_record'])
        (self.runtime / 'library.dll').write_bytes(b'changed')
        report = engine.status(self.env)
        self.assertTrue(report['configuration_matches_record'])
        self.assertFalse(report['requirements_match_record'])
        self.assertIn('differs', report['requirement_issues'][0])

    def test_status_distinguishes_missing_empty_and_invalid_evidence(self):
        self.assertIsNone(engine.status(self.env)['requirements_match_record'])
        lock = self.env / 'recipe-lock.json'
        lock.write_text(json.dumps({'file_checks': [], 'bridge_checks': []}))
        self.assertTrue(engine.status(self.env)['requirements_match_record'])
        lock.write_text(json.dumps({'file_checks': [], 'bridge_checks': [{}]}))
        self.assertFalse(engine.status(self.env)['requirements_match_record'])
        lock.write_text(json.dumps({'file_checks': []}))
        self.assertIsNone(engine.status(self.env)['requirements_match_record'])
