import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from plugg import core, vc_component


class VCComponentTest(unittest.TestCase):
    def test_failed_install_keeps_previous_dependency_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            record = directory / 'dependencies.json'
            previous = [{'sha256': 'previous'}]
            record.write_text(json.dumps(previous))
            with patch('plugg.artifacts.fetch', return_value=directory / 'vc.exe'), \
                    patch.object(core, 'run_process', return_value=5), self.assertRaises(core.HostError):
                vc_component.install(None, directory, directory / 'full', [{'sha256': 'new'}], lambda _: None, lambda: None)
            self.assertEqual(json.loads(record.read_text()), previous)

    def test_reboot_required_records_new_dependency_without_losing_existing(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            record = directory / 'dependencies.json'
            record.write_text('[{"sha256":"previous"}]')
            with patch('plugg.artifacts.fetch', return_value=directory / 'vc.exe'), \
                    patch.object(core, 'run_process', return_value=194):
                vc_component.install(None, directory, directory / 'full', [{'sha256': 'new'}], lambda _: None, lambda: None)
            self.assertEqual(json.loads(record.read_text()), [{'sha256': 'previous'}, {'sha256': 'new'}])

    def test_same_artifact_under_two_component_descriptions_runs_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            assets = [{'sha256': 'same', 'source': 'first'}, {'sha256': 'same', 'source': 'second'}]
            with patch('plugg.artifacts.fetch', return_value=directory / 'vc.exe') as fetch,                     patch.object(core, 'run_process', return_value=0) as execute:
                vc_component.install(None, directory, directory / 'full', assets, lambda _: None, lambda: None)
            fetch.assert_called_once()
            execute.assert_called_once()
            self.assertEqual(json.loads((directory / 'dependencies.json').read_text()), assets)

    def test_old_receipt_alone_does_not_skip_requested_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            asset = {'sha256': 'same'}
            (directory / 'dependencies.json').write_text(json.dumps([asset]))
            with patch('plugg.artifacts.fetch', return_value=directory / 'vc.exe'),                     patch.object(core, 'run_process', return_value=0) as execute:
                vc_component.install(None, directory, directory / 'full', [asset], lambda _: None, lambda: None)
            execute.assert_called_once()
