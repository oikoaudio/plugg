import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugg import core, helper_recipes, recipes, vendors, recipe_engine
from test_core import fake_pe


class HelperRecipeTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = core.Store(self.root / 'store', self.root / 'published')
        self.directory = self.root / 'config/plugg/recipes'
        self.directory.mkdir(parents=True)
        environment = patch.dict('os.environ', {'XDG_CONFIG_HOME': str(self.root / 'config')})
        environment.start()
        self.addCleanup(environment.stop)
        self.installer = fake_pe(self.root / 'Example Setup.exe')
        self.recipe = self.directory / 'helper.toml'
        self.recipe.write_text('''schema=1
id="local.example-helper"
revision=1
kind="vendor"
name="Example helper"
vendor="Example"
requires=["plugg.graphics-dxvk@1"]
[helper]
name="Example Manager"
executable="Program Files/Example/Manager.exe"
archive_tools=false
arguments=["/quiet"]
installer_sha256="''' + core.digest(self.installer) + '"\n')

    def test_shipped_klevgrand_composes_graphics_archive_tools_and_licensing(self):
        records = recipe_engine.catalogue([Path(recipe_engine.__file__).parent / 'recipes/community'])
        fingerprint = recipes.recipe()['installer_sha256'][0]
        selected = helper_recipes.catalogue(records)[fingerprint]
        self.assertEqual(selected['reference'], 'plugg.klevgrand@1')
        self.assertTrue(selected['helper']['archive_tools'])
        self.assertEqual(selected['archive_assets'], recipes.recipe()['packages'])
        self.assertEqual(selected['helper']['arguments'], recipes.recipe()['installer_args'])
        self.assertEqual(selected['licensing']['recovery'], 'deactivate-first')
        self.assertTrue(helper_recipes.replaces_builtin(selected, fingerprint))
        altered = dict(selected, vendor='Someone else')
        self.assertFalse(helper_recipes.replaces_builtin(altered, fingerprint))
        with self.assertRaisesRegex(ValueError, 'Archive tools'):
            recipe_engine.plan(records, selected['reference'], self.root / 'does-not-exist')

    def test_intake_pins_recipe_and_worker_publishes_helper_card(self):
        job = self.store.ingest(self.installer)
        snapshot = json.loads((self.store.root / 'jobs' / job / 'helper-recipe.json').read_text())
        self.assertEqual(snapshot['reference'], 'local.example-helper@1')
        # Editing the source cannot change the queued installation.
        self.recipe.write_text('broken after intake')
        runtime = self.root / 'runtime'
        (runtime / 'UMU-Proton-10.0-4').mkdir(parents=True)
        (runtime / 'UMU-Proton-10.0-4/proton').write_text('fixture')
        def execute(command, *args, **kwargs):
            if 'reg' in command:
                # Giving the new environment this computer's machine identity.
                self.assertEqual(command[-1], '/f')
                return 0
            target = self.store.prefix(job) / 'drive_c/Program Files/Example/Manager.exe'
            target.parent.mkdir(parents=True)
            target.write_bytes(b'fixture helper')
            self.assertEqual(command[-1], '/quiet')
            self.assertEqual(kwargs['cwd'], Path(self.store.job(job)['installer']).parent)
            return 0
        with patch.object(recipes, 'provision', return_value=runtime), \
                patch.object(core, 'run_process', side_effect=execute), \
                patch('plugg.proton_session.graphics_overrides'), \
                patch('plugg.proton_session.foreign_prefix_processes', return_value=[]), \
                patch.object(vendors, 'finish_installation', return_value={'added': 0, 'unchanged': 0, 'failures': []}) as finish:
            core.work(self.store, job)
            finish.assert_called_once_with(self.store, job)
        self.assertEqual(self.store.job(job)['status'], 'ready')
        card, = vendors.cards(self.store)
        self.assertEqual(card['name'], 'Example Manager')
        self.assertEqual(card['vendor'], 'Example')
        self.assertTrue(card['can_refresh'])
        with patch.object(recipes, 'provision') as provision, self.assertRaisesRegex(core.HostError, 'already finished'):
            helper_recipes.work(self.store, job)
        provision.assert_not_called()

    def test_ambiguous_installer_claims_disable_both_recipes_without_blocking_intake(self):
        second = self.directory / 'other.toml'
        second.write_text(self.recipe.read_text().replace('local.example-helper', 'local.other-helper'))
        # Two recipes claiming one installer is a contest neither may win, but
        # it must not stop the user adding the installer by the generic path.
        issues = []
        self.assertIsNone(helper_recipes.match(core.digest(self.installer), issues))
        self.assertTrue(any('Ambiguous helper' in item['error'] for item in issues))
        job = self.store.ingest(self.installer)
        self.assertFalse((self.store.root / 'jobs' / job / 'helper-recipe.json').exists())
        second.unlink()

    def test_a_recipe_needing_unsupported_provisioning_is_ignored_not_obeyed(self):
        self.recipe.write_text(self.recipe.read_text().replace('"plugg.graphics-dxvk@1"',
            '"plugg.graphics-dxvk@1", "plugg.ole32-foreign-window-guard@1"'))
        issues = []
        self.assertIsNone(helper_recipes.match(core.digest(self.installer), issues))
        self.assertTrue(any('does not yet provision' in item['error'] for item in issues))
        # Strict loading still reports it, so a contributor sees the problem.
        records = recipe_engine.catalogue(recipe_engine.default_directories())
        with self.assertRaisesRegex(ValueError, 'does not yet provision'):
            helper_recipes.catalogue(records)

    def test_interrupted_setup_is_not_replayed(self):
        job = self.store.ingest(self.installer)
        (self.store.root / 'jobs' / job / 'helper-setup.json').write_text('{"stage":"installing-helper"}')
        with patch.object(recipes, 'provision') as provision, self.assertRaisesRegex(core.HostError, 'needs inspection'):
            helper_recipes.work(self.store, job)
        provision.assert_not_called()

    def test_helper_recipe_cannot_be_applied_as_graphics(self):
        records = recipe_engine.catalogue(recipe_engine.default_directories())
        environment = self.root / 'environment'
        environment.mkdir()
        (environment / 'session.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'exact installer'):
            recipe_engine.plan(records, 'local.example-helper@1', environment)

    def test_changed_runtime_selection_is_not_silently_used_by_queued_job(self):
        job = self.store.ingest(self.installer)
        changed = recipes.recipe()
        changed['runtimes'][0]['sha256'] = '0' * 64
        with patch.object(recipes, 'recipe', return_value=changed), patch.object(recipes, 'provision') as provision:
            with self.assertRaisesRegex(core.HostError, 'inconsistent'):
                helper_recipes.work(self.store, job)
        provision.assert_not_called()

    def test_interrupted_setup_reserves_identity_before_card_exists(self):
        first = self.store.ingest(self.installer)
        (self.store.root / 'jobs' / first / 'helper-setup.json').write_text(json.dumps({
            'stage': 'installing-helper', 'reference': 'local.example-helper@1'}))
        self.store.update(first, 'failed', 'interrupted')
        second = self.store.ingest(self.installer)
        with patch.object(recipes, 'provision') as provision, self.assertRaisesRegex(core.HostError, 'earlier setup'):
            helper_recipes.work(self.store, second)
        provision.assert_not_called()
        self.assertEqual(self.store.job(second)['status'], 'failed')
        self.assertFalse(self.store.prefix(second).exists())

    def test_a_setup_that_failed_before_vendor_code_does_not_block_a_retry(self):
        first = self.store.ingest(self.installer)
        (self.store.root / 'jobs' / first / 'helper-setup.json').write_text(json.dumps({
            'stage': 'preparing-environment', 'reference': 'local.example-helper@1'}))
        self.store.update(first, 'failed', 'Could not give this environment the computer\'s machine identity (exit 1).')
        second = self.store.ingest(self.installer)
        with patch.object(recipes, 'provision', side_effect=core.HostError('reached provisioning')) as provision, \
                self.assertRaisesRegex(core.HostError, 'reached provisioning'):
            helper_recipes.work(self.store, second)
        provision.assert_called_once()

    def test_an_interrupted_early_setup_still_blocks(self):
        first = self.store.ingest(self.installer)
        (self.store.root / 'jobs' / first / 'helper-setup.json').write_text(json.dumps({
            'stage': 'preparing-environment', 'reference': 'local.example-helper@1'}))
        self.store.update(first, 'needs_attention', 'interrupted')
        second = self.store.ingest(self.installer)
        with patch.object(recipes, 'provision') as provision, self.assertRaisesRegex(core.HostError, 'earlier setup'):
            helper_recipes.work(self.store, second)
        provision.assert_not_called()

    def test_interruption_detection_respects_live_worker_lock(self):
        job = self.store.ingest(self.installer)
        directory = self.store.root / 'jobs' / job
        (directory / 'helper-setup.json').write_text('{"stage":"installing-helper"}')
        self.store.update(job, 'installing', 'Working')
        with core.lock(directory / 'job.lock'):
            self.assertEqual(helper_recipes.reconcile_interrupted(self.store), 0)
            self.assertEqual(self.store.job(job)['status'], 'installing')
        self.assertEqual(helper_recipes.reconcile_interrupted(self.store), 1)
        self.assertEqual(self.store.job(job)['status'], 'needs_attention')
        self.assertEqual(helper_recipes.reconcile_interrupted(self.store), 0)

    def test_helper_resolves_transitive_vc_components_into_saved_selection(self):
        self.recipe.write_text(self.recipe.read_text().replace('"plugg.graphics-dxvk@1"',
            '"plugg.graphics-dxvk@1", "plugg.vc2013-x64@1"'))
        job = self.store.ingest(self.installer)
        selected = json.loads((self.store.root / 'jobs' / job / 'helper-recipe.json').read_text())
        asset, = selected['vc_assets']
        self.assertEqual(asset['sha256'], 'a4bba7701e355ae29c403431f871a537897c363e215cafe706615e270984f17c')

    def test_scan_failure_keeps_helper_available_and_marks_attention(self):
        job = self.store.ingest(self.installer)
        def configure(*args, **kwargs):
            directory = self.store.prefix(job).parent
            (directory / 'session.json').write_text('{}')
            return directory / 'full', directory / 'helper'
        with patch.object(recipes, 'provision', return_value=self.root / 'runtime'),                 patch.object(recipes, 'configure', side_effect=configure),                 patch.object(core, 'run_process', return_value=0),                 patch('plugg.helper_component.install'),                 patch('plugg.proton_session.graphics_overrides'),                 patch('plugg.proton_session.foreign_prefix_processes', return_value=[]),                 patch.object(vendors, 'finish_installation', return_value={'added': 0, 'unchanged': 0, 'failures': ['Example failed to scan']}):
            helper_recipes.work(self.store, job)
        self.assertEqual(self.store.job(job)['status'], 'needs_attention')
        card, = vendors.cards(self.store)
        self.assertTrue(card['can_refresh'])
        self.assertTrue(card['needs_attention'])
        self.assertIn('Example failed to scan', card['message'])
        journal = self.store.root / 'jobs' / job / 'helper-setup.json'
        self.assertEqual(json.loads(journal.read_text())['stage'], 'complete')

    def test_read_only_match_explains_helper_without_creating_a_job(self):
        records = recipe_engine.catalogue(recipe_engine.default_directories())
        before = (self.store.root / 'jobs').exists()
        with patch.object(core, 'Store', side_effect=AssertionError('Must not create a store')),                 patch.object(recipes, 'provision', side_effect=AssertionError('Must not prepare runtime')):
            result = recipe_engine.match_input(records, self.installer)
        self.assertTrue(result['matched'])
        self.assertEqual(result['recipe']['reference'], 'local.example-helper@1')
        self.assertEqual(result['kind'], 'helper_installer')
        self.assertEqual((self.store.root / 'jobs').exists(), before)
        self.installer.write_bytes(self.installer.read_bytes() + b'different version')
        self.assertFalse(recipe_engine.match_input(records, self.installer)['matched'])

    def test_partial_helper_cannot_fall_back_to_generic_rescan(self):
        job = self.store.ingest(self.installer)
        prefix = self.store.prefix(job)
        prefix.mkdir(parents=True)
        journal = self.store.root / 'jobs' / job / 'helper-setup.json'
        journal.write_text('{"stage":"installing-helper"}')
        self.store.update(job, 'failed', 'Installer stopped')
        before = self.store.job(job)
        with patch.object(core, 'scan_and_publish') as scan, patch.object(vendors, 'work') as refresh:
            with self.assertRaisesRegex(core.HostError, 'setup has not completed'):
                core.work(self.store, job, rescan=True)
        scan.assert_not_called()
        refresh.assert_not_called()
        self.assertEqual(self.store.job(job), before)
        self.assertEqual(json.loads(journal.read_text()), {'stage': 'installing-helper'})

    def test_configured_helper_rescan_uses_managed_refresh(self):
        job = self.store.ingest(self.installer)
        prefix = self.store.prefix(job)
        prefix.mkdir(parents=True)
        (prefix.parent / 'environment.json').write_text('{"recipe":"managed-helper"}')
        with patch.object(core, 'scan_and_publish') as scan, patch.object(vendors, 'work') as refresh:
            core.work(self.store, job, rescan=True)
        scan.assert_not_called()
        refresh.assert_called_once_with(self.store, job, refresh=True)
