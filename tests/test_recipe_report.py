"""The bird's-eye view must be complete, deterministic and hard to talk past.

A shared recipe is someone else's decisions running against the user's licensed
environments. Review does not scale, so what a recipe can do has to be derived
from the file and capped by where the file lives.
"""
import json
from pathlib import Path
import tempfile
import unittest

from plugg import recipe_engine as engine, recipe_report

BASE = ('schema = 1\nid = "local.example"\nrevision = 1\nkind = "vendor"\n'
        'name = "Example"\nvendor = "Example"\n')
HELPER = ('[helper]\ninstaller_sha256 = "%s"\narguments = ["/S"]\n'
          'name = "Example Helper"\nexecutable = "Example/helper.exe"\narchive_tools = false\n' % ('a' * 64))


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def recipe(self, text, name='local.example.toml', directory=''):
        path = self.root / directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def report(self, text, directory='', tier=None):
        path = self.recipe(text, directory=directory)
        records = {**engine.catalogue([Path(engine.__file__).parent / 'recipes/community'])}
        record = engine.load(path)
        ref = engine.reference(record)
        records[ref] = record
        return recipe_report.report(records, ref, source=path, tier=tier)

    def test_pa_revision_describes_same_graphics_and_added_fix(self):
        records = engine.catalogue([Path(engine.__file__).parent / 'recipes/community'])
        first = recipe_report.report(records, 'plugg.plugin-alliance@1')
        second = recipe_report.report(records, 'plugg.plugin-alliance@2')
        self.assertIsNone(first['revision_note'])
        self.assertIn('Same graphics settings as recipe revision 1', second['revision_note'])
        self.assertIn('Bridge editor teardown fix', second['revision_note'])

    def test_documentation_only_ua_cannot_plan_an_environment_change(self):
        records = engine.catalogue([Path(engine.__file__).parent / 'recipes/community'])
        result = recipe_report.report(records, 'plugg.universal-audio@1')
        self.assertTrue(result['documentation_only'])
        self.assertIn('plugg.pace-license-support@1',
                      [item['reference'] for item in result['components']])
        # No session exists: rejection must precede reading any environment files.
        with self.assertRaisesRegex(ValueError, 'Documentation only'):
            engine.plan(records, result['reference'], self.root / 'never-created')
        self.assertFalse((self.root / 'never-created').exists())
        records['plugg.universal-audio@1']['data']['documentation_only'] = False
        with self.assertRaisesRegex(ValueError, 'Documentation only'):
            engine.plan(records, result['reference'], self.root / 'never-created')

    def test_vendor_runtime_distinguishes_new_setup_existing_and_documented(self):
        records = engine.catalogue([Path(engine.__file__).parent / 'recipes/community'])
        runtime = lambda ref: recipe_report.report(records, 'plugg.' + ref)['runtime']
        from plugg import recipes
        for ref in ('klevgrand@1', 'variety-of-sound@1'):
            self.assertIn('UMU-Proton 10.0-4', runtime(ref)['summary'])
            self.assertEqual(runtime(ref)['assets'], recipes.recipe()['runtimes'])
        self.assertEqual(runtime('plugin-alliance@2')['assets'], [])
        self.assertIn('selected environment', runtime('plugin-alliance@2')['summary'])
        self.assertIn('selected environment', runtime('universal-audio@1')['summary'])
        self.assertIn('OLE32', ' '.join(runtime('universal-audio@1')['details']))
        self.assertEqual(runtime('universal-audio@1')['assets'], [])

    # Capabilities

    def test_every_capability_has_a_description_and_a_tier_that_allows_it(self):
        for name in recipe_report.CAPABILITIES:
            self.assertTrue(recipe_report.CAPABILITIES[name].strip())
            self.assertTrue(any(name in allowed for allowed in recipe_report.TIERS.values()),
                            name + ' is allowed by no tier')

    def test_a_graphics_recipe_declares_only_graphics(self):
        result = self.report(BASE + 'requires = ["plugg.graphics-dxvk@1"]\n')
        self.assertEqual(result['capabilities'], ['configure-graphics'])
        self.assertEqual(result['verdict'], 'routine')

    def test_a_helper_recipe_declares_running_a_supplied_installer(self):
        result = self.report(BASE + 'requires = ["plugg.graphics-dxvk@1"]\n' + HELPER)
        self.assertIn('run-vendor-installer', result['capabilities'])
        self.assertIn('claim-installer', result['capabilities'])

    def test_a_module_recipe_declares_downloading_and_joining(self):
        result = self.report(
            BASE + 'requires = ["plugg.graphics-dxvk@1","plugg.vc2013-x64@1"]\n'
            '[modules."%s"]\nname = "Example"\ndependency = "plugg.vc2013-x64@1"\n' % ('b' * 64))
        for capability in ('import-module', 'claim-module', 'download-component', 'join-environment'):
            self.assertIn(capability, result['capabilities'])

    # Tier ceilings

    def test_a_community_recipe_may_not_run_a_vendor_installer(self):
        result = self.report(BASE + 'requires = ["plugg.graphics-dxvk@1"]\n' + HELPER,
                             directory='recipes/community')
        self.assertEqual(result['tier'], 'community')
        self.assertEqual(result['verdict'], 'refused')
        self.assertIn('run-vendor-installer', result['exceeds_tier'])

    def test_the_same_recipe_is_allowed_once_reviewed(self):
        result = self.report(BASE + 'requires = ["plugg.graphics-dxvk@1"]\n' + HELPER,
                             directory='recipes/reviewed')
        self.assertEqual(result['tier'], 'reviewed')
        self.assertNotEqual(result['verdict'], 'refused')

    def test_no_tier_permits_a_capability_that_does_not_exist(self):
        for tier, allowed in recipe_report.TIERS.items():
            self.assertTrue(allowed <= set(recipe_report.CAPABILITIES), tier)

    def test_community_is_a_subset_of_reviewed(self):
        self.assertTrue(recipe_report.TIERS['community'] < recipe_report.TIERS['reviewed'])

    def test_tier_comes_from_the_directory_not_the_recipe(self):
        text = BASE + 'requires = ["plugg.graphics-dxvk@1"]\n'
        self.assertEqual(self.report(text, directory='recipes/community')['tier'], 'community')
        self.assertEqual(self.report(text, directory='recipes/reviewed')['tier'], 'reviewed')
        self.assertEqual(self.report(text)['tier'], 'local')

    def test_shipped_recipes_are_recognized_as_shipped(self):
        records = engine.catalogue([Path(engine.__file__).parent / 'recipes/community'])
        result = recipe_report.report(records, 'plugg.graphics-dxvk@1')
        self.assertEqual(result['tier'], 'shipped')

    # Flags

    def test_running_a_supplied_installer_is_flagged_with_its_exact_arguments(self):
        result = self.report(BASE + 'requires = ["plugg.graphics-dxvk@1"]\n' + HELPER,
                             directory='recipes/reviewed')
        flag = next(item for item in result['flags'] if item['code'] == 'runs-vendor-installer')
        self.assertEqual(flag['level'], 'danger')
        self.assertIn('/S', flag['message'])

    def test_claiming_a_third_party_installer_is_flagged(self):
        result = self.report(BASE + 'requires = ["plugg.graphics-dxvk@1"]\n' + HELPER,
                             directory='recipes/reviewed')
        self.assertTrue(any(item['code'] == 'claims-third-party-installer' for item in result['flags']))

    def test_downloads_are_listed_with_their_url_and_hash(self):
        result = self.report(
            BASE + 'requires = ["plugg.graphics-dxvk@1","plugg.vc2013-x64@1"]\n'
            '[modules."%s"]\nname = "Example"\ndependency = "plugg.vc2013-x64@1"\n' % ('b' * 64))
        self.assertTrue(result['downloads'])
        for download in result['downloads']:
            self.assertTrue(download['url'].startswith('https://'))
            self.assertEqual(len(download['sha256']), 64)

    def test_a_bridge_patch_requirement_is_dangerous(self):
        result = self.report(BASE + 'requires = ["plugg.graphics-dxvk@1","plugg.bridge-editor-detach@1"]\n')
        self.assertIn('require-bridge-patch', result['capabilities'])
        self.assertEqual(result['verdict'], 'needs-review')

    def test_flags_are_ordered_worst_first(self):
        result = self.report(BASE + 'requires = ["plugg.graphics-dxvk@1"]\n' + HELPER,
                             directory='recipes/community')
        levels = [recipe_report.LEVELS.index(item['level']) for item in result['flags']]
        self.assertEqual(levels, sorted(levels, reverse=True))

    def test_the_report_is_deterministic(self):
        text = BASE + 'requires = ["plugg.graphics-dxvk@1"]\n' + HELPER
        first = self.report(text, directory='recipes/reviewed')
        second = self.report(text, directory='recipes/reviewed')
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_rendering_names_every_capability_and_flag(self):
        result = self.report(BASE + 'requires = ["plugg.graphics-dxvk@1"]\n' + HELPER,
                             directory='recipes/reviewed')
        text = recipe_report.render(result)
        for name in result['capabilities']:
            self.assertIn(recipe_report.CAPABILITIES[name], text)
        for item in result['flags']:
            self.assertIn(item['message'], text)

    def test_a_recipe_cannot_disguise_itself_with_invisible_text(self):
        for value in ('Example‮evil', 'Example\x1b[32m ok', 'Example\nSecond line'):
            with self.assertRaises(ValueError):
                engine.load(self.recipe(BASE.replace('name = "Example"', 'name = "%s"' % value),
                                        name='disguise.toml'))

    def test_a_recipe_cannot_claim_the_shipped_namespace(self):
        text = BASE.replace('local.example', 'plugg.example')
        with self.assertRaisesRegex(ValueError, 'reserved'):
            engine.add_local(self.recipe(text, name='reserved.toml'))


