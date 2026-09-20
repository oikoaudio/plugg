import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from plugg import core, softube_setup as setup


class SoftubeSetupTests(unittest.TestCase):
    def test_unknown_source_never_unpacks_or_publishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'setup.exe'
            source.write_bytes(b'unknown')
            with patch.object(setup.shutil, 'which', return_value='/usr/bin/bsdtar'), patch.object(setup.subprocess, 'run') as run:
                with self.assertRaises(core.HostError):
                    setup.stage(source, root / 'out')
                run.assert_not_called()
            self.assertFalse((root / 'out').exists())
            self.assertEqual(list(root.iterdir()), [source])

    def test_existing_destination_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(core.HostError):
                setup.stage('/missing', tmp)

    def test_vendor_symlink_escape_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drive = root / 'env/prefix/drive_c'
            drive.mkdir(parents=True)
            (drive / 'Program Files').symlink_to(root, target_is_directory=True)
            with self.assertRaises(core.HostError):
                setup.destination_path(root / 'env', 'Program Files/Softube/test.exe')

    def test_payload_links_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'link').symlink_to('/etc/passwd')
            with self.assertRaises(core.HostError):
                setup.file_manifest(root)


class SharedJoinTests(unittest.TestCase):
    def exercise(self, *, different=False, registration_error=False, missing_powershell=False, vc=()):
        from contextlib import ExitStack
        from unittest.mock import Mock
        from plugg import softube, softube_payload, ua_connect
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            env = root / 'environments/shared'
            drive = env / 'prefix/drive_c'
            power = drive / 'Program Files/PowerShell/7/pwsh.exe'
            power.parent.mkdir(parents=True)
            if not missing_powershell:
                power.write_bytes(b'power')
            (env / 'session.json').write_text('{"graphics_backend":"dxvk"}')
            pace = drive / 'PACE-test-state'
            pace.write_bytes(b'activated identity')
            source = root / 'source'
            (source / 'central').mkdir(parents=True)
            (source / 'central/Softube Central.exe').write_bytes(b'central')
            (source / 'InstallerService.exe').write_bytes(b'service')
            target = drive / softube.APP
            if different:
                target.parent.mkdir(parents=True)
                target.write_bytes(b'newer central')
            store = Mock(root=root)
            stack.enter_context(patch.object(ua_connect, 'library_context', return_value=(store, 'shared')))
            stack.enter_context(patch.object(ua_connect, 'require_idle_desktop'))
            stack.enter_context(patch.object(setup, 'preservation_state', side_effect=lambda _: pace.read_bytes()))
            stack.enter_context(patch.object(setup, 'service_status', return_value='matching'))
            stack.enter_context(patch.object(softube, 'prepare'))
            configure = stack.enter_context(patch.object(softube, 'configure'))
            register = stack.enter_context(patch.object(setup, 'register_service', return_value=False,
                side_effect=core.HostError('registration failed') if registration_error else None))
            import shutil, hashlib
            def stage(_, destination):
                shutil.copytree(source, destination)
                return {'installer_sha256': 'reviewed', 'service_sha256': 'reviewed'}
            stack.enter_context(patch.object(setup, 'stage', side_effect=stage))
            stack.enter_context(patch.object(softube_payload, 'SERVICE_SHA256', hashlib.sha256(b'service').hexdigest()))
            added = stack.enter_context(patch.object(setup, 'add_powershell',
                                                     side_effect=lambda *_: power.write_bytes(b'power')))
            import json as _json
            runtimes = stack.enter_context(patch.object(setup, 'add_vc_runtimes', side_effect=lambda _s, e, assets:
                                                        (e / 'dependencies.json').write_text(_json.dumps(list(assets)))))
            if different or registration_error:
                with self.assertRaises(core.HostError):
                    setup.join('/installer', env)
                self.assertFalse((env / 'softube-setup.json').exists())
                configure.assert_not_called()
                if different:
                    register.assert_not_called()
                    self.assertEqual(target.read_bytes(), b'newer central')
                    self.assertFalse((drive / softube.SERVICE).exists())
            else:
                first = setup.join('/installer', env, vc_assets=list(vc))
                second = setup.join('/installer', env, vc_assets=list(vc))
                self.assertEqual(first['files_added'], 2)
                self.assertEqual(second['files_added'], 0)
                self.assertEqual(target.read_bytes(), b'central')
                self.assertEqual((drive / softube.SERVICE).read_bytes(), b'service')
            self.assertEqual(added.call_count, 1 if missing_powershell else 0)
            if not (different or registration_error):
                self.assertEqual(runtimes.call_count, 1 if vc else 0)
            self.assertEqual(pace.read_bytes(), b'activated identity')

    def test_join_and_repeat_preserve_pace(self):
        self.exercise()

    def test_missing_powershell_is_added_once_before_joining(self):
        # Softube Central's installer service needs PowerShell; the iLok
        # environment is created without it.
        self.exercise(missing_powershell=True)

    def test_the_visual_cpp_runtime_is_installed_once_before_joining(self):
        self.exercise(vc=[{'sha256': 'a' * 64, 'url': 'https://download.microsoft.com/x.exe'}])

    def test_newer_helper_is_not_downgraded(self):
        self.exercise(different=True)

    def test_registration_failure_is_not_reported_as_success(self):
        self.exercise(registration_error=True)

    def test_unprotected_environment_is_refused(self):
        from plugg import licensing
        with tempfile.TemporaryDirectory() as tmp, patch.object(licensing, 'guard'), \
             patch.object(licensing, 'verify', return_value={'protected': False, 'matches': None}):
            with self.assertRaisesRegex(core.HostError, 'verified licensing identity'):
                setup.preservation_state(tmp)


