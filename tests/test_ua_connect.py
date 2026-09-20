"""Safety boundaries for the local UA Connect compatibility launcher."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugg import core, ua_connect


class UAConnectTests(unittest.TestCase):
    def test_missing_consent_does_not_modify_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(core.HostError):
                ua_connect.configure(tmp)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_missing_dependency_does_not_publish_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(core.HostError):
                ua_connect.configure(tmp, allow_electron_no_sandbox=True)
            self.assertFalse((Path(tmp) / 'launch-ua-connect').exists())

    def test_helper_configuration_preserves_audio_and_license_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('launch-full-proton',
                         'prefix/drive_c/Program Files/UA Connect/UA Connect.exe',
                         'prefix/drive_c/Plugg/Tools/Archive/tar.exe',
                         'launch-plugin', 'session.json', 'prefix/system.reg'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'preserve-me')
            ua_connect.configure(root, allow_electron_no_sandbox=True)
            for name in ('launch-plugin', 'session.json', 'prefix/system.reg'):
                self.assertEqual((root / name).read_bytes(), b'preserve-me')
            self.assertTrue((root / 'launch-ua-connect').stat().st_mode & 0o100)
            batch = (root / 'prefix/drive_c/Plugg/launch-ua-connect.cmd').read_bytes()
            self.assertIn(b'--disable-gpu --no-sandbox', batch)
            self.assertIn(b'Archive;%PATH%', batch)

    def test_active_daw_blocks_runtime_commands(self):
        with patch.object(ua_connect, 'require_idle_desktop', side_effect=core.HostError('DAW open')), \
             patch.object(ua_connect.subprocess, 'run') as command:
            with self.assertRaises(core.HostError):
                ua_connect.prepare_runtime('/not-accessed')
            command.assert_not_called()

    def test_unknown_windows_application_blocks_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'session.json').write_text(json.dumps({'proton': '/runtime/proton'}))
            with patch.object(ua_connect, 'require_idle_desktop'), \
                 patch.object(ua_connect.vendors, 'applications', return_value=[42]), \
                 patch.object(Path, 'read_bytes', return_value=b'C:\\setup.exe\0'), \
                 patch.object(ua_connect.subprocess, 'run') as command:
                with self.assertRaisesRegex(core.HostError, 'setup.exe'):
                    ua_connect.prepare_runtime(root)
                command.assert_not_called()

    def test_wines_own_background_helpers_do_not_block_the_handoff(self):
        # tabtip.exe lingered in the iLok environment and stopped every scan
        # after UA Connect or iLok License Manager closed.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'session.json').write_text(json.dumps({'proton': '/runtime/proton'}))
            for name in (b'C:\\windows\\system32\\tabtip.exe', b'C:\\windows\\system32\\xalia.exe'):
                with patch.object(ua_connect, 'require_idle_desktop'), \
                     patch.object(ua_connect.vendors, 'applications', return_value=[42]), \
                     patch.object(ua_connect, 'foreign_prefix_processes', return_value=[]), \
                     patch.object(ua_connect, 'stop_idle_session'), \
                     patch.object(Path, 'read_bytes', return_value=name + b'\0'):
                    ua_connect.prepare_runtime(root)

    def test_closing_window_releases_only_owned_helper_runtime(self):
        from unittest.mock import Mock
        child = Mock(pid=123)
        child.poll.return_value = None
        results = [Mock(stdout=json.dumps([{'title': 'UA Connect', 'pid': 456}]))]
        results += [Mock(stdout='[]') for _ in range(3)]
        with patch.dict(ua_connect.os.environ, {'HYPRLAND_INSTANCE_SIGNATURE': 'test'}), \
             patch.object(ua_connect.subprocess, 'run', side_effect=results), \
             patch.object(ua_connect, 'foreign_prefix_processes', return_value=[456]), \
             patch.object(ua_connect, 'descendants', return_value={123, 456}), \
             patch.object(ua_connect, 'prepare_runtime') as release, \
             patch.object(ua_connect.time, 'sleep'):
            self.assertEqual(ua_connect.wait_for_helper(child, '/environment'), 0)
        release.assert_called_once_with('/environment', bootstrap_pids={123, 456})

    def test_compositor_failure_never_means_helper_closed(self):
        from unittest.mock import Mock
        child = Mock(pid=123, returncode=0)
        child.poll.side_effect = [None, None, 0]
        with patch.dict(ua_connect.os.environ, {'HYPRLAND_INSTANCE_SIGNATURE': 'test'}), \
             patch.object(ua_connect.subprocess, 'run', side_effect=OSError('compositor unavailable')), \
             patch.object(ua_connect, 'prepare_runtime') as release, \
             patch.object(ua_connect.time, 'sleep'):
            self.assertEqual(ua_connect.wait_for_helper(child, '/environment'), 0)
        release.assert_not_called()
