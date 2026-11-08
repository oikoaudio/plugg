"""Which installers belong in the iLok environment, asked before and caught after."""
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugg import core, ilok_setup, pe_version
from test_core import fake_pe
from test_pe_version import pe_with, version_resource


def pe_with_sections(*names):
    """A PE32+ header whose section table holds these names and nothing else."""
    head = bytearray(0x400)
    head[:2] = b'MZ'
    struct.pack_into('<I', head, 60, 0x80)
    head[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HH', head, 0x84, 0x8664, len(names))
    struct.pack_into('<H', head, 0x80 + 20, 240)
    struct.pack_into('<H', head, 0x80 + 24, 0x20b)
    table = 0x80 + 24 + 240
    for index, name in enumerate(names):
        head[table + index * 40:table + index * 40 + 8] = name.encode().ljust(8, b'\0')
    return bytes(head)


PACE = pe_with_sections('.text', '.rdata', '.mfrt', '.oldrel', '.text001', '.proxy', '.reloc')
PLAIN = pe_with_sections('.text', '.rdata', '.data', '.pdata', '.rsrc', '.reloc')


class Library(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = core.Store(self.root / 'library', self.root / 'published')

    def ilok_environment(self, vendors=('Neural DSP', 'Soundtoys')):
        (self.store.root / 'environments' / 'shared').mkdir(parents=True)
        core.atomic_json(self.store.root / ilok_setup.GROUPS, {'schema': 1, 'groups': {
            'ilok': {'environment': 'shared', 'vendors': list(vendors)}}})

    def installer(self, company, name='Setup.exe'):
        path = self.root / 'downloads' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pe_with(version_resource({'CompanyName': company})))
        return path


class PaceWrapperTests(Library):
    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_the_pace_wrapper_is_recognised_by_its_sections(self):
        self.assertTrue(pe_version.pace_wrapped(self.write('Licensed.vst3', PACE)))
        self.assertFalse(pe_version.pace_wrapped(self.write('Free.vst3', PLAIN)))

    def test_a_bundle_is_read_through_its_windows_module(self):
        self.write('Licensed.vst3/Contents/x86_64-win/Licensed.vst3', PACE)
        self.assertTrue(pe_version.pace_wrapped(self.root / 'Licensed.vst3'))

    def test_files_that_are_not_programs_are_not_wrapped(self):
        self.assertFalse(pe_version.pace_wrapped(self.write('empty.vst3', b'')))
        self.assertFalse(pe_version.pace_wrapped(self.write('cut.vst3', PACE[:0x80 + 24 + 240 + 50])))
        self.assertFalse(pe_version.pace_wrapped(self.root / 'missing.vst3'))


class SuggestedVendorTests(Library):
    def test_a_vendor_the_ilok_environment_holds_is_suggested(self):
        self.ilok_environment()
        self.assertEqual(ilok_setup.suggested_vendor(self.store, self.installer('Neural DSP Technologies')),
                         'Neural DSP')
        self.assertEqual(ilok_setup.suggested_vendor(self.store, self.installer('SoundToys, Inc.')), 'Soundtoys')

    def test_other_vendors_and_partial_names_are_not(self):
        self.ilok_environment()
        self.assertIsNone(ilok_setup.suggested_vendor(self.store, self.installer('Arturia')))
        self.assertIsNone(ilok_setup.suggested_vendor(self.store, self.installer('Neural')))
        self.assertIsNone(ilok_setup.suggested_vendor(self.store, fake_pe(self.root / 'NoVersion.exe')))

    def test_nothing_is_suggested_without_an_ilok_environment(self):
        self.assertIsNone(ilok_setup.suggested_vendor(self.store, self.installer('Neural DSP')))


class IntakeTests(Library):
    def test_an_installer_from_an_ilok_vendor_is_held_for_a_decision(self):
        self.ilok_environment()
        with self.assertRaises(core.IlokVendorInstaller) as raised:
            self.store.ingest(self.installer('Neural DSP', 'Archetype Plini X v1.0.2.exe'))
        self.assertEqual(raised.exception.vendor, 'Neural DSP')
        self.assertIn('plugg ilok install', str(raised.exception))
        self.assertIn('--own-environment', str(raised.exception))
        self.assertEqual(self.store.jobs(), [])

    def test_its_own_environment_when_asked_for(self):
        self.ilok_environment()
        job = self.store.ingest(self.installer('Neural DSP'), own_environment=True)
        self.assertEqual(self.store.job(job)['status'], 'queued')

    def test_other_installers_are_not_held(self):
        self.ilok_environment()
        job = self.store.ingest(self.installer('Arturia'))
        self.assertEqual(self.store.job(job)['status'], 'queued')


class ScanTests(Library):
    def plugin(self, job, name, content):
        path = self.store.prefix(job) / 'drive_c/Program Files/Common Files/VST3' / (name + '.vst3')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_a_pace_wrapped_plugin_is_not_loaded_and_points_at_the_ilok_environment(self):
        self.ilok_environment()
        job = self.store.ingest(self.installer('Somebody New'))
        self.plugin(job, 'Licensed', PACE)
        with patch('plugg.core.probe') as probe:
            result = core.scan_and_publish(self.store, job)
        probe.assert_not_called()
        self.assertEqual(result['ilok'], ['Licensed'])
        saved = self.store.job(job)
        self.assertEqual(saved['status'], 'needs_attention')
        self.assertIn('Licensed uses iLok', saved['message'])
        self.assertIn('Install it there instead', saved['message'])
        recorded = json.loads((self.store.root / 'jobs' / job / 'scan-result.json').read_text())
        self.assertEqual(recorded['ilok'], ['Licensed'])

    def test_without_an_ilok_environment_it_says_how_to_make_one(self):
        job = self.store.ingest(self.installer('Somebody New'))
        self.plugin(job, 'Licensed', PACE)
        with patch('plugg.core.probe'):
            core.scan_and_publish(self.store, job)
        self.assertIn('plugg ilok create', self.store.job(job)['message'])

    def test_in_an_environment_with_pace_it_is_loaded_as_usual(self):
        job = self.store.ingest(self.installer('Somebody New'))
        self.plugin(job, 'Licensed', PACE)
        config = self.store.root / 'environments' / self.store.job(job)['env_id'] / 'environment.json'
        config.parent.mkdir(parents=True, exist_ok=True)
        core.atomic_json(config, {'licensing_group': 'ilok'})
        with patch('plugg.core.probe', side_effect=core.HostError('needs activation')) as probe:
            result = core.scan_and_publish(self.store, job)
        self.assertEqual(probe.call_count, 1)
        self.assertNotIn('ilok', result)

    def test_plain_plugins_beside_it_are_still_published(self):
        self.ilok_environment()
        job = self.store.ingest(self.installer('Somebody New'))
        self.plugin(job, 'Licensed', PACE)
        self.plugin(job, 'Free', PLAIN)
        with patch('plugg.core.probe', return_value={'classes': [{'name': 'Free'}]}) as probe, \
                patch('plugg.core.publish') as publish:
            result = core.scan_and_publish(self.store, job)
        self.assertEqual([call.args[1].stem for call in probe.call_args_list], ['Free'])
        self.assertEqual(publish.call_count, 1)
        self.assertEqual(result['published'], 1)
        self.assertIn('1 other plug-in module published', self.store.job(job)['message'])


if __name__ == '__main__':
    unittest.main()
