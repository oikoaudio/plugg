import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from plugg import ua_setup, core, recipe_engine, shared_setups


class UASetupTests(unittest.TestCase):
    def test_unknown_installer_never_unpacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'ua.exe'
            source.write_bytes(b'unknown')
            with patch('plugg.vendor_payload.subprocess.run') as run:
                with self.assertRaises(core.HostError):
                    ua_setup.stage(source, root / 'output')
                run.assert_not_called()
            self.assertFalse((root / 'output').exists())

    def test_comparison_never_replaces_newer_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / 'staged'
            service = app / ua_setup.SERVICE
            service.parent.mkdir(parents=True)
            service.write_bytes(b'service')
            (app / 'UA Connect.exe').write_bytes(b'old')
            target = root / 'env/prefix/drive_c' / ua_setup.APPLICATION / 'UA Connect.exe'
            target.parent.mkdir(parents=True)
            target.write_bytes(b'new')
            result = ua_setup.compare(root / 'env', app)
            self.assertEqual(result['different'], ['UA Connect.exe'])
            self.assertEqual(result['missing'], [ua_setup.SERVICE])
            self.assertEqual(target.read_bytes(), b'new')

    def test_shared_recipe_checks_dependencies_and_preserves_consent(self):
        records = recipe_engine.catalogue([Path(recipe_engine.__file__).parent / 'recipes/community'])
        ref = 'plugg.universal-audio@1'
        self.assertEqual(shared_setups.validate(records, ref)['adapter'], 'ua-connect')
        with patch.object(ua_setup, 'join', return_value={}) as join:
            shared_setups.execute(records, ref, '/installer', '/env')
            join.assert_called_once_with('/installer', '/env', allow_electron_no_sandbox=False)

    def test_service_cannot_contain_recipe_commands(self):
        from plugg.windows_service import Service
        for bad in ('foo.exe & evil.exe', '../escape.exe', 'C:/other.exe', '/root.exe'):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                Service('Test', 'Test Service', bad)


class UAJoinTests(unittest.TestCase):
    def exercise(self, *, different=False, consent=True, fail_service=False):
        from contextlib import ExitStack
        from types import SimpleNamespace
        import shutil
        from plugg import ua_connect, licensed_setup, archive_component, windows_service, licensing
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            env = root / 'environments/shared'
            drive = env / 'prefix/drive_c'
            drive.mkdir(parents=True)
            pace = drive / 'protected-pace'
            pace.write_bytes(b'licensing unchanged')
            app = drive / ua_setup.APPLICATION / 'UA Connect.exe'
            if different:
                app.parent.mkdir(parents=True)
                app.write_bytes(b'newer')
            stack.enter_context(patch.object(licensing, 'guard'))
            stack.enter_context(patch.object(ua_connect, 'library_context', return_value=(SimpleNamespace(root=root), 'shared')))
            stack.enter_context(patch.object(ua_connect, 'require_idle_desktop'))
            stack.enter_context(patch.object(licensed_setup, 'prepare'))
            stack.enter_context(patch.object(ua_setup, 'prerequisites', return_value=(b'licensing unchanged', [], 'absent')))
            stack.enter_context(patch.object(licensed_setup, 'preservation_state', side_effect=lambda _: pace.read_bytes()))
            def staged(_, output):
                output.mkdir()
                (output / 'UA Connect.exe').write_bytes(b'verified')
                return {'files': {'UA Connect.exe': core.digest(output / 'UA Connect.exe')}}
            stage = stack.enter_context(patch.object(ua_setup, 'stage', side_effect=staged))
            def archives(store, prefix, *args):
                path = prefix / 'drive_c/Plugg/Tools/Archive/tar.exe'
                path.parent.mkdir(parents=True)
                path.write_bytes(b'tool')
            stack.enter_context(patch.object(archive_component, 'install', side_effect=archives))
            register = stack.enter_context(patch.object(windows_service, 'register', return_value=False,
                side_effect=core.HostError('service failed') if fail_service else None))
            configure = stack.enter_context(patch.object(ua_connect, 'configure'))
            if different or not consent or fail_service:
                with self.assertRaises(core.HostError):
                    ua_setup.join('/installer', env, allow_electron_no_sandbox=consent)
                self.assertFalse((env / 'ua-setup.json').exists())
                configure.assert_not_called()
                if different or not consent:
                    register.assert_not_called()
                if not consent:
                    stage.assert_not_called()
                if different:
                    self.assertEqual(app.read_bytes(), b'newer')
            else:
                first = ua_setup.join('/installer', env, allow_electron_no_sandbox=True)
                second = ua_setup.join('/installer', env, allow_electron_no_sandbox=True)
                self.assertEqual(first['files_added'], 2)
                self.assertEqual(second['files_added'], 0)
            self.assertEqual(pace.read_bytes(), b'licensing unchanged')

    def test_install_and_repeat(self):
        self.exercise()

    def test_no_downgrade(self):
        self.exercise(different=True)

    def test_consent_required_before_staging(self):
        self.exercise(consent=False)

    def test_service_failure_has_no_success_receipt(self):
        self.exercise(fail_service=True)


