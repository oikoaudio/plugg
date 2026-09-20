from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from plugg import recipe_engine as engine


class RecipeAdditionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict('os.environ', {'XDG_CONFIG_HOME': str(self.root / 'config')})
        environment.start()
        self.addCleanup(environment.stop)
        self.source = self.root / 'recipe.toml'
        self.source.write_text('schema=1\nid="local.example"\nrevision=1\nkind="component"\nname="Example"\n')

    def test_addition_is_validated_and_identical_repeat_is_unchanged(self):
        first = engine.add_local(self.source)
        self.assertTrue(first['added'])
        self.assertEqual(Path(first['path']).read_bytes(), self.source.read_bytes())
        self.assertFalse(engine.add_local(self.source)['added'])
        engine.check(engine.catalogue(engine.default_directories()))

    def test_conflicting_revision_preserves_installed_recipe(self):
        first = engine.add_local(self.source)
        original = Path(first['path']).read_bytes()
        self.source.write_text(self.source.read_text().replace('name="Example"', 'name="Changed"'))
        with self.assertRaisesRegex(ValueError, 'new revision'):
            engine.add_local(self.source)
        self.assertEqual(Path(first['path']).read_bytes(), original)

    def test_unresolved_dependency_causes_no_config_writes(self):
        self.source.write_text(self.source.read_text() + 'requires=["local.missing@1"]\n')
        with self.assertRaisesRegex(ValueError, 'Missing recipe dependency'):
            engine.add_local(self.source)
        self.assertFalse((self.root / 'config').exists())

    def test_changed_source_is_not_saved_under_old_validation(self):
        record = engine.load(self.source)
        self.source.write_text('shell="bad"')
        with patch.object(engine, 'load', return_value=record), self.assertRaisesRegex(ValueError, 'changed'):
            engine.add_local(self.source)
        self.assertFalse((self.root / 'config').exists())
