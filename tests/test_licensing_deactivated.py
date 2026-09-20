"""Recording a deactivation the user made: explicit, per product, and never inferred."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugg import licensing
from plugg.__main__ import main
from test_licensing import REGISTRY


class DeactivatedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = Path(self.tmp.name) / 'environments' / 'one'
        (self.env / 'prefix').mkdir(parents=True)
        (self.env / 'prefix/system.reg').write_text(REGISTRY)
        (self.env / 'prefix/version').write_text('UMU-Proton-10.0-4\n')
        licensing.protect(self.env, [{'name': 'Example Synth', 'recovery': 'deactivate-first'},
                                     {'name': 'Example Reverb', 'recovery': 'reactivatable'}])

    def test_the_confirmation_names_the_products(self):
        with self.assertRaisesRegex(licensing.LicensedEnvironmentError, 'I have deactivated Example Synth'):
            licensing.deactivated(self.env, ['Example Synth'], 'yes')
        self.assertEqual(len(licensing.read(self.env)['products']), 2)

    def test_one_product_moves_to_history_and_protection_stays(self):
        record = licensing.deactivated(self.env, ['example synth'], 'I have deactivated Example Synth')
        self.assertTrue(record['protected'])
        self.assertEqual([item['name'] for item in record['products']], ['Example Reverb'])
        self.assertEqual(record['deactivated'][0]['name'], 'Example Synth')
        self.assertIn('deactivated_at', record['deactivated'][0])
        self.assertEqual(licensing.status(self.env)['severity'], 'reactivatable')

    def test_when_nothing_is_left_the_environment_is_no_longer_protected(self):
        record = licensing.deactivated(self.env, ['Example Synth', 'Example Reverb'],
                                       'I have deactivated Example Reverb, Example Synth')
        self.assertFalse(record['protected'])
        self.assertEqual(record['products'], [])
        self.assertTrue(licensing.guard(self.env, 'recreate_prefix')['allowed'])
        self.assertIn('identity', record)

    def test_an_unrecorded_product_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'Not recorded'):
            licensing.deactivated(self.env, ['Other'], 'I have deactivated Other')

    def test_the_command_asks_for_the_phrase_first(self):
        output = io.StringIO()
        with patch('sys.argv', ['plugg', 'licensing', 'deactivated', '--environment', str(self.env),
                                '--product', 'Example Synth']), contextlib.redirect_stdout(output):
            self.assertEqual(main(), 1)
        self.assertIn('--confirm "I have deactivated Example Synth"', output.getvalue())
        self.assertEqual(len(licensing.read(self.env)['products']), 2)


if __name__ == '__main__':
    unittest.main()
