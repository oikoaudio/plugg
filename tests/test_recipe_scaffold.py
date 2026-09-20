"""A generated recipe must be valid, honest about its tier, and ready to explain."""
from pathlib import Path
import tempfile
import unittest

from plugg import core, recipe_engine as engine, recipe_report, recipe_scaffold
from test_core import fake_pe


class ScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def bundle(self, name='Example.vst3'):
        inner = self.root / 'download' / name / 'Contents' / 'x86_64-win'
        inner.mkdir(parents=True)
        fake_pe(inner / name)
        return self.root / 'download' / name

    def written(self, text, name='generated.toml'):
        path = self.root / name
        path.write_text(text)
        return path

    def test_a_generated_module_recipe_validates(self):
        text = recipe_scaffold.scaffold(self.bundle(), vendor='Example Audio')
        record = engine.load(self.written(text))
        self.assertEqual(record['data']['id'], 'local.example-audio')
        self.assertEqual(record['data']['kind'], 'vendor')

    def test_the_generated_hash_is_the_module_the_manager_would_match(self):
        from plugg import standalone
        bundle = self.bundle()
        record = engine.load(self.written(recipe_scaffold.scaffold(bundle)))
        self.assertEqual(list(record['data']['modules']),
                         [core.digest(standalone.module_path(bundle))])

    def test_a_generated_module_recipe_resolves_against_shipped_components(self):
        record = engine.load(self.written(recipe_scaffold.scaffold(self.bundle(), vendor='Example')))
        records = {**engine.catalogue([Path(engine.__file__).parent / 'recipes/community']),
                   engine.reference(record): record}
        engine.check(records)

    def test_a_generated_module_recipe_is_allowed_at_community_tier(self):
        record = engine.load(self.written(recipe_scaffold.scaffold(self.bundle(), vendor='Example')))
        records = {**engine.catalogue([Path(engine.__file__).parent / 'recipes/community']),
                   engine.reference(record): record}
        result = recipe_report.report(records, engine.reference(record), tier='community')
        self.assertEqual(result['exceeds_tier'], [])

    def test_a_generated_installer_recipe_says_it_needs_review(self):
        installer = fake_pe(self.root / 'Setup.exe')
        text = recipe_scaffold.scaffold(installer, vendor='Example')
        self.assertIn('reviewed-tier', text)
        self.assertIn('cannot live in', text)
        self.assertIn(core.digest(installer), text)

    def test_a_generated_installer_recipe_loads_so_it_can_be_explained(self):
        text = recipe_scaffold.scaffold(fake_pe(self.root / 'Setup.exe'), vendor='Example')
        record = engine.load(self.written(text))
        # Loadable but obviously unfinished: only the person who ran the
        # installer knows where it puts things, and guessing is worse than asking.
        self.assertIn('TODO', record['data']['helper']['executable'])
        self.assertIn('TODO', record['data']['notes'])

    def test_a_generated_installer_recipe_is_refused_at_community_tier(self):
        record = engine.load(self.written(
            recipe_scaffold.scaffold(fake_pe(self.root / 'Setup.exe'), vendor='Example')))
        records = {**engine.catalogue([Path(engine.__file__).parent / 'recipes/community']),
                   engine.reference(record): record}
        result = recipe_report.report(records, engine.reference(record), tier='community')
        self.assertEqual(result['verdict'], 'refused')
        self.assertIn('run-vendor-installer', result['exceeds_tier'])

    def test_identity_is_namespaced_away_from_the_shipped_namespace(self):
        for vendor in ('Example', 'Plugg', 'Weird  Name!!'):
            identity = recipe_scaffold.suggest_id(vendor)
            self.assertTrue(identity.startswith('local.'))
            self.assertTrue(engine.ID.fullmatch(identity), identity)

    def test_a_chosen_dependency_is_used(self):
        text = recipe_scaffold.scaffold(self.bundle(), vendor='Example',
                                        dependency='plugg.vc2013-x64@1')
        record = engine.load(self.written(text))
        self.assertIn('plugg.vc2013-x64@1', record['data']['requires'])

    def test_missing_and_linked_inputs_are_refused(self):
        with self.assertRaises(core.HostError):
            recipe_scaffold.scaffold(self.root / 'absent.vst3')
        target = self.bundle('Linked.vst3')
        link = self.root / 'link.vst3'
        link.symlink_to(target)
        with self.assertRaisesRegex(core.HostError, 'not a link'):
            recipe_scaffold.scaffold(link)

    def test_quoting_survives_a_vendor_name_with_punctuation(self):
        text = recipe_scaffold.scaffold(self.bundle(), vendor='O\'Hara "Audio" \\ Co')
        record = engine.load(self.written(text))
        self.assertEqual(record['data']['vendor'], 'O\'Hara "Audio" \\ Co')


if __name__ == '__main__':
    unittest.main()
