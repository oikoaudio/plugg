"""The PowerShell forwarder is found in a checkout or an installed package, and pinned to its reviewed source."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from plugg import core, powershell_component as ps


class ForwarderTests(unittest.TestCase):
    def test_the_pinned_source_is_the_checked_in_source(self):
        source = Path(__file__).resolve().parents[1] / 'components/powershell-forwarder/main.go'
        self.assertEqual(core.digest(source), ps.FORWARDER_SOURCE_SHA256,
                         'main.go changed: review it, then update FORWARDER_SOURCE_SHA256')

    def test_an_installed_forwarder_is_found_without_a_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary)
            installed = prefix / 'lib/plugg/powershell-forwarder'
            installed.mkdir(parents=True)
            (installed / 'build.json').write_text('{}')
            with patch.object(core, 'REPO', prefix / 'site-packages'), patch.object(sys, 'prefix', str(prefix)):
                self.assertEqual(ps.forwarder_directory(), installed)

    def test_a_missing_forwarder_says_how_to_get_one(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(core, 'REPO', Path(temporary)), patch.object(sys, 'prefix', temporary), \
                    patch('plugg.powershell_component.Path.is_file', return_value=False):
                with self.assertRaisesRegex(core.HostError, 'Arch package includes it'):
                    ps.forwarder_directory()


if __name__ == '__main__':
    unittest.main()
