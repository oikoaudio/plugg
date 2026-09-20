"""The licensing command must never make a risky choice on the user's behalf."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugg import licensing
from plugg.__main__ import main, parse_product

REGISTRY = ('WINE REGISTRY Version 2\n\n'
            '[Software\\\\Microsoft\\\\Cryptography] 1774855987\n'
            '"MachineGuid"="0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"\n')


class LicensingCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = Path(self.tmp.name) / 'environments' / 'one'
        (self.env / 'prefix').mkdir(parents=True)
        (self.env / 'prefix/system.reg').write_text(REGISTRY)

    def invoke(self, *arguments):
        output = io.StringIO()
        with patch('sys.argv', ['plugg', 'licensing', *arguments, '--environment', str(self.env)]), \
             patch('plugg.__main__.Store', side_effect=AssertionError('Licensing command opened a library')), \
             contextlib.redirect_stderr(output), contextlib.redirect_stdout(output):
            code = main()
        return code, output.getvalue()

    def test_product_syntax_accepts_a_recovery_method_and_remaining_count(self):
        self.assertEqual(parse_product('ExampleSynth:limited-activations:3'),
                         {'name': 'ExampleSynth', 'recovery': 'limited-activations', 'activations_remaining': 3})
        self.assertEqual(parse_product('Skaka:reactivatable'),
                         {'name': 'Skaka', 'recovery': 'reactivatable'})
        for text in ('ExampleSynth', 'ExampleSynth:limited-activations:many', ':reactivatable', 'a:b:c:d'):
            with self.assertRaises(ValueError):
                parse_product(text)

    def test_protect_then_status_reports_the_recorded_products(self):
        code, _ = self.invoke('protect', '--product', 'ExampleSynth:limited-activations:3')
        self.assertEqual(code, 0)
        code, output = self.invoke('status')
        report = json.loads(output)
        self.assertEqual(code, 0)
        self.assertTrue(report['protected'])
        self.assertEqual(report['severity'], 'limited-activations')
        self.assertTrue(report['matches_recorded_identity'])

    def test_protect_requires_a_product(self):
        code, message = self.invoke('protect')
        self.assertEqual(code, 1)
        self.assertIn('--product', message)

    def test_unknown_recovery_method_is_rejected_with_the_valid_ones(self):
        code, message = self.invoke('protect', '--product', 'ExampleSynth:whenever')
        self.assertEqual(code, 1)
        self.assertIn('limited-activations', message)

    def test_acknowledge_without_confirmation_prints_the_required_phrase(self):
        self.invoke('protect', '--product', 'ExampleSynth:limited-activations:3')
        code, message = self.invoke('acknowledge', '--operation', 'recreate_prefix')
        self.assertEqual(code, 1)
        self.assertIn(licensing.CONFIRMATION['limited-activations'], message)

    def test_acknowledge_with_the_wrong_phrase_is_refused(self):
        self.invoke('protect', '--product', 'Bound:deactivate-first')
        code, message = self.invoke('acknowledge', '--operation', 'recreate_prefix',
                                    '--confirm', 'I HAVE DEACTIVATED')
        self.assertEqual(code, 1)
        self.assertIn('Deactivate them', message)

    def test_acknowledge_with_the_right_phrase_records_one_operation(self):
        self.invoke('protect', '--product', 'Bound:deactivate-first')
        code, output = self.invoke('acknowledge', '--operation', 'recreate_prefix',
                                   '--confirm', licensing.CONFIRMATION['deactivate-first'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)['operation'], 'recreate_prefix')

    def test_backup_and_restore_round_trip_through_the_command(self):
        self.invoke('protect', '--product', 'Bound:deactivate-first')
        code, output = self.invoke('backup', '--label', 'before-test')
        self.assertEqual(code, 0)
        self.assertIn('system.reg', [item['name'] for item in json.loads(output)['files']])
        code, listing = self.invoke('backups')
        identifier = json.loads(listing)[0]['id']
        (self.env / 'prefix/system.reg').write_text(REGISTRY.replace('0f1e2d3c', '999e2d3c'))
        with patch('plugg.vendors.applications', return_value=[]):
            code, output = self.invoke('restore', '--recovery-point', identifier,
                                       '--confirm', licensing.CONFIRMATION['deactivate-first'])
        self.assertEqual(code, 0)
        self.assertIn('0f1e2d3c', (self.env / 'prefix/system.reg').read_text())

    def test_restore_needs_a_named_recovery_point(self):
        self.invoke('protect', '--product', 'Bound:deactivate-first')
        code, message = self.invoke('restore', '--confirm', licensing.CONFIRMATION['deactivate-first'])
        self.assertEqual(code, 1)
        self.assertIn('--recovery-point', message)

    def test_status_of_an_unprotected_environment_is_not_an_error(self):
        code, output = self.invoke('status')
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(output)['protected'])


if __name__ == '__main__':
    unittest.main()
