"""Behavioral tests use an isolated library and never the user's prefixes."""
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from plugg import core


def fake_pe(path, machine=0x8664):
    head = bytearray(96)
    head[:2] = b"MZ"
    struct.pack_into("<I",head,60,64)
    head[64:68] = b"PE\0\0"
    struct.pack_into("<H",head,68,machine)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(head)
    return path


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = core.Store(self.root/'data',self.root/'published')

    def tearDown(self):
        self.tmp.cleanup()

    def test_intake_copies_validated_installer_and_preserves_original(self):
        source=fake_pe(self.root/'A weird $name.exe')
        job=self.store.ingest(source)
        saved=self.store.job(job)
        source.write_text('changed')
        self.assertEqual(core.pe_machine(Path(saved['installer'])),0x8664)
        self.assertNotEqual(core.digest(source),saved['hash'])
        self.assertEqual(saved['status'],'queued')

    def test_split_installer_keeps_names_and_all_adjacent_bin_parts(self):
        source=fake_pe(self.root/'extracted/My Product Setup.exe')
        (source.parent/'My Product Setup-1.bin').write_bytes(b'part one')
        (source.parent/'My Product Setup-2.BIN').write_bytes(b'part two')
        (source.parent/'license.txt').write_text('activation file')
        job=self.store.job(self.store.ingest(source))
        saved=Path(job['installer'])
        self.assertEqual(saved.name,source.name)
        self.assertEqual(sorted(p.name for p in saved.parent.iterdir()),
                         ['My Product Setup-1.bin','My Product Setup-2.BIN','My Product Setup.exe'])
        (source.parent/'My Product Setup-1.bin').write_bytes(b'original changed')
        self.assertEqual((saved.parent/'My Product Setup-1.bin').read_bytes(),b'part one')
        core.verify_installer(job)

    def test_changed_or_missing_bin_is_rejected_before_launch(self):
        source=fake_pe(self.root/'setup.exe')
        (self.root/'setup.bin').write_bytes(b'payload')
        job=self.store.job(self.store.ingest(source))
        companion=Path(job['installer']).parent/'setup.bin'
        companion.write_bytes(b'changed')
        with self.assertRaisesRegex(core.HostError,'missing or changed'):core.verify_installer(job)
        companion.unlink()
        with self.assertRaisesRegex(core.HostError,'missing or changed'):core.verify_installer(job)

    def test_symlink_payload_is_rejected_without_leaving_partial_job(self):
        source=fake_pe(self.root/'extracted/setup.exe')
        outside=self.root/'outside';outside.write_bytes(b'data')
        (source.parent/'setup.bin').symlink_to(outside)
        with self.assertRaisesRegex(core.HostError,'regular files'):self.store.ingest(source)
        self.assertEqual(self.store.jobs(),[])
        self.assertEqual(list((self.store.root/'jobs').iterdir()),[])

    def test_installer_process_reads_companion_from_its_working_directory(self):
        payload=self.root/'payload with spaces';payload.mkdir()
        (payload/'setup.bin').write_bytes(b'expected payload')
        rc=core.run_process(['python3','-c',
            'from pathlib import Path; assert Path("setup.bin").read_bytes()==b"expected payload"'],
            os.environ.copy(),self.root/'log',cwd=payload)
        self.assertEqual(rc,0)

    def test_non_installer_and_damaged_pe_rejected(self):
        source=self.root/'fake.exe';source.write_text('hello')
        with self.assertRaises(core.HostError):self.store.ingest(source)
        source=fake_pe(source);b=bytearray(source.read_bytes());struct.pack_into('<I',b,60,0xffffffff);source.write_bytes(b)
        with self.assertRaises(core.HostError):self.store.ingest(source)
        self.assertEqual(self.store.jobs(),[])

    def test_msi_requires_compound_file_header(self):
        source=self.root/'wrong.msi';source.write_bytes(b'not an MSI')
        with self.assertRaises(core.HostError):core.installer_type(source)

    def test_discovery_does_not_follow_prefix_escape(self):
        prefix=self.root/'prefix';drive=prefix/'drive_c'
        good=fake_pe(drive/'Program Files/Common Files/VST3/Good.vst3')
        outside=self.root/'outside';fake_pe(outside/'Bad.vst3')
        (drive/'escape').symlink_to(outside,target_is_directory=True)
        (good.parent/'Symlink.vst3').symlink_to(outside/'Bad.vst3')
        self.assertEqual([x['path'] for x in core.discover(prefix)],[good])

    def test_archive_path_and_link_escapes_rejected(self):
        for name,link in [('../escape',''),('link','../../escape')]:
            archive=self.root/'bad.tar'
            with tarfile.open(archive,'w') as tar:
                info=tarfile.TarInfo(name)
                if link:info.type=tarfile.SYMTYPE;info.linkname=link;tar.addfile(info)
                else:info.size=1;tar.addfile(info,io.BytesIO(b'x'))
            with self.assertRaises(tarfile.FilterError):core.safe_extract(archive,self.root/'extract')

    def test_subprocess_arguments_are_not_shell_expanded(self):
        script=self.root/'argv.py';script.write_text('import sys;print(sys.argv[1])')
        log=self.root/'log'
        payload='$(touch '+str(self.root/'pwned')+')'
        rc=core.run_process(['python3',script,payload],os.environ.copy(),log)
        self.assertEqual(rc,0);self.assertEqual(log.read_text().strip(),payload)
        self.assertFalse((self.root/'pwned').exists())

    def test_process_timeout_terminates_child(self):
        with self.assertRaises(core.HostError):
            core.run_process(['python3','-c','import time;time.sleep(60)'],os.environ.copy(),self.root/'log',timeout=0.1)

    def test_cancel_persists_and_terminal_job_is_not_restarted(self):
        job=self.store.ingest(fake_pe(self.root/'x.exe'))
        self.store.cancel(job)
        with self.assertRaises(core.Cancelled):self.store.cancelled(job)
        self.store.update(job,'cancelled','Cancelled')
        with self.assertRaises(core.HostError):core.work(self.store,job)

    def test_publication_location_persists_across_worker_start(self):
        reopened=core.Store(self.store.root)
        self.assertEqual(reopened.publication,self.root/'published')
        with self.assertRaises(core.HostError):core.Store(self.store.root,self.root/'elsewhere')

    def test_runtime_environment_does_not_inherit_global_wine_prefix(self):
        with patch.dict(os.environ,{'WINEPREFIX':'/not-ours','WINELOADER':'/other','WINESERVER':'/wrong','WAYLAND_DISPLAY':'wayland-1'}):
            env=core.runtime_env(self.root/'prefix',self.root/'runtime/bin/wine')
        self.assertEqual(env['WINEPREFIX'],str(self.root/'prefix'))
        self.assertEqual(env['WINESERVER'],str(self.root/'runtime/bin/wineserver'))
        self.assertNotIn('WAYLAND_DISPLAY',env)

    def test_launcher_quotes_paths(self):
        prefix=self.root/'a space $x'/'prefix';prefix.mkdir(parents=True)
        wine=self.root/'runtime weird'/'wine';wine.parent.mkdir();wine.write_text('#!/bin/sh\nprintf "%s" "$WINEPREFIX"\n');wine.chmod(0o700)
        core.create_launcher(prefix,wine)
        out=subprocess.check_output([prefix.parent/'launch-wine'],text=True)
        self.assertEqual(out,str(prefix))

    def publication_fixture(self, name="Long " * 40):
        job=self.store.ingest(fake_pe(self.root/'installer.exe'))
        module=fake_pe(self.store.prefix(job)/'drive_c/Gain.vst3')
        bridge=self.root/'bridge';bridge.mkdir(exist_ok=True)
        for filename in ('libyabridge-chainloader-vst3.so','libyabridge-vst3.so','yabridge-host.exe','yabridge-host.exe.so'):
            (bridge/filename).write_bytes(b'fixture')
        self.bridge_patch=patch.object(self.store,'bridge',return_value=bridge)
        self.bridge_patch.start();self.addCleanup(self.bridge_patch.stop)
        return job,{'path':module,'name':name,'hash':core.digest(module)}, {'classes':[{'id':'0123456789abcdef','name':name}]}

    def test_publication_is_complete_and_internal_names_are_short(self):
        job,item,metadata=self.publication_fixture()
        core.publish(self.store,item,job,metadata)
        target=Path(self.store.plugins()[0]['publication'])
        self.assertTrue(target.is_symlink())
        self.assertEqual(target.resolve().parent,self.store.root/'bundles')
        self.assertLessEqual(len(target.stem),core.name_budget())
        native=target/'Contents/x86_64-linux'/(target.stem+'.so')
        self.assertTrue(native.is_file())
        self.assertEqual((target/'Contents/x86_64-win'/target.name).resolve(),item['path'])
        self.assertEqual(json.loads((target/'plugg.json').read_text())['metadata'],metadata)

    def test_failed_publication_never_exposes_partial_bundle(self):
        job,item,metadata=self.publication_fixture()
        with patch('plugg.core.make_bundle',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):core.publish(self.store,item,job,metadata)
        self.assertEqual(list(self.store.publication.iterdir()),[])
        self.assertEqual(self.store.plugins(),[])

    def test_publication_retry_repairs_missing_registry_record(self):
        job,item,metadata=self.publication_fixture()
        core.publish(self.store,item,job,metadata)
        target=Path(self.store.plugins()[0]['publication']);before=target.lstat().st_ino
        with self.store.db() as db:db.execute('DELETE FROM plugins')
        core.publish(self.store,item,job,metadata)
        self.assertEqual(len(self.store.plugins()),1)
        self.assertEqual(target.lstat().st_ino,before)

    def test_metadata_enrichment_preserves_published_bundle(self):
        job,item,metadata=self.publication_fixture("Gain")
        core.publish(self.store,item,job,metadata)
        target=Path(self.store.plugins()[0]['publication'])
        original_manifest=(target/'plugg.json').read_bytes()
        original_inode=target.lstat().st_ino
        enriched={'classes':[dict(metadata['classes'][0],vendor='Example',version='1.2.3')]}
        core.publish(self.store,item,job,enriched)
        self.assertEqual(json.loads(self.store.plugins()[0]['metadata']),enriched)
        self.assertEqual((target/'plugg.json').read_bytes(),original_manifest)
        self.assertEqual(target.lstat().st_ino,original_inode)
        changed={'classes':[dict(enriched['classes'][0],id='different-class')]}
        with self.assertRaisesRegex(core.HostError,'changed'):
            core.publish(self.store,item,job,changed)

    def test_changed_module_cannot_silently_replace_published_version(self):
        job,item,metadata=self.publication_fixture()
        core.publish(self.store,item,job,metadata)
        item['hash']='different-version'
        with self.assertRaisesRegex(core.HostError,'changed'):core.publish(self.store,item,job,metadata)
        self.assertNotEqual(self.store.plugins()[0]['hash'],item['hash'])

    def test_duplicate_original_plugin_ids_are_rejected(self):
        job,item,metadata=self.publication_fixture()
        core.publish(self.store,item,job,metadata)
        with self.assertRaisesRegex(core.HostError,'already'):core.publish(self.store,item,'another-env',metadata)
        self.assertEqual(len(self.store.plugins()),1)

    def test_publication_does_not_overwrite_foreign_path(self):
        job,item,metadata=self.publication_fixture()
        core.publish(self.store,item,job,metadata)
        target=Path(self.store.plugins()[0]['publication']);target.unlink();target.mkdir()
        (target/'keep').write_text('unmanaged')
        with self.assertRaisesRegex(core.HostError,'unmanaged'):core.publish(self.store,item,job,metadata)
        self.assertEqual((target/'keep').read_text(),'unmanaged')


