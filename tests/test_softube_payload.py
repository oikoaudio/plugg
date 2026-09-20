"""Extraction rejects unknown inputs and malformed framing before publication."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugg import core, softube_payload as payload


class SoftubePayloadTests(unittest.TestCase):
    def test_unknown_installer_never_reaches_decoder(self):
        with tempfile.TemporaryDirectory() as tmp:
            installer = Path(tmp) / 'setup.exe'
            installer.write_bytes(b'unknown')
            with patch.object(payload, 'decode_chunks') as decoder:
                with self.assertRaises(core.HostError):
                    payload.extract_service(installer)
                decoder.assert_not_called()

    def test_wrong_hash_rejected_before_decode(self):
        with tempfile.TemporaryDirectory() as tmp:
            installer = Path(tmp) / 'setup.exe'
            installer.write_bytes(b'unknown')
            with patch.object(payload, 'HELPER_SIZE', 7), patch.object(payload, 'decode_chunks') as decoder:
                with self.assertRaisesRegex(core.HostError, 'hash'):
                    payload.extract_service(installer)
                decoder.assert_not_called()

    def test_malformed_chunks(self):
        for data in (b'', b'\0', b'\x05\0\0x', b'\0\0\0trailing'):
            with self.subTest(data=data), self.assertRaises(core.HostError):
                payload.decode_chunks(data, 10)

    def test_real_empty_bzip_stream(self):
        self.assertEqual(payload.decode_chunks(b'\x01\0\0\x17\0\0\0', 0), b'')

    def test_output_budget_is_shared_across_chunks(self):
        framed = b'\x01\0\0x' * 2 + b'\0\0\0'
        with patch.object(payload, 'decompress_with_framing', return_value=(b'abc', 'current')) as decoder:
            self.assertEqual(payload.decode_chunks(framed, 6), b'abcabc')
            self.assertEqual([c.kwargs['max_output_size'] for c in decoder.call_args_list], [6, 3])
