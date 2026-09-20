import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from plugg import protocols


class ProtocolTests(unittest.TestCase):
    def test_uri_is_one_unchanged_argument_without_shell_or_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);launcher=root/'launcher';launcher.touch()
            config=root/'config.json';config.write_text(json.dumps({'launcher':str(launcher),'application':'Native Access.exe'}))
            uri='native-access://callback?code=synthetic%20test&state=a;b'
            with patch.object(protocols.subprocess,'Popen') as launch:
                protocols.dispatch(config,uri)
                self.assertEqual(launch.call_args.args[0],[str(launcher),'Native Access.exe',uri])
                self.assertFalse(launch.call_args.kwargs.get('shell',False))
                self.assertEqual(launch.call_args.kwargs['stdout'],protocols.subprocess.DEVNULL)
                self.assertEqual(launch.call_args.kwargs['stderr'],protocols.subprocess.DEVNULL)

    def test_rejects_other_protocols_and_control_characters_before_launch(self):
        with patch.object(protocols.subprocess,'Popen') as launch:
            for uri in ['https://example.com','file:///tmp/test','native-access://a\nb','native-access://'+('x'*17000)]:
                with self.assertRaises(ValueError):protocols.dispatch('/unused',uri)
            launch.assert_not_called()