class ServiceRecordTests(unittest.TestCase):
    def test_existing_service_configuration(self):
        from plugg import licensing
        section = setup.SERVICE_SECTION.casefold()
        correct = {(section, 'imagepath'): 'str(2):"\\"C:\\\\Program Files\\\\Softube\\\\InstallerDaemon\\\\InstallerService.exe\\""',
                   (section, 'start'): 'dword:00000003',
                   (section, 'type'): 'dword:00000010',
                   (section, 'objectname'): '"LocalSystem"'}
        with patch.object(licensing, '_registry_values', return_value=correct):
            self.assertEqual(setup.service_status('/env'), 'matching')
        for name, value in (('start', 'dword:00000002'), ('type', 'dword:00000001'),
                            ('objectname', '"different user"'), ('imagepath', '"wrong.exe"')):
            with self.subTest(name=name), patch.object(licensing, '_registry_values',
                    return_value={**correct, (section, name): value}):
                self.assertEqual(setup.service_status('/env'), 'different')
        with patch.object(licensing, '_registry_values', return_value={}):
            self.assertEqual(setup.service_status('/env'), 'absent')

    def test_existing_service_does_not_start_wine(self):
        with patch.object(setup, 'service_status', return_value='matching'), \
             patch.object(setup.subprocess, 'Popen') as start:
            self.assertFalse(setup.register_service('/env'))
            start.assert_not_called()


class OpenRepairTests(unittest.TestCase):
    """Opening Central brings the shared environment up to what the recipe requires."""

    def run_with(self, *, pwsh, recorded):
        from unittest.mock import patch
        from plugg import softube, licensing
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            if pwsh:
                path = directory / 'prefix/drive_c/Program Files/PowerShell/7/pwsh.exe'
                path.parent.mkdir(parents=True)
                path.write_bytes(b'pwsh')
            if recorded:
                import json
                from plugg import recipe_engine, shared_setups
                records = recipe_engine.catalogue([Path(softube.__file__).parent / 'recipes/community'])
                (directory / 'dependencies.json').write_text(json.dumps(shared_setups.validate(records, softube.RECIPE)['vc_assets']))
            with patch.object(licensing, 'guard'), \
                    patch.object(setup, 'add_powershell') as powershell, \
                    patch.object(setup, 'add_vc_runtimes') as runtimes:
                added = softube.ensure_prerequisites(object(), directory)
            return added, powershell.call_count, runtimes.call_count

    def test_a_complete_environment_is_left_alone(self):
        self.assertEqual(self.run_with(pwsh=True, recorded=True), ([], 0, 0))

    def test_a_missing_runtime_is_added_before_central_opens(self):
        self.assertEqual(self.run_with(pwsh=True, recorded=False), (['Visual C++ runtime'], 0, 1))
        self.assertEqual(self.run_with(pwsh=False, recorded=False), (['PowerShell', 'Visual C++ runtime'], 1, 1))
