"""The Visual C++ installer registers the runtime and then never exits under Wine."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugg import core, vc_component

ENTRY = '"DisplayName"="Microsoft Visual C++ 2015-2022 Redistributable (x64) - 14.44.35211"\n'


class SettleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = Path(self.tmp.name)
        (self.env / 'prefix').mkdir()
        self.registry = self.env / 'prefix' / 'system.reg'
        self.registry.write_text('WINE REGISTRY Version 2\n')

    def fake_run(self, register, exit_code=None):
        def run(command, env, log, check, timeout):
            for tick in range(1000):
                if tick == 2 and register:
                    self.registry.write_text(self.registry.read_text() + ENTRY)
                check()
                if exit_code is not None and tick == 5:
                    return exit_code
            raise core.HostError('This operation took too long.')
        return run

    def test_a_registered_runtime_ends_the_wait(self):
        clock = iter(range(0, 10000, 5))
        with patch.object(core, 'run_process', side_effect=self.fake_run(register=True)), \
                patch('time.monotonic', side_effect=lambda: next(clock)), \
                patch.object(vc_component, 'stop_environment') as stopped:
            self.assertEqual(vc_component.run_installer(self.env, ['vc'], lambda: None), 0)
        stopped.assert_called_once_with(self.env)

    def test_a_normal_exit_is_returned_as_is(self):
        with patch.object(core, 'run_process', side_effect=self.fake_run(register=False, exit_code=1638)), \
                patch.object(vc_component, 'stop_environment') as stopped:
            self.assertEqual(vc_component.run_installer(self.env, ['vc'], lambda: None), 1638)
        stopped.assert_not_called()

    def test_nothing_registered_still_times_out(self):
        with patch.object(core, 'run_process', side_effect=self.fake_run(register=False)), \
                patch.object(vc_component, 'stop_environment') as stopped:
            with self.assertRaises(core.HostError):
                vc_component.run_installer(self.env, ['vc'], lambda: None)
        stopped.assert_not_called()


if __name__ == '__main__':
    unittest.main()
