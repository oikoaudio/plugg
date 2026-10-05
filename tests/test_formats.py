"""Publishing VST2 and CLAP beside VST3, and choosing which of them a library publishes.

The Windows files here are built in the test: a minimal PE32+ image whose one
section holds an export table, which is all that tells a VST2 DLL from any
other DLL. The bridge is a directory of placeholder files; nothing is loaded.
"""
import hashlib
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugg import bridge_bundle, core, environments, formats, pe_version, vendors

BRIDGE_FILES = ('libyabridge-vst3.so', 'libyabridge-chainloader-vst3.so', 'libyabridge-vst2.so',
                'libyabridge-chainloader-vst2.so', 'libyabridge-clap.so', 'libyabridge-chainloader-clap.so',
                'yabridge-host.exe', 'yabridge-host.exe.so')


def pe_exporting(names, machine=0x8664):
    """A PE32+ file whose only section is .edata at RVA 0x1000, file offset 0x400."""
    rva, raw = 0x1000, 0x400
    directory = bytearray(40)
    strings = b''.join(name.encode() + b'\0' for name in names)
    pointers_at = 40
    strings_at = pointers_at + 4 * len(names)
    pointers, offset = b'', strings_at
    for name in names:
        pointers += struct.pack('<I', rva + offset)
        offset += len(name) + 1
    struct.pack_into('<I', directory, 24, len(names))
    struct.pack_into('<I', directory, 32, rva + pointers_at)
    section = bytes(directory) + pointers + strings
    head = bytearray(raw)
    head[:2] = b'MZ'
    struct.pack_into('<I', head, 60, 0x80)
    pe = 0x80
    head[pe:pe + 4] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', head, pe + 4, machine, 1, 0, 0, 0, 240, 0x2022)
    optional = pe + 24
    struct.pack_into('<H', head, optional, 0x20b)
    struct.pack_into('<I', head, optional + 108, 16)
    struct.pack_into('<II', head, optional + 112, rva, len(section))
    table = optional + 240
    head[table:table + 8] = b'.edata\0\0'
    struct.pack_into('<IIII', head, table + 8, len(section), rva, len(section), raw)
    return bytes(head) + section


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class ExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_export_names_are_read_without_loading(self):
        dll = write(self.root / 'Synth.dll', pe_exporting(['VSTPluginMain', 'main']))
        self.assertEqual(pe_version.exports(dll), {'VSTPluginMain', 'main'})

    def test_anything_else_has_no_exports(self):
        self.assertEqual(pe_version.exports(write(self.root / 'text.dll', b'not a program' * 10)), set())
        self.assertEqual(pe_version.exports(self.root / 'missing.dll'), set())

    def test_a_dll_is_a_vst2_plug_in_only_when_it_exports_the_entry_point(self):
        self.assertEqual(formats.module_format(write(self.root / 'Synth.dll', pe_exporting(['VSTPluginMain']))), 'vst2')
        self.assertEqual(formats.module_format(write(self.root / 'Old.dll', pe_exporting(['main']))), 'vst2')
        self.assertIsNone(formats.module_format(write(self.root / 'helper.dll', pe_exporting(['DllGetClassObject']))))
        self.assertEqual(formats.module_format(write(self.root / 'Gain.clap', pe_exporting(['clap_entry']))), 'clap')
        self.assertIsNone(formats.module_format(write(self.root / 'Other.clap', pe_exporting(['DllMain']))))
        self.assertEqual(formats.module_format(self.root / 'Anything.vst3'), 'vst3')


class ChoiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = core.Store(self.root / 'library', self.root / 'home/.vst3/plugg')

    def test_vst3_is_the_default_and_cannot_be_switched_off(self):
        self.assertEqual(formats.enabled(self.store.root), ('vst3',))
        result = formats.choose(self.store, {'clap'})
        self.assertEqual(result['formats'], ['vst3', 'clap'])
        self.assertEqual(formats.enabled(self.store.root), ('vst3', 'clap'))

    def test_unknown_formats_are_refused(self):
        with self.assertRaises(formats.FormatError):
            formats.choose(self.store, {'au'})

    def test_folders_sit_beside_the_vst3_folder_and_are_recorded(self):
        formats.choose(self.store, {'vst2', 'clap'})
        self.assertEqual(formats.folder(self.store, 'vst2'), self.root / 'home/.vst/plugg')
        self.assertEqual(formats.folder(self.store, 'clap'), self.root / 'home/.clap/plugg')
        settings = json.loads((self.store.root / 'settings.json').read_text())
        self.assertEqual(settings[formats.FOLDERS_SETTING]['vst2'], str(self.root / 'home/.vst/plugg'))

    def test_a_library_published_elsewhere_never_uses_the_real_folders(self):
        self.assertEqual(formats.default_folder(Path('/tmp/dev/published'), 'clap'), Path('/tmp/dev/published-clap'))

    def test_a_bridge_without_the_format_cannot_be_chosen(self):
        bridge = self.root / 'old-bridge'
        write(bridge / 'build.json', b'{}')
        for name in BRIDGE_FILES[:2] + BRIDGE_FILES[6:]:
            write(bridge / name, b'fixture')
        with patch.object(self.store, 'bridge_directory', return_value=bridge), \
                self.assertRaisesRegex(formats.FormatError, 'cannot publish VST2'):
            formats.apply(self.store, {'vst2'})
        self.assertEqual(formats.enabled(self.store.root), ('vst3',))

    def test_the_summary_names_every_chosen_format(self):
        formats.choose(self.store, {'vst2', 'clap'})
        self.assertIn('VST3, VST2 and CLAP', formats.summary(self.store))
        self.assertIn('add VST2 and CLAP', formats.summary(self.store))


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = core.Store(self.root / 'library', self.root / 'home/.vst3/plugg')
        self.bridge = self.root / 'bridge'
        for name in BRIDGE_FILES:
            write(self.bridge / name, ('fixture ' + name).encode())
        started = patch.object(self.store, 'bridge', return_value=self.bridge)
        started.start()
        self.addCleanup(started.stop)
        self.drive = self.root / 'env/prefix/drive_c'
        formats.choose(self.store, {'vst2', 'clap'})

    def module(self, relative, data=None):
        path = write(self.drive / relative, data or pe_exporting(['VSTPluginMain']))
        return {'path': path, 'name': path.stem, 'hash': core.digest(path)}

    def metadata(self, kind, ident='50674732', name='Gain'):
        data = {'classes': [{'id': ident, 'name': name, 'vendor': 'Plugg Tests'}]}
        if kind != 'vst3':
            data['format'] = kind
        return data

    def test_a_vst2_is_a_directory_link_holding_the_loader_and_the_dll(self):
        item = self.module('Program Files/VSTPlugins/Gain.dll')
        core.publish(self.store, item, 'job', self.metadata('vst2'))
        target = Path(self.store.plugins()[0]['publication'])
        self.assertEqual(target, self.root / 'home/.vst/plugg/Gain')
        self.assertTrue(target.is_symlink())
        self.assertEqual(target.resolve(), self.store.root / 'bundles/vst2/Gain')
        self.assertEqual((target / 'Gain.so').read_bytes(), b'fixture libyabridge-chainloader-vst2.so')
        self.assertEqual((target / 'Gain.dll').resolve(), item['path'])
        self.assertTrue((target / '.plugg-managed').is_file())
        self.assertEqual(os.readlink(target / 'libyabridge-vst2.so'), str(self.bridge / 'libyabridge-vst2.so'))

    def test_a_32_bit_vst2_also_links_the_32_bit_host(self):
        for name in formats.HOST_32:
            write(self.bridge / name, ('fixture ' + name).encode())
        item = self.module('Program Files (x86)/VSTPlugins/Old.dll', pe_exporting(['VSTPluginMain'], 0x14c))
        core.publish(self.store, item, 'job', self.metadata('vst2', name='Old'))
        target = Path(self.store.plugins()[0]['publication'])
        for name in formats.HOST_32:
            self.assertEqual(os.readlink(target / name), str(self.bridge / name))
        self.assertEqual(formats.links_in(target, 'vst2'), formats.bridge_links('vst2', True))

    def test_a_64_bit_vst2_does_not_link_the_32_bit_host(self):
        for name in formats.HOST_32:
            write(self.bridge / name, ('fixture ' + name).encode())
        core.publish(self.store, self.module('Program Files/VSTPlugins/Gain.dll'), 'job', self.metadata('vst2'))
        target = Path(self.store.plugins()[0]['publication'])
        self.assertFalse((target / formats.HOST_32[0]).exists())

    def test_a_32_bit_vst2_needs_a_bridge_with_the_32_bit_host(self):
        item = self.module('Program Files (x86)/VSTPlugins/Old.dll', pe_exporting(['VSTPluginMain'], 0x14c))
        with self.assertRaisesRegex(formats.FormatError, 'no 32-bit host'):
            core.publish(self.store, item, 'job', self.metadata('vst2', name='Old'))

    def test_a_clap_keeps_the_windows_file_out_of_the_daws_scan(self):
        item = self.module('Program Files/Common Files/CLAP/Gain.clap', pe_exporting(['clap_entry']))
        core.publish(self.store, item, 'job', self.metadata('clap', 'org.example.gain'))
        target = Path(self.store.plugins()[0]['publication'])
        self.assertEqual(target, self.root / 'home/.clap/plugg/Gain')
        self.assertEqual((target / 'Gain.clap').read_bytes(), b'fixture libyabridge-chainloader-clap.so')
        self.assertEqual((target / 'Gain.clap-win').resolve(), item['path'])
        self.assertEqual([p.name for p in target.iterdir() if p.name.endswith('.clap')], ['Gain.clap'])

    def test_one_plug_in_may_be_published_once_per_format_under_one_name(self):
        vst3 = self.module('Program Files/Common Files/VST3/Gain.vst3', b'MZ' + b'\0' * 200)
        vst2 = self.module('Program Files/VSTPlugins/Gain.dll')
        clap = self.module('Program Files/Common Files/CLAP/Gain.clap', b'MZ' + b'\1' * 200)
        core.publish(self.store, vst3, 'job', self.metadata('vst3', '50674732'))
        core.publish(self.store, vst2, 'job', self.metadata('vst2', '50674732'))
        core.publish(self.store, clap, 'job', self.metadata('clap', '50674732'))
        names = sorted(Path(p['publication']).name for p in self.store.plugins())
        self.assertEqual(names, ['Gain', 'Gain', 'Gain.vst3'])

    def test_a_duplicate_id_within_one_format_is_still_refused(self):
        core.publish(self.store, self.module('Program Files/VSTPlugins/Gain.dll'), 'job', self.metadata('vst2'))
        copy = self.module('Program Files/Steinberg/VSTPlugins/Gain.dll')
        with self.assertRaisesRegex(core.HostError, 'already'):
            core.publish(self.store, copy, 'other', self.metadata('vst2'))

    def test_switching_a_format_off_removes_nothing(self):
        core.publish(self.store, self.module('Program Files/VSTPlugins/Gain.dll'), 'job', self.metadata('vst2'))
        with patch.object(self.store, 'bridge_directory', return_value=self.bridge):
            formats.apply(self.store, {'vst3'})
        plugin, = self.store.plugins()
        self.assertEqual(plugin['status'], 'ready')
        self.assertTrue(Path(plugin['publication']).is_symlink())

    def test_a_plug_in_taken_out_stays_out_until_it_is_put_back(self):
        item = self.module('Program Files/VSTPlugins/Gain.dll')
        identity = core.publish(self.store, item, 'job', self.metadata('vst2'))
        core.keep_out(self.store, identity)
        self.assertFalse(Path(self.store.plugins()[0]['publication']).exists())
        self.assertIsNone(core.publish(self.store, item, 'job', self.metadata('vst2')))
        self.assertEqual(self.store.plugins()[0]['status'], 'removed')
        core.put_back(self.store, identity)
        plugin, = self.store.plugins()
        self.assertEqual(plugin['status'], 'ready')
        self.assertTrue(Path(plugin['publication']).is_symlink())
        self.assertEqual(core.kept_out(self.store), set())

    def test_a_changed_module_is_not_put_back_blind(self):
        item = self.module('Program Files/VSTPlugins/Gain.dll')
        identity = core.publish(self.store, item, 'job', self.metadata('vst2'))
        core.keep_out(self.store, identity)
        item['path'].write_bytes(pe_exporting(['VSTPluginMain', 'main']))
        with self.assertRaisesRegex(core.HostError, 'changed'):
            core.put_back(self.store, identity)

    def test_checking_again_does_not_load_a_plug_in_taken_out(self):
        item = self.module('Program Files/VSTPlugins/Gain.dll')
        prefix = self.drive.parent
        core.keep_out(self.store, core.publish(self.store, item, 'job', self.metadata('vst2')))
        with patch.object(self.store, 'prefix', return_value=prefix), patch.object(self.store, 'update'), \
                patch.object(self.store, 'cancelled'), patch('plugg.core.probe') as probe:
            (self.store.root / 'jobs/job').mkdir(parents=True)
            core.scan_and_publish(self.store, 'job')
        probe.assert_not_called()

    def test_moving_to_the_current_bridge_covers_every_format(self):
        core.publish(self.store, self.module('Program Files/VSTPlugins/Gain.dll'), 'job', self.metadata('vst2'))
        plan = core.adopt_current_bridge(self.store)
        self.assertEqual((plan['planned'], plan['problems']), ([], []))
        newer = self.root / 'newer'
        for name in BRIDGE_FILES:
            write(newer / name, ('newer ' + name).encode())
        with patch.object(self.store, 'bridge', return_value=newer):
            core.adopt_current_bridge(self.store, apply=True)
        target = Path(self.store.plugins()[0]['publication'])
        self.assertEqual((target / 'Gain.so').read_bytes(), b'newer libyabridge-chainloader-vst2.so')
        self.assertEqual(os.readlink(target / 'libyabridge-vst2.so'), str(newer / 'libyabridge-vst2.so'))

    def test_a_leftover_vst2_bundle_is_named_with_its_folder_and_can_be_removed(self):
        item = self.module('Program Files/VSTPlugins/Gain.dll')
        core.publish(self.store, item, 'job', self.metadata('vst2'))
        core.forget_plugin(self.store, self.store.plugins()[0]['id'])
        item['path'].unlink()
        dead = environments.dead_bundles(self.store)
        self.assertEqual([(d['name'], d['format']) for d in dead], [('vst2/Gain', 'vst2')])
        environments.remove_dead_bundle(self.store, 'vst2/Gain')
        self.assertFalse((self.store.root / 'bundles/vst2/Gain').exists())
        with self.assertRaises(core.HostError):
            environments.remove_dead_bundle(self.store, 'jobs/Gain')


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.prefix = Path(temporary.name) / 'prefix'
        self.drive = self.prefix / 'drive_c'
        write(self.drive / 'Program Files/Common Files/VST3/Gain.vst3', pe_exporting(['GetPluginFactory']))
        write(self.drive / 'Program Files/VSTPlugins/Gain.dll', pe_exporting(['VSTPluginMain']))
        write(self.drive / 'Program Files (x86)/VSTPlugins/Gain.dll', pe_exporting(['VSTPluginMain'], 0x14c))
        write(self.drive / 'Program Files/Vendor/helper.dll', pe_exporting(['DllMain']))
        write(self.drive / 'Program Files/Common Files/CLAP/Gain.clap', pe_exporting(['clap_entry']))

    def found(self, items):
        return sorted((item['format'], str(item['path'].relative_to(self.drive))) for item in items)

    def test_only_the_chosen_formats_are_discovered(self):
        self.assertEqual(self.found(core.discover(self.prefix)),
                         [('vst3', 'Program Files/Common Files/VST3/Gain.vst3')])

    def test_32_bit_vst2_is_found_and_32_bit_clap_left_out(self):
        write(self.drive / 'Program Files (x86)/Common Files/CLAP/Gain.clap', pe_exporting(['clap_entry'], 0x14c))
        self.assertEqual(self.found(core.discover(self.prefix, formats.FORMATS)), [
            ('clap', 'Program Files/Common Files/CLAP/Gain.clap'),
            ('vst2', 'Program Files (x86)/VSTPlugins/Gain.dll'),
            ('vst2', 'Program Files/VSTPlugins/Gain.dll'),
            ('vst3', 'Program Files/Common Files/VST3/Gain.vst3')])

    def store_with_bridge(self, bitbridge):
        store = core.Store(self.prefix.parent / 'library', self.prefix.parent / 'published')
        bridge = self.prefix.parent / ('bridge-%s' % bitbridge)
        for name in formats.HOST_32 if bitbridge else ():
            write(bridge / name, b'host')
        bridge.mkdir(exist_ok=True)
        started = patch.object(store, 'bridge', return_value=bridge)
        started.start()
        self.addCleanup(started.stop)
        return store

    def test_32_bit_vst2_is_left_out_without_a_32_bit_host(self):
        items = core.hostable(self.store_with_bridge(False), core.discover(self.prefix, ('vst2',)))
        self.assertEqual(self.found(items), [('vst2', 'Program Files/VSTPlugins/Gain.dll')])

    def test_with_a_32_bit_host_the_64_bit_build_comes_first(self):
        items = core.hostable(self.store_with_bridge(True), core.discover(self.prefix, ('vst2',)))
        self.assertEqual([item['machine'] for item in items], [0x8664, 0x14c])

    def test_a_32_bit_build_of_a_published_plug_in_is_left_out_quietly(self):
        store = self.store_with_bridge(True)
        metadata = {'format': 'vst2', 'classes': [{'id': '50674732', 'name': 'Gain'}]}
        with store.db() as db:
            db.execute('INSERT INTO plugins(id,env_id,name,module,hash,status,metadata,publication,message)'
                       " VALUES('p','env','Gain','Gain.dll','h','ready',?,'','ok')", (json.dumps(metadata),))
        old = {'machine': 0x14c}
        self.assertTrue(core.duplicate_32_bit(store, old, metadata))
        other = {'format': 'vst2', 'classes': [{'id': '4f6c6421', 'name': 'Old'}]}
        self.assertFalse(core.duplicate_32_bit(store, old, other))
        self.assertFalse(core.duplicate_32_bit(store, {'machine': 0x8664}, metadata))

    def test_vendor_apps_are_looked_for_in_their_install_folders_only(self):
        write(self.drive / 'ProgramData/Helper/cache/Gain.dll', pe_exporting(['VSTPluginMain']))
        self.assertEqual(self.found(vendors.installed(self.prefix, ('vst2', 'clap'))), [
            ('clap', 'Program Files/Common Files/CLAP/Gain.clap'),
            ('vst2', 'Program Files/VSTPlugins/Gain.dll')])


    def test_finding_nothing_names_no_format(self):
        store = core.Store(self.prefix.parent / 'library', self.prefix.parent / 'published')
        empty = self.prefix.parent / 'empty'
        (empty / 'drive_c').mkdir(parents=True)
        with patch.object(store, 'prefix', return_value=empty):
            self.assertEqual(core.nothing_found(store, 'job'), 'No plug-ins found yet. Finish installing or '
                                                                'activating the products, then check again.')

    def test_plug_ins_in_a_format_left_off_are_pointed_out(self):
        store = core.Store(self.prefix.parent / 'library', self.prefix.parent / 'published')
        (self.drive / 'Program Files/Common Files/VST3/Gain.vst3').unlink()
        with patch.object(store, 'prefix', return_value=self.prefix):
            message = core.nothing_found(store, 'job')
        self.assertIn('Only VST2 and CLAP plug-ins were found', message)
        self.assertIn('Turn them on under Settings', message)

class BridgeReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def build(self, names):
        directory = self.root / ('build-%d' % len(names))
        files = {}
        for name in names:
            content = ('fixture ' + name).encode()
            write(directory / name, content)
            files[name] = hashlib.sha256(content).hexdigest()
        (directory / 'build.json').write_text(json.dumps({'files': files}))
        return directory

    def test_builds_with_and_without_vst2_and_clap_are_both_accepted(self):
        old = self.build(bridge_bundle.ARTIFACTS)
        new = self.build(bridge_bundle.ARTIFACTS + bridge_bundle.FORMAT_ARTIFACTS)
        bridge_bundle.inspect(old)
        bridge_bundle.inspect(new)
        self.assertEqual(formats.supported_by(old), ('vst3',))
        self.assertEqual(formats.supported_by(new), formats.FORMATS)

    def test_a_vst3_only_build_keeps_the_release_name_it_always_had(self):
        old = self.build(bridge_bundle.ARTIFACTS)
        lines = [name + ' ' + core.digest(old / name) for name in bridge_bundle.RELEASE_FILES]
        expected = hashlib.sha256('\n'.join(lines).encode()).hexdigest()[:16]
        self.assertEqual(bridge_bundle.release_name(old)[0], expected)

    def test_a_build_with_the_32_bit_host_is_accepted_and_named_apart(self):
        names = bridge_bundle.ARTIFACTS + bridge_bundle.FORMAT_ARTIFACTS
        without = self.build(names)
        with_host = self.build(names + bridge_bundle.BITBRIDGE_ARTIFACTS)
        bridge_bundle.inspect(with_host)
        self.assertTrue(bridge_bundle.has_bitbridge(with_host))
        self.assertFalse(bridge_bundle.has_bitbridge(without))
        self.assertNotEqual(bridge_bundle.release_name(with_host)[0], bridge_bundle.release_name(without)[0])
        release = bridge_bundle.install_release(with_host, self.root / 'releases')
        self.assertTrue(bridge_bundle.has_bitbridge(release))

    def test_half_a_32_bit_host_is_refused(self):
        partial = self.build(bridge_bundle.ARTIFACTS + bridge_bundle.FORMAT_ARTIFACTS
                             + bridge_bundle.BITBRIDGE_ARTIFACTS[:1])
        with self.assertRaisesRegex(ValueError, 'incomplete 32-bit'):
            bridge_bundle.release_name(partial)

    def test_a_release_with_part_of_the_new_files_is_refused(self):
        partial = self.build(bridge_bundle.ARTIFACTS + bridge_bundle.FORMAT_ARTIFACTS[:1])
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            bridge_bundle.release_name(partial)


