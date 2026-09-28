"""A launch whose Windows program dies must fail, not wait for it.

Wine's launcher can outlive the program it started: when a plug-in takes the
Windows host down, the launcher stays in NtWaitForMultipleObjects and the DAW
waits on a process that no longer exists. That reads as a frozen DAW rather
than a failed plug-in, so the session watches the program itself.
"""
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from plugg import proton_session


class FakeProcess:
    pid = 0

    def __init__(self, alive=True):
        self.alive = alive

    def poll(self):
        return None if self.alive else 0


class WindowsProcessAliveTests(unittest.TestCase):
    def test_it_finds_this_process_by_its_program_name(self):
        with open('/proc/self/cmdline', 'rb') as handle:
            program = handle.read().split(b'\0')[0].decode()
        self.assertTrue(proton_session.windows_process_alive(program))
        self.assertFalse(proton_session.windows_process_alive(program, os.getpgrp() + 1))

    def test_an_absent_program_is_not_alive(self):
        self.assertFalse(proton_session.windows_process_alive('/nonexistent/yabridge-host.exe.so'))


@unittest.skipUnless(shutil.which('cc') and shutil.which('bash'), 'needs a C compiler and bash')
class DeadMainThreadTests(unittest.TestCase):
    """A host whose main thread died is dead, even beside a healthy twin.

    The processes here are shaped like a real launch, as ps shows one under
    Proton: the launcher (start.exe) carries the host's Unix path as an
    argument and waits for it, and the host's own argv[0] is that path in
    Windows form.
    """
    WINDOWS_NAME = 'X:\\bundle\\Contents\\x86_64-linux\\yabridge-host.exe.so'

    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory()
        cls.program = os.path.join(cls.scratch.name, 'yabridge-host.exe.so')
        source = os.path.join(os.path.dirname(__file__), 'fixtures', 'leader-exits.c')
        subprocess.run(['cc', '-O1', '-pthread', source, '-o', cls.program], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def start(self, *args):
        process = subprocess.Popen(
            ['bash', '-c', '(exec -a "$1" "$0" "${@:2}") & wait', self.program, self.WINDOWS_NAME, *args],
            start_new_session=True)
        self.addCleanup(self.end, process)
        return process

    @staticmethod
    def end(process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)

    def state(self, process, wanted):
        deadline = time.monotonic() + 5
        while (found := proton_session.windows_process_state(self.program, process.pid)) != wanted \
                and time.monotonic() < deadline:
            time.sleep(0.05)
        return found

    def test_the_launcher_is_not_mistaken_for_the_host(self):
        dead = self.start()
        self.assertEqual(self.state(dead, 'exited'), 'exited')
        self.assertIsNone(dead.poll(), 'the launcher should still be waiting, as Wine\'s does')

    def test_a_dead_main_thread_is_not_hidden_by_another_instance(self):
        healthy = self.start('stay')
        dead = self.start()
        self.assertEqual(self.state(dead, 'exited'), 'exited')
        self.assertEqual(self.state(healthy, 'running'), 'running')

    def test_the_watch_ends_a_launch_whose_host_lost_its_main_thread(self):
        self.start('stay')
        dead = self.start()
        self.assertTrue(proton_session.watch_windows_process(
            self.program, dead, threading.Event(), appeared_within=5, interval=0.05))

    def test_the_watch_leaves_a_healthy_launch_alone(self):
        self.start()
        healthy = self.start('stay')
        stopping = threading.Event()
        threading.Timer(1, stopping.set).start()
        self.assertFalse(proton_session.watch_windows_process(
            self.program, healthy, stopping, appeared_within=5, interval=0.05))

    def test_a_host_first_seen_dead_is_reported(self):
        # A plug-in can take the host down before the first look.
        dead = self.start()
        self.assertEqual(self.state(dead, 'exited'), 'exited')
        self.assertTrue(proton_session.watch_windows_process(
            self.program, dead, threading.Event(), appeared_within=5, interval=0.05))


class WatchdogTests(unittest.TestCase):
    def watch(self, states, process, appeared_within=60):
        calls = iter(states)
        with patch.object(proton_session, 'windows_process_state', lambda *_: next(calls, None)):
            return proton_session.watch_windows_process('program', process, threading.Event(),
                                                        appeared_within=appeared_within, interval=0)

    def test_a_program_that_ran_and_vanished_is_reported(self):
        self.assertTrue(self.watch(['running', 'running', None], FakeProcess()))

    def test_a_program_that_never_appears_is_not_reported_as_dead(self):
        # Something else may be slow to start; only the launcher's own exit ends this.
        self.assertFalse(self.watch([None, None], FakeProcess(), appeared_within=0.0))

    def test_a_finished_launcher_ends_the_watch(self):
        self.assertFalse(self.watch(['running', 'running'], FakeProcess(alive=False)))

    def test_a_stopping_session_ends_the_watch(self):
        stopping = threading.Event()
        stopping.set()
        with patch.object(proton_session, 'windows_process_state', lambda *_: 'running'):
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
