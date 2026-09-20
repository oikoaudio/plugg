import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from plugg import proton_session as session


class SessionConfigurationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        prefix = self.root / 'prefix'
        (prefix / 'drive_c').mkdir(parents=True)
        self.executable = self.root / 'fixture-executable'
        self.executable.write_text('#!/bin/sh\nexit 0\n')
        self.executable.chmod(0o700)
        self.cfg = {'prefix': str(prefix), 'proton': str(self.executable),
                    'runtime_entry': str(self.executable), 'graphics_backend': 'wined3d'}
        self.path = self.root / 'session.json'

    def save(self, cfg):
        self.path.write_text(json.dumps(cfg))

    def test_bad_configuration_fails_before_any_runtime_or_ipc(self):
        cases = [[], {}, {**self.cfg, 'proton': None}, {**self.cfg, 'prefix': 4},
                 {**self.cfg, 'idle_seconds': True}, {**self.cfg, 'runtime_entry': '/does-not-exist'}]
        for cfg in cases:
            self.save(cfg)
            with patch.object(session, 'ipc_directory') as ipc, patch.object(session.subprocess, 'Popen') as start:
                with self.assertRaises(RuntimeError):
                    session.ensure_session(self.path)
                ipc.assert_not_called()
                start.assert_not_called()

    def test_changed_manager_is_rejected_before_runtime(self):
        self.save({**self.cfg, 'manager_sha256': '0' * 64})
        with patch.object(session.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(RuntimeError, 'differs from its recorded version'):
                session.ensure_session(self.path)
            start.assert_not_called()

    def test_correct_manager_and_legacy_configuration_are_accepted(self):
        fingerprint = hashlib.sha256(Path(session.__file__).read_bytes()).hexdigest()
        for cfg in (self.cfg, {**self.cfg, 'manager_sha256': fingerprint}):
            self.save(cfg)
            self.assertEqual(session.configuration(self.path, verify_manager=True), cfg)

    def test_non_executable_runtime_is_rejected(self):
        self.executable.chmod(0o600)
        self.save(self.cfg)
        with self.assertRaisesRegex(RuntimeError, 'executable unavailable'):
            session.configuration(self.path)

    def test_snapshot_validation_does_not_reread_changed_file(self):
        snapshot = json.dumps(self.cfg).encode()
        self.path.write_text('{}')
        self.assertEqual(session.configuration(self.path, contents=snapshot), self.cfg)
