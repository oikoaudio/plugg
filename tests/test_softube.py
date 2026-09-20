"""Shared PACE launch must not replace licensing or stop another manager."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from plugg import core, softube, ua_connect


class SoftubeTests(unittest.TestCase):
    def test_configuration_preserves_existing_runtime_and_pace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = ['launch-full-proton', 'session.json', 'prefix/system.reg',
                     'prefix/drive_c/Program Files/PACE/LDSvc.exe',
                     'prefix/drive_c/' + softube.APP, 'prefix/drive_c/' + softube.SERVICE]
            for name in files:
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b'original')
            softube.configure(root)
            self.assertTrue(softube.configured(root))
            batch = (root / 'prefix/drive_c/Plugg/launch-softube-central.cmd').read_bytes()
            self.assertIn(b'--disable-gpu', batch)
            self.assertNotIn(b'--no-sandbox', batch)
            for name in files:
                self.assertEqual((root / name).read_bytes(), b'original')

    def test_missing_service_does_not_create_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(core.HostError):
                softube.configure(tmp)
            self.assertFalse((Path(tmp) / 'launch-softube-central').exists())

    def test_another_manager_or_installer_blocks_release(self):
        for name in ('iLok License Manager.exe', 'UA Connect.exe', 'setup.exe', 'yabridge-host.exe'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'session.json').write_text(json.dumps({'proton': '/runtime/proton'}))
                with patch.object(ua_connect, 'require_idle_desktop'), \
                     patch.object(ua_connect.vendors, 'applications', return_value=[42]), \
                     patch.object(Path, 'read_bytes', return_value=name.encode()+b'\0'), \
                     patch.object(ua_connect.subprocess, 'run') as command:
                    with self.assertRaises(core.HostError):
                        softube.release(root)
                    command.assert_not_called()

    def test_only_own_softube_window_controls_release(self):
        child = Mock(pid=123)
        child.poll.return_value = None
        windows = [Mock(stdout=json.dumps([{'title': 'Softube Central', 'pid': 456}]))]
        windows += [Mock(stdout=json.dumps([{'title': 'Softube Central', 'pid': 999}])) for _ in range(3)]
        release = Mock()
        with patch.dict(ua_connect.os.environ, {'HYPRLAND_INSTANCE_SIGNATURE': 'test'}), \
             patch.object(ua_connect.subprocess, 'run', side_effect=windows), \
             patch.object(ua_connect, 'foreign_prefix_processes', return_value=[456]), \
             patch.object(ua_connect, 'descendants', return_value={123, 456}), \
             patch.object(ua_connect.time, 'sleep'):
            self.assertEqual(ua_connect.wait_for_helper(child, '/environment', title=softube.TITLE, release=release), 0)
        release.assert_called_once_with('/environment', bootstrap_pids={123, 456})