if __name__ == '__main__':
    unittest.main()


class DirectImportTests(unittest.TestCase):
    """A plug-in dropped on the window is qualified from its headers before anything is copied."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = core.Store(self.root / 'library', self.root / 'home/.vst3/plugg')

    def test_a_vst2_dll_is_taken_as_a_vst2_import(self):
        job = self.store.job(self.store.ingest(write(self.root / 'Gain.dll', pe_exporting(['VSTPluginMain']))))
        self.assertEqual(job['kind'], 'vst2')
        self.assertTrue(formats.is_import(job))

    def test_a_clap_file_is_taken_as_a_clap_import(self):
        job = self.store.job(self.store.ingest(write(self.root / 'Gain.clap', pe_exporting(['clap_entry']))))
        self.assertEqual(job['kind'], 'clap')

    def test_a_dll_that_is_not_a_vst2_is_refused_and_nothing_is_kept(self):
        with self.assertRaisesRegex(core.HostError, 'not a VST2 plug-in'):
            self.store.ingest(write(self.root / 'helper.dll', pe_exporting(['DllGetClassObject'])))
        with self.assertRaisesRegex(core.HostError, 'not a Windows CLAP plug-in'):
            self.store.ingest(write(self.root / 'Fake.clap', pe_exporting(['DllMain'])))
        self.assertEqual(self.store.jobs(), [])
        self.assertEqual(list((self.store.root / 'jobs').iterdir()) if (self.store.root / 'jobs').exists() else [], [])

    def bridge(self, bitbridge):
        bridge = self.root / ('bridge-%s' % bitbridge)
        bridge.mkdir(exist_ok=True)
        for name in formats.HOST_32 if bitbridge else ():
            write(bridge / name, b'host')
        started = patch.object(self.store, 'bridge_source', return_value=bridge)
        started.start()
        self.addCleanup(started.stop)

    def test_a_32_bit_vst2_is_taken_when_the_bridge_has_a_32_bit_host(self):
        self.bridge(True)
        job = self.store.job(self.store.ingest(write(self.root / 'Old.dll', pe_exporting(['main'], 0x14c))))
        self.assertEqual(job['kind'], 'vst2')

    def test_a_32_bit_vst2_is_refused_when_the_bridge_has_no_32_bit_host(self):
        self.bridge(False)
        with self.assertRaisesRegex(core.HostError, 'no 32-bit host'):
            self.store.ingest(write(self.root / 'Old.dll', pe_exporting(['main'], 0x14c)))
        self.assertEqual(self.store.jobs(), [])

    def test_32_bit_clap_and_other_machines_are_still_refused(self):
        with self.assertRaisesRegex(core.HostError, 'Only 64-bit Windows CLAP'):
            self.store.ingest(write(self.root / 'Old.clap', pe_exporting(['clap_entry'], 0x14c)))
        with self.assertRaisesRegex(core.HostError, 'Only 64-bit Windows VST2 plug-ins are supported, and 32-bit'):
            self.store.ingest(write(self.root / 'Arm.dll', pe_exporting(['main'], 0xaa64)))