class UpdateTests(unittest.TestCase):
    def test_known_versions_are_recognised_by_hash_and_others_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            installer = Path(temporary) / 'UA.exe'
            installer.write_bytes(b'not a reviewed installer')
            with self.assertRaisesRegex(core.HostError, 'not been reviewed'):
                ua_setup.version_of(installer)
        self.assertIn('1.10.0.3844', ua_setup.VERSIONS)

    def test_update_replaces_only_changed_ua_connect_files_and_checks_pace_after(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = root / 'library/environments/env'
            app_dir = env / 'prefix/drive_c' / ua_setup.APPLICATION
            app_dir.mkdir(parents=True)
            (app_dir / 'UA Connect.exe').write_bytes(b'old')
            (app_dir / 'same.dll').write_bytes(b'same')
            (env / 'ua-setup.json').write_text('{"version": "1.9.6.3797", "files_added": 2}')
            staged = {'UA Connect.exe': b'new', 'same.dll': b'same', 'extra.dll': b'extra'}

            def fake_stage(installer, destination):
                destination.mkdir(parents=True)
                for name, data in staged.items():
                    (destination / name).write_bytes(data)
                return {'installer_sha256': 'c' * 64, 'version': '1.10.0.3844',
                        'files': {name: core.digest(destination / name) for name in staged}}

            store = type('S', (), {'root': root / 'library'})()
            with patch('plugg.licensing.guard'), patch('plugg.licensing.backup') as backup, \
                    patch('plugg.ua_connect.library_context', return_value=(store, 'job')), \
                    patch('plugg.ua_connect.require_idle_desktop'), \
                    patch('plugg.proton_session.foreign_prefix_processes', return_value=[]), \
                    patch.object(ua_setup, 'prerequisites', return_value=('state', [], 'present')), \
                    patch.object(ua_setup, 'stage', side_effect=fake_stage), \
                    patch('plugg.licensed_setup.preservation_state', return_value='state'), \
                    patch('plugg.core.lock'):
                (store.root / 'jobs/job').mkdir(parents=True)
                result = ua_setup.update(root / 'UA.exe', env)
            backup.assert_called_once()
            self.assertEqual((app_dir / 'UA Connect.exe').read_bytes(), b'new')
            self.assertEqual((app_dir / 'extra.dll').read_bytes(), b'extra')
            self.assertEqual(result['files_written'], 2)
            self.assertEqual(result['version'], '1.10.0.3844')
            self.assertEqual(result['updated_from'], '1.9.6.3797')

    def test_a_changed_pace_state_stops_the_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = root / 'library/environments/env'
            (env / 'prefix/drive_c').mkdir(parents=True)
            (env / 'ua-setup.json').write_text('{}')
            store = type('S', (), {'root': root / 'library'})()
            (store.root / 'jobs/job').mkdir(parents=True)

            def fake_stage(installer, destination):
                destination.mkdir(parents=True)
                return {'installer_sha256': 'c' * 64, 'version': '1.10.0.3844', 'files': {}}

            with patch('plugg.licensing.guard'), patch('plugg.licensing.backup'), \
                    patch('plugg.ua_connect.library_context', return_value=(store, 'job')), \
                    patch('plugg.ua_connect.require_idle_desktop'), \
                    patch('plugg.proton_session.foreign_prefix_processes', return_value=[]), \
                    patch.object(ua_setup, 'prerequisites', return_value=('before', [], 'present')), \
                    patch.object(ua_setup, 'stage', side_effect=fake_stage), \
                    patch('plugg.licensed_setup.preservation_state', return_value='after'), \
                    patch('plugg.core.lock'):
                with self.assertRaisesRegex(core.HostError, 'PACE or licensing state changed'):
                    ua_setup.update(root / 'UA.exe', env)
