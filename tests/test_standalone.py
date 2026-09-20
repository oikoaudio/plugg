"""Standalone imports use synthetic PE files and disposable libraries."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from plugg import core, standalone, recipes
from test_core import fake_pe


class StandaloneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = core.Store(self.root/'store', self.root/'published')

    def test_import_copies_the_selection_and_nothing_else_from_the_folder(self):
        source = fake_pe(self.root/'download/Gain.vst3')
        # The folder a plug-in is imported from belongs to the user and may
        # hold anything. Only the selection is copied into the library.
        (source.parent/'readme.txt').write_text('Requirements')
        (source.parent/'tax-return.txt').write_text('private')
        fake_pe(source.with_suffix('.dll'))
        job = self.store.job(self.store.ingest(source))
        saved = standalone.verify(job)
        self.assertEqual(job['kind'], 'vst3')
        self.assertEqual({p.name for p in saved.parent.iterdir()}, {'Gain.vst3'})
        self.assertTrue(source.exists())
        saved.write_bytes(b'changed')
        with self.assertRaisesRegex(core.HostError,'changed'):
            standalone.verify(job)

    def test_a_bundle_of_empty_directories_cannot_evade_the_import_limits(self):
        bundle = self.root/'download/Huge.vst3'
        deep = bundle/'Contents/x86_64-win'
        deep.mkdir(parents=True)
        fake_pe(deep/'Huge.vst3')
        for index in range(standalone.MAX_ENTRIES + 10):
            (bundle/('empty%d' % index)).mkdir()
        with self.assertRaisesRegex(core.HostError,'size or file-count limit'):
            standalone.inventory(bundle)

    def test_a_deeply_nested_import_is_refused_before_it_is_copied(self):
        bundle = self.root/'download/Deep.vst3'
        deep = bundle/'Contents/x86_64-win'
        deep.mkdir(parents=True)
        fake_pe(deep/'Deep.vst3')
        nested = bundle
        for _ in range(standalone.MAX_DEPTH + 2):
            nested = nested/'d'
        nested.mkdir(parents=True)
        with self.assertRaisesRegex(core.HostError,'nested too deeply'):
            standalone.inventory(bundle)

    def test_bundle_keeps_resources_and_rejects_added_file(self):
        source = self.root/'Gain.vst3'
        fake_pe(source/'Contents/x86_64-win/Gain.vst3')
        resources = source/'Contents/Resources'
        resources.mkdir(); (resources/'preset.dat').write_bytes(b'preset')
        job = self.store.job(self.store.ingest(source))
        saved = standalone.verify(job)
        self.assertEqual((saved/'Contents/Resources/preset.dat').read_bytes(),b'preset')
        (saved/'Contents/Resources/extra.dat').write_bytes(b'extra')
        with self.assertRaises(core.HostError):standalone.verify(job)

    def test_bundle_link_cannot_import_external_data(self):
        source = self.root/'Gain.vst3'
        fake_pe(source/'Contents/x86_64-win/Gain.vst3')
        (source/'outside').symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(core.HostError,'without links'):
            self.store.ingest(source)
        self.assertEqual(self.store.jobs(), [])

    def test_linux_binary_is_rejected_before_job_creation(self):
        source = self.root/'Native.vst3';source.write_bytes(b'\x7fELF'+b'\0'*128)
        with self.assertRaises(core.HostError):self.store.ingest(source)
        self.assertEqual(self.store.jobs(), [])

    def test_saved_module_cannot_be_replaced_by_symlink(self):
        source = fake_pe(self.root/'Gain.vst3')
        job = self.store.job(self.store.ingest(source))
        saved = Path(job['installer']);saved.unlink();saved.symlink_to(source)
        with self.assertRaises(core.HostError):standalone.verify(job)

    def test_work_routes_to_import_not_installer_execution(self):
        source = fake_pe(self.root/'Gain.vst3')
        job = self.store.ingest(source)
        with patch.object(standalone,'work') as run, patch.object(recipes,'work') as helper:
            core.work(self.store,job)
            run.assert_called_once_with(self.store,job,False)
            helper.assert_not_called()

    def shared_fixture(self):
        source = fake_pe(self.root/'Owner.vst3')
        owner = self.store.ingest(source)
        job = self.store.job(owner)
        directory = self.store.prefix(owner).parent
        directory.mkdir(parents=True)
        runtime = self.root/'runtime'
        asset = {'url':'https://example.invalid/runtime.exe','sha256':'test'}
        spec = {'modules':{job['hash']:{'vendor':'Example','recipe':'local.example','dependency':'vc'}},'dependencies':{'vc':asset}}
        core.atomic_json(directory/'environment.json',{'recipe':'standalone-vst3','status':'ready'})
        core.atomic_json(directory/'session.json',{'proton':str(runtime/'UMU-Proton-10.0-4/proton'),'prefix':str(directory/'prefix'),'graphics_backend':'dxvk'})
        core.atomic_json(directory/'dependencies.json',[asset])
        self.store.update(owner,'ready','Ready')
        return job,spec,runtime,directory

    def test_reuse_requires_matching_recipe_dependency_and_runtime(self):
        job,spec,runtime,directory = self.shared_fixture()
        with patch.object(standalone.proton_session,'graphics_overrides',return_value=''):
            self.assertEqual(standalone.compatible_environment(self.store,job,spec,runtime),job['env_id'])
            self.assertIsNone(standalone.compatible_environment(self.store,job,spec,self.root/'another-runtime'))
            core.atomic_json(directory/'dependencies.json',[])
            self.assertIsNone(standalone.compatible_environment(self.store,job,spec,runtime))

    def test_unknown_and_other_recipes_are_not_grouped(self):
        job,spec,runtime,_ = self.shared_fixture()
        incoming = dict(job,hash='new')
        with patch.object(standalone.proton_session,'graphics_overrides',return_value=''):
            self.assertIsNone(standalone.compatible_environment(self.store,incoming,spec,runtime))
            spec['modules']['new']={'vendor':'Different vendor','recipe':'local.other','dependency':'vc'}
            self.assertIsNone(standalone.compatible_environment(self.store,incoming,spec,runtime))

    def test_a_recipe_may_not_join_an_environment_by_claiming_its_vendor_name(self):
        job,spec,runtime,_ = self.shared_fixture()
        incoming = dict(job,hash='new')
        # Same vendor string, different recipe: a vendor name is free text that
        # anyone may claim, so it may not decide which environment is entered.
        spec['modules']['new']={'vendor':'Example','recipe':'local.impostor','dependency':'vc'}
        with patch.object(standalone.proton_session,'graphics_overrides',return_value=''):
            self.assertIsNone(standalone.compatible_environment(self.store,incoming,spec,runtime))
        spec['modules']['new']={'vendor':'Example','recipe':'local.example','dependency':'vc'}
        with patch.object(standalone.proton_session,'graphics_overrides',return_value=''):
            self.assertEqual(standalone.compatible_environment(self.store,incoming,spec,runtime),job['env_id'])

    def test_rescan_only_publishes_selected_module_with_shared_environment(self):
        job,spec,runtime,directory = self.shared_fixture()
        source = fake_pe(self.root/'Second.vst3')
        source.write_bytes(source.read_bytes()+b'second')
        incoming = self.store.ingest(source)
        with self.store.db() as db:
            db.execute('UPDATE jobs SET env_id=? WHERE id=?',(job['env_id'],incoming))
        installed = directory/'prefix/drive_c/Program Files/Common Files/VST3'
        installed.mkdir(parents=True)
        import shutil
        shutil.copy2(source,installed/source.name)
        fake_pe(installed/'Owner.vst3')
        metadata={'classes':[{'id':'second','name':'Second'}]}
        with patch.object(standalone.vendors,'applications',return_value=[]), patch.object(core,'probe',return_value=metadata) as probe, patch.object(core,'publish') as publish:
            standalone.check_one(self.store,incoming)
            self.assertEqual(probe.call_count,1)
            self.assertEqual(probe.call_args.args[1].name,'Second.vst3')
            self.assertEqual(publish.call_args.kwargs['environment'],job['env_id'])

    def test_busy_shared_environment_prevents_copy_and_dependency_changes(self):
        job,spec,runtime,directory = self.shared_fixture()
        source = fake_pe(self.root/'Second.vst3')
        incoming = self.store.ingest(source)
        with patch.object(self.store,'bridge'), patch.object(recipes,'provision',return_value=runtime), patch.object(standalone,'compatible_environment',return_value=job['env_id']), patch.object(standalone.vendors,'applications',return_value=[123]), patch.object(standalone,'prepare') as prepare:
            with self.assertRaisesRegex(core.HostError,'Close this vendor'):
                standalone.work(self.store,incoming)
            prepare.assert_not_called()
            self.assertFalse((directory/'prefix/drive_c/Program Files/Common Files/VST3/Second.vst3').exists())

    def test_dependency_superset_can_satisfy_another_product(self):
        job,spec,runtime,directory = self.shared_fixture()
        extra={'url':'https://example.invalid/older.exe','sha256':'older'}
        spec['dependencies']['older']=extra
        spec['modules']['new']={'vendor':'Example','recipe':'local.example','dependency':'older'}
        incoming=dict(job,hash='new')
        with patch.object(standalone.proton_session,'graphics_overrides',return_value=''):
            self.assertIsNone(standalone.compatible_environment(self.store,incoming,spec,runtime))
            core.atomic_json(directory/'dependencies.json',[spec['dependencies']['vc'],extra])
            self.assertEqual(standalone.compatible_environment(self.store,incoming,spec,runtime),job['env_id'])

    def test_rescan_preserves_identity_after_a_managed_move(self):
        job,_,_,directory = self.shared_fixture()
        module = fake_pe(directory/'prefix/drive_c/Program Files/Common Files/VST3/Owner.vst3')
        metadata={'classes':[{'id':'owner','name':'Owner'}]}
        import json
        with self.store.db() as db:
            db.execute('INSERT INTO plugins VALUES(?,?,?,?,?,?,?,?,?)',('preserved-id',job['env_id'],'Owner',str(module),job['hash'],'ready',json.dumps(metadata),str(self.root/'published/old-name.vst3'),'Ready'))
        with patch.object(standalone.vendors,'applications',return_value=[]), patch.object(core,'probe',return_value=metadata), patch.object(core,'publish') as publish:
            standalone.check_one(self.store,job['id'])
            self.assertEqual(publish.call_args.kwargs['identity'],'preserved-id')

    def test_local_recipe_drives_import_without_vendor_dispatch(self):
        import json
        config = self.root / 'config'
        local = config / 'plugg/recipes'
        local.mkdir(parents=True)
        source = fake_pe(self.root / 'New Vendor.vst3')
        fingerprint = core.digest(source)
        (local / 'new-vendor.toml').write_text(
            'schema=1\nid="local.new-vendor"\nrevision=1\nkind="vendor"\n'
            'name="New Vendor"\nvendor="New Vendor"\n'
            'requires=["plugg.graphics-dxvk@1","plugg.vc2013-x64@1"]\n'
            f'[modules."{fingerprint}"]\nname="New Plugin"\n'
            'dependency="plugg.vc2013-x64@1"\n'
        )
        job_id = self.store.ingest(source)
        def configure(store, selected, runtime, helper_enabled=False):
            directory = store.prefix(selected).parent
            core.atomic_json(directory / 'session.json', {'prefix': str(store.prefix(selected)), 'graphics_backend': 'dxvk'})
            return self.root / 'fixture-launcher', None
        with patch.dict('os.environ', {'XDG_CONFIG_HOME': str(config)}),              patch.object(self.store, 'bridge'),              patch.object(recipes, 'provision', return_value=self.root / 'runtime'),              patch.object(recipes, 'configure', side_effect=configure),              patch('plugg.artifacts.fetch', return_value=self.root / 'vc.exe') as fetch,              patch.object(core, 'run_process', return_value=0) as execute,              patch.object(standalone.proton_session, 'foreign_prefix_processes', return_value=[]),              patch.object(standalone.proton_session, 'graphics_overrides', return_value=''),              patch.object(standalone.vendors, 'applications', return_value=[]),              patch.object(core, 'probe', return_value={'classes': [{'id': 'fixture', 'name': 'New Plugin'}]}),              patch.object(core, 'publish') as publish:
            standalone.work(self.store, job_id)
            self.assertEqual(self.store.job(job_id)['status'], 'ready')
            self.assertEqual(fetch.call_args.args[1]['sha256'], 'a4bba7701e355ae29c403431f871a537897c363e215cafe706615e270984f17c')
            installs = [call.args[0] for call in execute.call_args_list
                        if call.args[0][-3:] == ['/install', '/quiet', '/norestart']]
            self.assertEqual(len(installs), 1)
            identity = [call.args[0] for call in execute.call_args_list if 'reg' in call.args[0]]
            self.assertEqual(len(identity), 1, 'the new environment is given this computer\'s identity')
            publish.assert_called_once()
            self.assertTrue((self.store.prefix(job_id) / 'drive_c/Program Files/Common Files/VST3/New Vendor.vst3').is_file())
            lock = json.loads((self.store.root / 'jobs' / job_id / 'recipe-lock.json').read_text())
            self.assertEqual(lock['recipe'], 'local.new-vendor@1')
            self.assertEqual(lock['input_sha256'], fingerprint)
            with self.assertRaisesRegex(core.HostError, 'already finished'):
                standalone.work(self.store, job_id)
            self.assertEqual(fetch.call_count, 1)

    def test_ambiguous_local_recipe_is_ignored_rather_than_silently_chosen(self):
        config = self.root / 'config'
        local = config / 'plugg/recipes'
        local.mkdir(parents=True)
        source = fake_pe(self.root / 'Duplicate.vst3')
        for name in ('one', 'two'):
            (local / (name + '.toml')).write_text(
                f'schema=1\nid="local.{name}"\nrevision=1\nkind="vendor"\n'
                'name="Example"\nvendor="Example"\n'
                'requires=["plugg.graphics-dxvk@1","plugg.vc2013-x64@1"]\n'
                f'[modules."{core.digest(source)}"]\nname="Example"\n'
                'dependency="plugg.vc2013-x64@1"\n'
            )
        self.store.ingest(source)
        with patch.dict('os.environ', {'XDG_CONFIG_HOME': str(config)}):
            # Neither recipe may quietly win a contested module identity. The
            # import is still possible; it is simply treated as unrecognized.
            issues = []
            spec = standalone.catalogue(issues)
            self.assertNotIn(core.digest(source), spec['modules'])
            self.assertTrue(any('Multiple recipes claim' in item['error'] for item in issues))
            # Built-in recipes are unaffected by someone else's bad file.
            self.assertTrue(spec['modules'])

    def test_interrupted_import_is_not_replayed_into_partial_prefix(self):
        source = fake_pe(self.root / 'Interrupted.vst3')
        selected = self.store.ingest(source)
        self.store.update(selected, 'preparing', 'Old worker stopped', pid=123)
        state = self.store.root / 'jobs' / selected / 'import-state.json'
        core.atomic_json(state, {'schema': 1, 'stage': 'preparing-environment', 'status': 'running'})
        with patch.object(recipes, 'provision') as provision, patch.object(standalone, 'prepare') as prepare:
            with self.assertRaisesRegex(core.HostError, 'will not be replayed'):
                standalone.work(self.store, selected)
            provision.assert_not_called()
            prepare.assert_not_called()
        self.assertEqual(self.store.job(selected)['status'], 'needs_attention')
        self.assertEqual(__import__('json').loads(state.read_text())['stage'], 'preparing-environment')

    def test_queued_worker_rereads_completion_after_waiting_for_import_lock(self):
        from contextlib import contextmanager
        source = fake_pe(self.root / 'Queued.vst3')
        selected = self.store.ingest(source)
        original_lock = core.lock
        @contextmanager
        def race(path, blocking=True):
            if path.name == 'standalone-import.lock':
                self.store.update(selected, 'ready', 'Another worker completed')
            with original_lock(path, blocking=blocking):
                yield
        with patch.object(core, 'lock', side_effect=race), patch.object(recipes, 'provision') as provision:
            with self.assertRaisesRegex(core.HostError, 'already finished'):
                standalone.work(self.store, selected)
            provision.assert_not_called()

    def test_reconcile_observes_worker_lock_not_stale_pid(self):
        source = fake_pe(self.root / 'Monitored.vst3')
        selected = self.store.ingest(source)
        self.store.update(selected, 'preparing', 'Working', pid=999999)
        directory = self.store.root / 'jobs' / selected
        core.atomic_json(directory / 'import-state.json', {'status': 'running', 'stage': 'preparing-environment'})
        with core.lock(directory / 'job.lock'):
            self.assertEqual(standalone.reconcile_interrupted(self.store), 0)
            self.assertEqual(self.store.job(selected)['status'], 'preparing')
        self.assertEqual(standalone.reconcile_interrupted(self.store), 1)
        self.assertEqual(self.store.job(selected)['status'], 'needs_attention')
        self.assertIsNone(self.store.job(selected)['pid'])

    def test_rescan_missing_import_has_actionable_error(self):
        selected = self.store.ingest(fake_pe(self.root / 'NotInstalled.vst3'))
        with self.assertRaisesRegex(core.HostError, 'did not reach plug-in installation'):
            standalone.check_one(self.store, selected)

    def test_partial_bundle_copy_cannot_be_published_by_rescan(self):
        source = fake_pe(self.root / 'Partial.vst3')
        selected = self.store.ingest(source)
        core.atomic_json(self.store.root / 'jobs' / selected / 'import-state.json',
                         {'stage': 'installing-files', 'status': 'running'})
        self.store.update(selected, 'needs_attention', 'Interrupted')
        with patch.object(self.store, 'bridge'), patch.object(standalone, 'check_one') as scan:
            with self.assertRaisesRegex(core.HostError, 'file copying did not finish'):
                standalone.work(self.store, selected, rescan=True)
            scan.assert_not_called()
