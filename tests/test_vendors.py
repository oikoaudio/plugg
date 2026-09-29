"""Vendor workflows use disposable files and a fake Helper, never user prefixes."""
import itertools
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from plugg import core, vendors
from test_core import fake_pe


class VendorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = core.Store(self.root/'store', self.root/'published')
        self.job = self.store.ingest(fake_pe(self.root/'installer.exe'))
        self.prefix = self.store.prefix(self.job)
        self.envdir = self.prefix.parent
        self.envdir.mkdir(parents=True)
        self.helper = self.root/'helper'
        core.atomic_json(self.envdir/'environment.json', {'recipe':'klevgrand','helper_launcher':str(self.helper)})
        self.bridge = self.root/'bridge';self.bridge.mkdir()
        for name in ('libyabridge-vst3.so','libyabridge-chainloader-vst3.so','yabridge-host.exe','yabridge-host.exe.so'):
            (self.bridge/name).write_bytes(b'fixture')
        self.addCleanup(patch.stopall)
        patch.object(self.store,'bridge',return_value=self.bridge).start()
        self.metadata = {'classes':[{'id':'test-class','name':'Gain','vendor':'Example','version':'1'}]}

    def installed(self):
        return fake_pe(self.prefix/'drive_c/Program Files/Common Files/VST3/Gain.vst3')

    def test_full_helper_does_not_launch_if_idle_session_cannot_stop(self):
        core.atomic_json(self.envdir/'environment.json',{'recipe':'klevgrand','helper_launcher':str(self.helper),'helper_owns_runtime':True})
        with patch('plugg.vendors.applications',return_value=[]), patch('plugg.proton_session.stop_idle_session',side_effect=RuntimeError('still in use')) as stop, patch('plugg.vendors.subprocess.Popen') as launch:
            with self.assertRaisesRegex(RuntimeError,'still in use'):
                vendors.work(self.store,self.job)
            stop.assert_called_once_with(self.envdir/'session.json')
            launch.assert_not_called()

    def test_idle_session_stop_refuses_an_unknown_runtime(self):
        from plugg import proton_session
        config=self.root/'session.json';config.write_text('{}')
        ipc=self.root/'ipc';ipc.mkdir()
        with patch('plugg.proton_session.configuration',return_value={'prefix':str(self.prefix),'proton':'/unused'}), patch('plugg.proton_session.ipc_directory',return_value=ipc), patch('plugg.vendors.applications',return_value=[]), patch('plugg.proton_session.ping',return_value=False), patch('plugg.proton_session.foreign_prefix_processes',return_value=[123]), patch('plugg.proton_session.os.kill') as kill:
            with self.assertRaisesRegex(RuntimeError,'Another runtime'):
                proton_session.stop_idle_session(config)
            kill.assert_not_called()

    def test_initial_placement_rule_is_installed_before_launch_and_disabled(self):
        with patch.dict(os.environ,{'HYPRLAND_INSTANCE_SIGNATURE':'test'}), patch('plugg.vendors.shutil.which',return_value='/usr/bin/hyprctl'), patch('plugg.vendors.subprocess.run',return_value=subprocess.CompletedProcess([],0,'ok\n')) as run:
            with self.assertRaisesRegex(RuntimeError,'child failed'):
                with vendors.helper_placement():
                    self.assertEqual(run.call_count,1)
                    self.assertIn('float=true,persistent_size=false',run.call_args.args[0][2])
                    raise RuntimeError('child failed')
            self.assertEqual(run.call_count,2)
            self.assertIn('set_enabled(false)',run.call_args.args[0][2])

    def test_initial_placement_failure_prevents_launch(self):
        with patch.dict(os.environ,{'HYPRLAND_INSTANCE_SIGNATURE':'test'}), patch('plugg.vendors.shutil.which',return_value='/usr/bin/hyprctl'), patch('plugg.vendors.subprocess.run',return_value=subprocess.CompletedProcess([],0,'error: unsupported')):
            with self.assertRaises(core.HostError):
                with vendors.helper_placement():
                    self.fail('Helper must not launch after a rejected rule')

    def test_float_only_managed_helper_once_without_resizing(self):
        windows = [
            {'address':'0x123','pid':12,'class':'steam_proton','title':'Klevgrand Helper','floating':False},
            {'address':'0x456','pid':45,'class':'steam_proton','title':'Klevgrand Helper','floating':False},
            {'address':'0x789','pid':12,'class':'steam_proton','title':'Skaka','floating':False},
        ]
        handled = set()
        replies = [subprocess.CompletedProcess([],0,json.dumps(windows)), subprocess.CompletedProcess([],0,'ok\n'), subprocess.CompletedProcess([],0,json.dumps(windows))]
        with patch.dict(os.environ,{'HYPRLAND_INSTANCE_SIGNATURE':'test'}), patch('plugg.vendors.shutil.which',return_value='/usr/bin/hyprctl'), patch('plugg.vendors.foreign_prefix_processes',return_value=[12]), patch('plugg.vendors.subprocess.run',side_effect=replies) as run:
            self.assertIsNone(vendors.float_helper(self.prefix,handled))
            self.assertIsNone(vendors.float_helper(self.prefix,handled))
        self.assertEqual(handled,{('0x123',12)})
        commands=[c.args[0] for c in run.call_args_list]
        self.assertEqual(commands[1],['hyprctl','dispatch','hl.dsp.window.float({action="enable",window="address:0x123"})'])
        self.assertEqual(len(commands),3)

    def test_float_failure_is_nonfatal_and_not_marked_handled(self):
        handled=set()
        with patch.dict(os.environ,{'HYPRLAND_INSTANCE_SIGNATURE':'test'}), patch('plugg.vendors.shutil.which',return_value='/usr/bin/hyprctl'), patch('plugg.vendors.subprocess.run',side_effect=subprocess.TimeoutExpired('hyprctl',2)):
            self.assertIn('Float the Helper',vendors.float_helper(self.prefix,handled))
        self.assertEqual(handled,set())

    def test_other_desktops_do_not_run_hyprland_commands(self):
        with patch.dict(os.environ,{},clear=True), patch('plugg.vendors.subprocess.run') as run:
            self.assertIsNone(vendors.float_helper(self.prefix,set()))
            run.assert_not_called()

    def test_only_installed_vst3_not_cache_or_other_formats(self):
        good=self.installed()
        fake_pe(self.prefix/'drive_c/Program Files/Klevgrand/Helper/downloads/1/Gain.vst3')
        fake_pe(good.with_suffix('.dll'))
        fake_pe(good.parent/'Gain.aaxplugin/Contents/x64/Gain.aaxplugin')
        outside=fake_pe(self.root/'outside.vst3')
        (good.parent/'escape.vst3').symlink_to(outside)
        self.assertEqual([x['path'] for x in vendors.installed(self.prefix)],[good])

    def test_existing_publication_from_another_job_is_preserved(self):
        self.installed();item=vendors.installed(self.prefix)[0]
        core.publish(self.store,item,'original-job',self.metadata)
        before=self.store.plugins()
        with patch('plugg.core.probe') as probe:
            result=vendors.refresh_library(self.store,self.job)
            probe.assert_not_called()
        self.assertEqual(result,{'added':0,'unchanged':1,'updated':[],'removed':[],'failures':[],'waiting':[]})
        self.assertEqual(self.store.plugins(),before)

    def test_a_vendor_app_update_is_reported_as_updated_not_republished(self):
        # The DAW's adapter links to the module file, so it already loads the
        # update; Plugg reports it and leaves the publication as it is.
        path=self.installed();item=vendors.installed(self.prefix)[0]
        core.publish(self.store,item,self.job,self.metadata)
        before=self.store.plugins()
        with path.open('ab') as f:f.write(b'changed version')
        result=vendors.refresh_library(self.store,self.job)
        self.assertEqual(result['updated'],[item['name']])
        self.assertEqual(result['failures'],[])
        self.assertEqual(self.store.plugins(),before)

    def test_new_product_is_checked_and_published(self):
        self.installed()
        with patch('plugg.core.probe',return_value=self.metadata) as probe:
            result=vendors.refresh_library(self.store,self.job)
        self.assertEqual(result['added'],1)
        self.assertEqual(probe.call_count,1)
        self.assertTrue(Path(self.store.plugins()[0]['publication']).is_symlink())

    def test_module_changing_during_probe_is_not_published(self):
        path=self.installed()
        def change(*args):
            with path.open('ab') as f:f.write(b'update still running')
            return self.metadata
        with patch('plugg.core.probe',side_effect=change):
            result=vendors.refresh_library(self.store,self.job)
        self.assertEqual(len(result['failures']),1)
        self.assertEqual(self.store.plugins(),[])

    def test_active_vendor_blocks_helper_launch(self):
        with patch('plugg.vendors.applications',return_value=[123]), patch('plugg.vendors.subprocess.Popen') as launch:
            with self.assertRaisesRegex(core.HostError,'Close this vendor'):
                vendors.start(self.store,self.job)
            launch.assert_not_called()

    def test_helper_exit_automatically_publishes_new_installation(self):
        source=fake_pe(self.root/'source.vst3')
        dest=self.prefix/'drive_c/Program Files/Common Files/VST3/Gain.vst3'
        self.helper.write_text('#!/usr/bin/python3\nfrom pathlib import Path\np=Path('+repr(str(dest))+')\np.parent.mkdir(parents=True,exist_ok=True)\np.write_bytes(Path('+repr(str(source))+').read_bytes())\n')
        self.helper.chmod(0o700)
        clock=itertools.count()
        with patch('plugg.vendors.helper_placement'), patch('plugg.vendors.applications',return_value=[]), patch('plugg.vendors.time.sleep'), patch('plugg.vendors.time.monotonic',side_effect=lambda:next(clock)), patch('plugg.core.probe',return_value=self.metadata):
            result=vendors.work(self.store,self.job)
        self.assertEqual(result['added'],1)
        state=json.loads((self.envdir/'helper-state.json').read_text())
        self.assertEqual(state['status'],'ready')
        self.assertTrue(Path(self.store.plugins()[0]['publication']).exists())

    def test_helper_failure_is_visible_and_does_not_scan(self):
        self.helper.write_text('#!/bin/sh\nexit 2\n');self.helper.chmod(0o700)
        with patch('plugg.vendors.helper_placement'), patch('plugg.vendors.applications',return_value=[]), patch('plugg.vendors.refresh_library') as refresh:
            with self.assertRaisesRegex(core.HostError,'exited unexpectedly'):
                vendors.work(self.store,self.job)
            refresh.assert_not_called()
        self.assertEqual(json.loads((self.envdir/'helper-state.json').read_text())['status'],'needs_attention')

    def test_ua_close_uses_shared_discovery_and_preserves_repeat_publication(self):
        from plugg import ua_connect
        self.installed()
        core.atomic_json(self.envdir/'environment.json', {
            'recipe':'pace-service-experiment', 'helper_launcher':str(self.helper),
            'helper_job':self.job})
        core.atomic_json(self.envdir/'ua-connect-launch.json', {
            'revision':1, 'electron_no_sandbox':True})
        for expected in (1, 0):
            clock=itertools.count()
            with patch('plugg.ua_connect.require_idle_desktop'), \
                 patch('plugg.ua_connect.prepare_runtime') as cleanup, \
                 patch('plugg.ua_connect.wait_for_helper',return_value=0), \
                 patch('plugg.ua_connect.library_context',return_value=(self.store,self.job)), \
                 patch('plugg.ua_connect.subprocess.Popen'), \
                 patch('plugg.vendors.helper_placement'), \
                 patch('plugg.ua_connect.foreign_prefix_processes',return_value=[]), \
                 patch('plugg.vendors.time.sleep'), \
                 patch('plugg.vendors.time.monotonic',side_effect=lambda:next(clock)), \
                 patch('plugg.core.probe',return_value=self.metadata) as probe:
                self.assertEqual(ua_connect.run(self.envdir),0)
                self.assertEqual(probe.call_count,expected)
                self.assertEqual(cleanup.call_count,3)
            state=json.loads((self.envdir/'helper-state.json').read_text())
            self.assertEqual(state['status'],'ready')
            self.assertTrue(state['message'].startswith(str(expected)+' added'))
        self.assertEqual(len(self.store.plugins()),1)

    def test_shared_discovery_cleans_runtime_after_probe_failure(self):
        self.installed()
        clock=itertools.count()
        with patch('plugg.vendors.time.sleep'), \
             patch('plugg.vendors.time.monotonic',side_effect=lambda:next(clock)), \
             patch('plugg.core.probe',side_effect=core.HostError('Cannot load plugin')), \
             patch('plugg.ua_connect.prepare_runtime') as cleanup:
            result=vendors.finish_installation(self.store,self.job,busy=lambda _:False,
                                              after_scan=lambda:cleanup(self.envdir))
        self.assertEqual(result['added'],0)
        self.assertEqual(len(result['failures']),1)
        cleanup.assert_called_once_with(self.envdir)
        self.assertEqual(json.loads((self.envdir/'helper-state.json').read_text())['status'],'needs_attention')



    def test_card_uses_operation_lock_instead_of_saved_pid(self):
        core.atomic_json(self.envdir / 'helper-state.json', {'status': 'running', 'pid': os.getpid()})
        card, = vendors.cards(self.store)
        self.assertFalse(card['busy'])
        self.assertTrue(card['needs_attention'])
        self.assertFalse((self.envdir / 'helper.lock').exists())
        with core.lock(self.envdir / 'helper.lock'):
            # A live operation need not have published its PID yet.
            core.atomic_json(self.envdir / 'helper-state.json', {'status': 'opening'})
            card, = vendors.cards(self.store)
            self.assertTrue(card['busy'])
            self.assertFalse(card['needs_attention'])
        card, = vendors.cards(self.store)
        self.assertFalse(card['busy'])
        self.assertTrue(card['needs_attention'])

    def test_damaged_helper_status_keeps_card_and_does_not_rewrite_record(self):
        path = self.envdir / 'helper-state.json'
        for contents in ('{', '[]', '{"message":42}', 'x' * (64 * 1024 + 1)):
            with self.subTest(contents=contents[:20]):
                path.write_text(contents)
                card, = vendors.cards(self.store)
                self.assertTrue(card['needs_attention'])
                self.assertFalse(card['busy'])
                self.assertIn('could not be read', card['message'])
                self.assertEqual(path.read_text(), contents)
        with core.lock(self.envdir / 'helper.lock'):
            card, = vendors.cards(self.store)
            self.assertTrue(card['busy'])
            self.assertTrue(card['needs_attention'])
        core.atomic_json(path, {'status': 'ready', 'message': 'Ready'})
        card, = vendors.cards(self.store)
        self.assertFalse(card['needs_attention'])


class ManagerAttributionTests(unittest.TestCase):
    def test_shared_ilok_products_are_not_all_ua_connect_products(self):
        plugins = [
            {'name': name, 'metadata': json.dumps({'classes': [{'name': name, 'vendor': vendor}]})}
            for name, vendor in [('SpaceBlender', 'Soundtoys'), ('soothe', 'oeksound'),
                                 ('UADx LA-2A', 'Universal Audio (UADx)'), ('Unknown', '')]]
        self.assertEqual(vendors.manager_products('pace-service-experiment', plugins), ['UADx LA-2A'])
        self.assertEqual(len(vendors.manager_products('klevgrand', plugins)), 4)

    def test_missing_vendor_is_not_inferred_from_plugin_name(self):
        plugins = [{'name': 'UAD sounding name', 'metadata': '{}'}]
        self.assertEqual(vendors.manager_products('pace-service-experiment', plugins), [])

if __name__ == '__main__':
    unittest.main()