if __name__=='__main__':unittest.main()


class ArchiveTests(unittest.TestCase):
    def test_archive_and_restore_preserve_installer_and_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=core.Store(root/'store',root/'published')
            job=store.ingest(fake_pe(root/'installer.exe'))
            prefix=store.prefix(job);prefix.mkdir(parents=True)
            marker=prefix/'keep.dat';marker.write_text('keep')
            store.update(job,'ready','Installed')
            store.archive(job)
            self.assertTrue(store.jobs()[0]['archived'])
            self.assertTrue(Path(store.job(job)['installer']).exists())
            self.assertEqual(marker.read_text(),'keep')
            self.assertEqual(store.job(job)['status'],'ready')
            store.archive(job,False)
            self.assertFalse(store.jobs()[0]['archived'])

    def test_active_attempt_cannot_be_archived(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=core.Store(root/'store',root/'published')
            job=store.ingest(fake_pe(root/'installer.exe'))
            with self.assertRaisesRegex(core.HostError,'finish'):store.archive(job)
            self.assertFalse(store.jobs()[0]['archived'])


class BackgroundProcessTests(unittest.TestCase):
    """Proton's container refuses a working directory under /usr, which is where
    the installed package lives. Every Proton step started from the app failed
    until background work stopped inheriting the package directory."""

    def test_workers_start_in_the_library_not_the_package(self):
        import subprocess
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            store = core.Store(Path(temporary) / 'library', Path(temporary) / 'published')
            (store.root / 'jobs' / 'job').mkdir(parents=True)
            with patch.object(store, 'job'), patch('subprocess.Popen') as popen:
                popen.return_value.pid = 1
                store.start('job')
            self.assertEqual(popen.call_args.kwargs['cwd'], store.root)
            self.assertNotIn('PYTHONPATH', popen.call_args.kwargs.get('env') or {})

    def test_the_plugg_command_runs_from_any_directory(self):
        import subprocess
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(core.plugg_command('--help'), cwd=temporary, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('usage: plugg', result.stdout)

    def test_nothing_starts_in_the_package_directory(self):
        package = Path(core.__file__).resolve().parent
        for path in package.glob('*.py'):
            self.assertNotIn('cwd=core.REPO', path.read_text(), path.name)
            self.assertNotIn('cwd=REPO', path.read_text(), path.name)


class SharedInstallerIntakeTests(unittest.TestCase):
    """Softube Central and UA Connect belong in the iLok environment. Dropped on
    the app, they used to start a plain new environment without PACE, which
    stalled at the installer and could never have licensed anything."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = core.Store(root / 'library', root / 'published')
        self.installer = root / 'Softube Central Setup 3.0.5.exe'
        fake_pe(self.installer)
        self.known = {core.digest(self.installer): ('Softube Central', 'plugg.softube@2')}

    def test_it_is_pointed_at_the_ilok_environment(self):
        environment = self.store.root / 'environments' / 'ilok'
        environment.mkdir(parents=True)
        (self.store.root / 'licensing-environments.json').write_text(
            json.dumps({'schema': 1, 'groups': {'ilok': {'environment': 'ilok'}}}))
        with patch.object(core, 'shared_environment_installers', return_value=self.known):
            with self.assertRaises(core.SharedEnvironmentInstaller) as caught:
                self.store.ingest(self.installer)
        self.assertEqual(caught.exception.recipe, 'plugg.softube@2')
        self.assertEqual(caught.exception.environment, environment)
        self.assertEqual(self.store.jobs(), [])

    def test_without_an_ilok_environment_it_says_what_to_do_first(self):
        with patch.object(core, 'shared_environment_installers', return_value=self.known):
            with self.assertRaisesRegex(core.HostError, 'plugg ilok create'):
                self.store.ingest(self.installer)
        self.assertEqual(self.store.jobs(), [])

    def test_the_reviewed_installers_are_the_ones_recognised(self):
        from plugg import softube_setup, ua_setup
        known = core.shared_environment_installers()
        self.assertEqual(known[softube_setup.INSTALLER_SHA256][1], 'plugg.softube@2')
        for sha256, _ in ua_setup.VERSIONS.values():
            self.assertEqual(known[sha256][1], 'plugg.universal-audio@1')


class OneRuntimeTests(unittest.TestCase):
    """Unknown installers went to a separate plain Wine build long after every
    other path had moved to the selected runtime. Nothing checked that all ways
    of creating an environment agreed."""

    def test_unknown_installers_use_the_selected_runtime(self):
        import inspect
        source = inspect.getsource(core._work)
        self.assertNotIn('provision_wine(', source)
        self.assertIn('recipes.configure(', source)

    def test_every_environment_is_configured_through_the_runtime_selection(self):
        import inspect
        from plugg import recipes
        self.assertIn('proton_for_new_environment', inspect.getsource(recipes.configure))

    def test_the_runtime_is_named_in_words(self):
        self.assertEqual(core.runtime_label({'proton': '/r/proton-10.0-4-plugg-1-440a6d29c2e6/proton'}),
                         'UMU-Proton-10.0-4 (plugg-1)')
        self.assertEqual(core.runtime_label({'proton': '/r/proton-b246/UMU-Proton-10.0-4/proton'}),
                         'UMU-Proton-10.0-4')


class SoftubeOpenTests(unittest.TestCase):
    def test_a_taken_environment_says_so_instead_of_doing_nothing(self):
        from plugg import softube, vendors
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with patch.object(softube, 'configured', return_value=True), \
                    patch.object(softube.ua_connect, 'require_idle_desktop'), \
                    patch.object(softube, 'foreign_prefix_processes', return_value=[]), \
                    patch.object(vendors, 'visible_window', return_value=None), \
                    patch.object(vendors, 'program_names', return_value=['Softube Saturation Knob Installer.exe']), \
                    patch.object(core, 'worker_running', return_value=True), \
                    patch.object(vendors, 'open_native_access') as opened:
                with self.assertRaisesRegex(core.HostError, 'Force close'):
                    softube.start(directory)
            opened.assert_not_called()


class InstalledHelperTests(unittest.TestCase):
    """Kilohearts Installer installs itself and is how products are managed
    later, but an installer without a recipe never got a helper card."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = core.Store(root / 'library', root / 'published')
        self.env = self.store.root / 'environments' / 'env'
        drive = self.env / 'prefix' / 'drive_c'
        (drive / 'ProgramData/Kilohearts').mkdir(parents=True)
        (drive / 'ProgramData/Kilohearts/Kilohearts Installer.exe').write_bytes(b'MZ')
        (drive / 'ProgramData/Kilohearts/uninstall.exe').write_bytes(b'MZ')
        (drive / 'Program Files/Internet Explorer').mkdir(parents=True)
        (drive / 'Program Files/Internet Explorer/iexplore.exe').write_bytes(b'MZ')
        (self.env / 'launch-full-proton').write_text('#!/bin/sh\n')
        (self.env / 'session.json').write_text('{}')
        (self.env / 'environment.json').write_text(json.dumps({'id': 'env', 'recipe': 'installer'}))
        with self.store.db() as db:
            db.execute("INSERT INTO jobs VALUES('env','Kilohearts Installer [BC_token]','/x.exe','exe',?, "
                       "'ready','ok',1,1,0,NULL,'env')", ('0' * 64,))

    def test_only_vendor_apps_are_offered(self):
        from plugg import vendors
        self.assertEqual(vendors.helper_candidates(self.env), ['ProgramData/Kilohearts/Kilohearts Installer.exe'])

    def test_the_installers_own_app_becomes_the_helper(self):
        from plugg import vendors
        result = core.adopt_installed_helper(self.store, self.store.job('env'))
        self.assertEqual(result['helper']['executable'], 'ProgramData/Kilohearts/Kilohearts Installer.exe')
        cfg = json.loads((self.env / 'environment.json').read_text())
        self.assertEqual(cfg['recipe'], 'managed-helper')
        self.assertEqual(cfg['display_name'], 'Kilohearts Installer')
        self.assertTrue((self.env / 'launch-helper').is_file())
        self.assertEqual([card['name'] for card in vendors.cards(self.store)], ['Kilohearts Installer'])

    def test_an_old_wine_environment_is_not_given_a_helper(self):
        from plugg import vendors
        (self.env / 'launch-full-proton').unlink()
        self.assertIsNone(core.adopt_installed_helper(self.store, self.store.job('env')))
        with self.assertRaisesRegex(core.HostError, 'Install the product again'):
            vendors.adopt_helper(self.store, 'env', 'ProgramData/Kilohearts/Kilohearts Installer.exe', 'Kilohearts')


class ManagerInstallerTests(unittest.TestCase):
    """Kilohearts Installer is its own manager: closing it after installing
    products reported exit code 2, the install counted as failed, and neither
    the scan nor the helper card followed until Check again."""

    def test_a_non_zero_exit_that_installed_plug_ins_is_not_a_failure(self):
        import inspect
        source = inspect.getsource(core._work)
        self.assertIn('if rc != 0 and not discover(prefix):', source)

    def test_check_again_also_gives_the_helper_its_card(self):
        import inspect
        source = inspect.getsource(core._work)
        rescan = source[source.index('if rescan:\n                scan_and_publish'):]
        self.assertLess(rescan.index('adopt_installed_helper'), rescan.index('return'))