class ComponentIndexTests(unittest.TestCase):
    """The component catalogue is what lets someone avoid trusting a recipe."""

    def setUp(self):
        self.records = engine.catalogue([Path(engine.__file__).parent / 'recipes/community'])
        self.index = recipe_report.component_index(self.records)

    def test_every_shipped_component_says_which_problem_it_solves(self):
        missing = [item['reference'] for item in self.index if not item['purpose']]
        self.assertEqual(missing, [], 'components without a purpose: ' + ', '.join(missing))

    def test_a_purpose_is_a_sentence_not_a_label(self):
        for item in self.index:
            self.assertGreater(len(item['purpose']), 30, item['reference'])

    def test_the_index_lists_capabilities_so_a_choice_can_be_informed(self):
        dxvk = next(item for item in self.index if item['reference'] == 'plugg.graphics-dxvk@1')
        self.assertEqual(dxvk['capabilities'], ['configure-graphics'])

    def test_components_name_consuming_recipes_and_expose_full_report(self):
        fix = next(item for item in self.index if item['reference'] == 'plugg.bridge-editor-detach@1')
        self.assertIn('plugg.plugin-alliance@2', [item['reference'] for item in fix['used_by']])
        self.assertNotIn('plugg.plugin-alliance@1', [item['reference'] for item in fix['used_by']])
        self.assertIn('require-bridge-patch', fix['report']['capabilities'])
        self.assertTrue(any('Does not install or replace' in flag['message'] for flag in fix['report']['flags']))

    def test_current_helpers_share_archive_component(self):
        archives = next(item for item in self.index
                        if item['reference'] == 'plugg.windows-archive-tools@2')
        consumers = {item['reference'] for item in archives['used_by']}
        self.assertIn('plugg.klevgrand@1', consumers)
        self.assertIn('plugg.universal-audio@2', consumers)
        self.assertTrue(recipe_report.report(
            self.records, 'plugg.universal-audio@2')['documentation_only'])

    def test_evidence_is_bound_to_exact_recipe_bytes(self):
        record = self.records['plugg.vc2013-x64@1']
        evidence = recipe_report.component_evidence(record)
        self.assertIn('Synthetic fixture', evidence['limitations'])
        changed = dict(record, sha256='0' * 64)
        self.assertIsNone(recipe_report.component_evidence(changed))
        for item in self.index:
            evidence = item['report']['evidence']
            self.assertIsNotNone(evidence, item['reference'])
            source = evidence['source']
            if source.startswith('plugg-lab: '):
                # Raw evidence lives in the private lab notebook, not the public tree.
                self.assertRegex(source, r'^plugg-lab: [\w./-]+$')
            else:
                self.assertTrue((Path(__file__).resolve().parents[1] / source).is_file())

    def test_vendor_recipes_are_not_offered_as_components(self):
        self.assertTrue(all(self.records[item['reference']]['data']['kind'] == 'component'
                            for item in self.index))

    def test_purpose_belongs_to_components_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'vendor.toml'
            path.write_text(BASE + 'purpose = "Solves a problem that vendors do not have."\n')
            with self.assertRaisesRegex(ValueError, 'purpose describes a component'):
                engine.load(path)


