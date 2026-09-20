from pathlib import Path
import tempfile
import unittest
from plugg import core, helper_component as helper


class HelperComponentTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.prefix = self.root / 'prefix'
        self.spec = {'name': 'Example Manager', 'executable': 'Program Files/Example/Manager.exe', 'archive_tools': False}

    def test_two_helpers_share_launch_operation_with_distinct_paths(self):
        for archive_tools in (False, True):
            spec = {**self.spec, 'archive_tools': archive_tools}
            launcher = helper.configure(self.prefix, self.root / 'full launcher', spec)
            batch = (self.prefix / 'drive_c/Plugg/launch-helper.cmd').read_text()
            self.assertIn('"C:\\Program Files\\Example\\Manager.exe"', batch)
            self.assertEqual('set "PATH=' in batch, archive_tools)
            self.assertIn("'" + str(self.root / 'full launcher') + "'", launcher.read_text())
        other = {**self.spec, 'executable': 'Other/Helper.exe'}
        helper.configure(self.prefix, self.root / 'full', other)
        self.assertIn('"C:\\Other\\Helper.exe"', (self.prefix / 'drive_c/Plugg/launch-helper.cmd').read_text())

    def test_batch_expansion_and_traversal_are_rejected_before_writing(self):
        for path in ('../helper.exe', '/helper.exe', 'C:/helper.exe', '%TEMP%/helper.exe', 'a&b.exe', 'a\n.exe', 'a".exe'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                helper.configure(self.prefix, self.root / 'full', {**self.spec, 'executable': path})
        self.assertFalse(self.prefix.exists())

    def test_installed_target_must_exist_and_stay_in_environment(self):
        with self.assertRaises(core.HostError):
            helper.installed_binary(self.prefix, self.spec)
        target = self.prefix / 'drive_c' / self.spec['executable']
        target.parent.mkdir(parents=True)
        target.write_bytes(b'fixture')
        self.assertEqual(helper.installed_binary(self.prefix, self.spec), target)
        target.unlink()
        outside = self.root / 'outside.exe'
        outside.write_bytes(b'fixture')
        target.symlink_to(outside)
        with self.assertRaises(core.HostError):
            helper.installed_binary(self.prefix, self.spec)

    def test_custom_helper_uses_shared_environment_configuration(self):
        import json
        from types import SimpleNamespace
        from plugg import recipes
        runtime = self.root / 'runtime'
        (runtime / 'UMU-Proton-10.0-4').mkdir(parents=True)
        (runtime / 'UMU-Proton-10.0-4/proton').write_text('fixture')
        self.prefix.mkdir()
        store = SimpleNamespace(root=self.root, prefix=lambda _: self.prefix)
        full, launcher = recipes.configure(store, 'fixture', runtime, helper_spec=self.spec)
        self.assertTrue(full.is_file())
        self.assertTrue(launcher.is_file())
        session = json.loads((self.root / 'session.json').read_text())
        self.assertEqual(session['recipe'], 'managed-helper-1')
        self.assertEqual(session['prefix'], str(self.prefix))
        self.assertEqual(json.loads((self.root / 'helper-entry.json').read_text())['helper'], self.spec)
        self.assertNotIn('Klevgrand', (self.prefix / 'drive_c/Plugg/launch-helper.cmd').read_text())

    def test_invalid_description_rejected_before_environment_writes(self):
        from types import SimpleNamespace
        from plugg import recipes
        store = SimpleNamespace(root=self.root, prefix=lambda _: self.prefix)
        with self.assertRaises(ValueError):
            recipes.configure(store, 'fixture', self.root / 'missing-runtime', helper_spec={})
        with self.assertRaises(ValueError):
            recipes.configure(store, 'fixture', self.root / 'missing-runtime', helper_enabled=False, helper_spec=self.spec)
        self.assertEqual(list(self.root.iterdir()), [])

    def installer_job(self):
        import json
        payload = self.root / 'job/payload'
        payload.mkdir(parents=True)
        installer = payload / 'setup.exe'
        installer.write_bytes(b'installer')
        companion = payload / 'setup.bin'
        companion.write_bytes(b'data')
        (payload.parent / 'installer-files.json').write_text(json.dumps({'schema': 1, 'files': [
            {'name': path.name, 'sha256': core.digest(path)} for path in (installer, companion)]}))
        return {'installer': str(installer), 'hash': core.digest(installer)}

    def test_install_preserves_companion_directory_and_checks_expected_helper(self):
        from unittest.mock import patch
        job = self.installer_job()
        target = self.prefix / 'drive_c' / self.spec['executable']
        def run(*args, **kwargs):
            target.parent.mkdir(parents=True)
            target.write_bytes(b'helper')
            return 0
        with patch.object(core, 'run_process', side_effect=run) as process:
            result = helper.install(job, self.prefix, self.root / 'full', self.spec, ['/quiet', 'one argument'], lambda: None)
        self.assertEqual(result, target)
        self.assertEqual(process.call_args.kwargs['cwd'], Path(job['installer']).parent)
        self.assertEqual(process.call_args.args[0][-2:], ['/quiet', 'one argument'])

    def test_changed_companion_prevents_execution(self):
        from unittest.mock import patch
        job = self.installer_job()
        Path(job['installer']).with_suffix('.bin').write_bytes(b'changed')
        with patch.object(core, 'run_process') as process, self.assertRaisesRegex(core.HostError, 'missing or changed'):
            helper.install(job, self.prefix, self.root / 'full', self.spec, [], lambda: None)
        process.assert_not_called()

    def test_installer_exit_and_missing_helper_are_distinct_failures(self):
        from unittest.mock import patch
        job = self.installer_job()
        with patch.object(core, 'run_process', return_value=5), self.assertRaisesRegex(core.HostError, 'exit 5'):
            helper.install(job, self.prefix, self.root / 'full', self.spec, [], lambda: None)
        with patch.object(core, 'run_process', return_value=0), self.assertRaisesRegex(core.HostError, 'not found'):
            helper.install(job, self.prefix, self.root / 'full', self.spec, [], lambda: None)
