import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from plugg import native_access_routing as router, core


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / 'session.json'
        self.config = Path(self.tmp.name) / 'native-access-protocol.json'
        self.stack = patch.object(router, 'state_path', return_value=self.state)
        self.stack.start();self.addCleanup(self.stack.stop)

    def test_active_session_routes_without_persisting_uri_and_clears_on_close(self):
        uri = 'native-access://callback?code=synthetic&state=unchanged'
        with patch.object(router, 'install_handler'), router.active(self.config):
            with patch.object(router.vendors, 'running_programs', return_value=[(42, 'Native Access.exe')]), patch.object(router.protocols, 'dispatch') as dispatch:
                router.route(uri)
                dispatch.assert_called_once_with(self.config, uri)
            self.assertNotIn('synthetic', self.state.read_text())
        self.assertFalse(self.state.exists())

    def test_second_session_cannot_replace_first(self):
        with patch.object(router, 'install_handler'), router.active(self.config):
            before = self.state.read_text()
            with self.assertRaisesRegex(core.HostError, 'already owns'):
                with router.active(self.config.with_name('other.json')):
                    self.fail('second owner accepted')
            self.assertEqual(before, self.state.read_text())

    def test_stale_pid_identity_is_not_reused(self):
        self.state.write_text(json.dumps({'pid':123,'process_start':'old','config':str(self.config)}))
        with patch.object(router, 'process_identity', return_value='new'), patch.object(router.protocols, 'dispatch') as dispatch:
            with self.assertRaises(core.HostError):
                router.route('native-access://callback?code=synthetic')
            dispatch.assert_not_called()

    def test_closed_windows_app_is_not_relaunched_by_callback(self):
        with patch.object(router, 'install_handler'), router.active(self.config):
            with patch.object(router.vendors, 'running_programs', return_value=[]), patch.object(router.protocols, 'dispatch') as dispatch:
                with self.assertRaises(core.HostError):
                    router.route('native-access://callback?code=synthetic')
                dispatch.assert_not_called()

    def test_invalid_uri_rejected_before_state_access(self):
        with patch.object(router, 'state_path') as state:
            with self.assertRaises(ValueError):router.route('file:///tmp/no')
            state.assert_not_called()