if __name__ == '__main__':
    unittest.main()


class TierPathTests(unittest.TestCase):
    """Where a recipe lives must be unambiguous to a reviewer and to the check.

    These cases were all found by an adversarial verification pass: matching a
    tier name anywhere in the path let recipes/community/reviewed/x.toml claim
    the reviewed ceiling while the diff read "community".
    """

    def test_only_a_direct_child_of_a_tier_directory_gets_that_tier(self):
        self.assertEqual(recipe_report.tier_for('/r/recipes/community/a.toml'), 'community')
        self.assertEqual(recipe_report.tier_for('/r/recipes/reviewed/a.toml'), 'reviewed')

    def test_a_nested_tier_name_is_refused_rather_than_inferred(self):
        for path in ('/r/recipes/community/reviewed/a.toml',
                     '/r/recipes/community/sub/reviewed/deep/a.toml',
                     '/r/recipes/reviewed/community/a.toml',
                     '/r/reviewed/recipes/a.toml'):
            with self.assertRaises(ValueError, msg=path):
                recipe_report.tier_for(path)

    def test_a_tier_name_outside_a_recipes_directory_is_not_a_tier(self):
        self.assertEqual(recipe_report.tier_for('/home/me/reviewed/a.toml'), 'local')
        self.assertEqual(recipe_report.tier_for('/home/me/.config/plugg/recipes/a.toml'),
                         'local')

    def test_the_review_script_refuses_a_misplaced_recipe(self):
        import importlib.util
        script = Path(__file__).resolve().parents[1] / 'scripts/review-recipe.py'
        spec = importlib.util.spec_from_file_location('review_recipe', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        root = Path(module.ROOT)
        self.assertIsNone(module.misplaced(root / 'recipes/community/a.toml'))
        self.assertIsNone(module.misplaced(root / 'recipes/reviewed/a.toml'))
        for path in ('recipes/community/reviewed/a.toml', 'recipes/a.toml',
                     'recipes/community/sub/a.toml', 'recipes/community/notes.md'):
            self.assertIsNotNone(module.misplaced(root / path), path)


class CapabilityDepthTests(unittest.TestCase):
    """A capability must not be hidden one dependency deep."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_a_helper_carried_by_a_dependency_is_still_reported(self):
        component = self.root / 'component.toml'
        component.write_text(
            'schema = 1\nid = "local.sneaky"\nrevision = 1\nkind = "component"\n'
            'name = "Looks harmless"\npurpose = "Claims to do nothing of consequence at all."\n'
            'requires = ["plugg.graphics-dxvk@1"]\n' + HELPER)
        vendor = self.root / 'vendor.toml'
        vendor.write_text(BASE + 'requires = ["local.sneaky@1"]\n')
        records = engine.catalogue([Path(engine.__file__).parent / 'recipes/community'])
        for path in (component, vendor):
            record = engine.load(path)
            records[engine.reference(record)] = record
        result = recipe_report.report(records, 'local.example@1', tier='community')
        self.assertIn('run-vendor-installer', result['capabilities'])
        self.assertEqual(result['verdict'], 'refused')


class CatalogueBadgeTests(unittest.TestCase):
    def test_badges_do_not_disguise_routine_capabilities_as_pending_reviews(self):
        result = {'verdict':'needs-review', 'runs':[{}], 'capabilities':['create-environment']}
        self.assertEqual(recipe_report.catalogue_badge(result), ('Runs an installer', None))
        self.assertEqual(result['verdict'], 'needs-review')

    def test_refusal_stays_visible_even_for_documentation(self):
        self.assertEqual(recipe_report.catalogue_badge({'verdict':'refused','documentation_only':True}),
                         ('Blocked by recipe policy', 'danger'))

    def test_patch_requirement_is_not_reported_as_installed(self):
        self.assertEqual(recipe_report.catalogue_badge({'verdict':'needs-review','capabilities':['require-bridge-patch']}),
                         ('Requires bridge patches', None))
