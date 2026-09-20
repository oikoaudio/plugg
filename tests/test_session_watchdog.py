"""A launch whose Windows program dies must fail, not wait for it.

Wine's launcher can outlive the program it started: when a plug-in takes the
Windows host down, the launcher stays in NtWaitForMultipleObjects and the DAW
waits on a process that no longer exists. That reads as a frozen DAW rather
than a failed plug-in, so the session watches the program itself.
"""
import os
import threading
import time
import unittest
from unittest.mock import patch

from plugg import proton_session


class FakeProcess:
    def __init__(self, alive=True):
        self.alive = alive

    def poll(self):
        return None if self.alive else 0


class WindowsProcessAliveTests(unittest.TestCase):
    def test_it_finds_this_process_by_its_command_line(self):
        with open('/proc/self/cmdline', 'rb') as handle:
            marker = handle.read().split(b'\0')[0].decode()
        self.assertTrue(proton_session.windows_process_alive(marker))

    def test_an_absent_program_is_not_alive(self):
        self.assertFalse(proton_session.windows_process_alive('/nonexistent/yabridge-host.exe.so'))


class WatchdogTests(unittest.TestCase):
    def watch(self, states, process, appeared_within=60):
        calls = iter(states)
        with patch.object(proton_session, 'windows_process_alive', lambda _: next(calls, False)):
            return proton_session.watch_windows_process('program', process, threading.Event(),
                                                        appeared_within=appeared_within, interval=0)

    def test_a_program_that_ran_and_vanished_is_reported(self):
        self.assertTrue(self.watch([True, True, False], FakeProcess()))

    def test_a_program_that_never_appears_is_not_reported_as_dead(self):
        # Something else may be slow to start; only the launcher's own exit ends this.
        self.assertFalse(self.watch([False, False], FakeProcess(), appeared_within=0.0))

    def test_a_finished_launcher_ends_the_watch(self):
        self.assertFalse(self.watch([True, True], FakeProcess(alive=False)))

    def test_a_stopping_session_ends_the_watch(self):
        stopping = threading.Event()
        stopping.set()
        with patch.object(proton_session, 'windows_process_alive', lambda _: True):
            self.assertFalse(proton_session.watch_windows_process('program', FakeProcess(), stopping, interval=0))


class SessionDiagnosticsTests(unittest.TestCase):
    def test_wine_errors_are_not_silenced(self):
        """A crash inside Wine must reach the log; -all hid the one that started this."""
        source = (proton_session.__file__)
        with open(source) as handle:
            text = handle.read()
        self.assertIn("WINEDEBUG=os.environ.get('PLUGG_WINEDEBUG','fixme-all')", text)
        self.assertNotIn("WINEDEBUG='-all'", text)


if __name__ == '__main__':
    unittest.main()
