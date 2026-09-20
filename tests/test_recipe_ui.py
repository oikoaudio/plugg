"""Recipes are only safe to share if the person adding one can see it.

The capability report existed from the beginning, and for months the only
way to reach it was a terminal. The person who most needs it — someone who
opens a file another person posted — is exactly the person not typing
`recipe explain`. These tests hold two things: that a recipe cannot be
added without the report being produced first, and that removing one you
added is possible, bounded, and cannot break the catalogue.
"""
import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugg import recipe_engine as engine

GUI = Path(__file__).resolve().parents[1] / 'plugg' / 'gui.py'


def function(name, tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError('gui.py has no ' + name)


def names(node):
    return {child.attr for child in ast.walk(node) if isinstance(child, ast.Attribute)} | \
           {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


class AddingShowsTheReport(unittest.TestCase):
    """Discovered from the source, so a later refactor cannot quietly undo it."""

    def setUp(self):
        self.tree = ast.parse(GUI.read_text(encoding='utf-8'))

    def test_choosing_a_file_reports_on_it_and_does_not_add_it(self):
        chosen = names(function('recipe_chosen', self.tree))
        self.assertIn('report', chosen, 'choosing a recipe must produce its capability report')
        self.assertNotIn('add_local', chosen,
                         'a chosen file must not be added before anyone has seen what it does')

    def test_only_one_place_adds_a_recipe_and_it_is_reached_from_the_preview(self):
        methods = [node for parent in ast.walk(self.tree) if isinstance(parent, ast.ClassDef)
                   for node in parent.body if isinstance(node, ast.FunctionDef)]
        adders = [node.name for node in methods if 'add_local' in names(node)]
        self.assertEqual(adders, ['add_recipe'])
        self.assertIn('add_recipe', names(function('preview_recipe', self.tree)))

    def test_a_refused_recipe_cannot_be_added_from_the_preview(self):
        body = ast.get_source_segment(GUI.read_text(encoding='utf-8'),
                                      function('preview_recipe', self.tree))
        self.assertIn("'refused'", body)
        self.assertIn('set_sensitive(False)', body)

    def test_the_report_window_shows_downloads_pinned_to_a_hash(self):
        body = ast.get_source_segment(GUI.read_text(encoding='utf-8'),
                                      function('recipe_window', self.tree))
        for shown in ('capability_descriptions', 'flags', 'downloads', 'runs', 'claims', 'sha256'):
            with self.subTest(shown=shown):
                self.assertIn(shown, body)


class RemovingWhatYouAdded(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict('os.environ', {'XDG_CONFIG_HOME': str(self.root / 'config')})
        environment.start()
        self.addCleanup(environment.stop)
        self.source = self.root / 'recipe.toml'
        self.source.write_text('schema=1\nid="local.example"\nrevision=1\nkind="component"\nname="Example"\n')

    def test_a_recipe_you_added_can_be_removed(self):
        added = engine.add_local(self.source)
        self.assertTrue(Path(added['path']).is_file())
        result = engine.remove_local(added['reference'])
        self.assertTrue(result['removed'])
        self.assertFalse(Path(added['path']).exists())
        self.assertNotIn(added['reference'], engine.catalogue(engine.default_directories()))

    def test_a_recipe_that_ships_with_the_application_is_not_yours_to_delete(self):
        shipped = [ref for ref, record in engine.catalogue(engine.default_directories()).items()
                   if Path(record['source']).resolve().parent != (self.root / 'config').resolve()]
        if not shipped:
            self.skipTest('no shipped recipes in this catalogue')
        with self.assertRaisesRegex(ValueError, 'part of the application'):
            engine.remove_local(shipped[0])

    def test_removing_something_another_recipe_needs_is_refused(self):
        base = engine.add_local(self.source)
        dependent = self.root / 'dependent.toml'
        dependent.write_text('schema=1\nid="local.dependent"\nrevision=1\nkind="component"\n'
                             'name="Dependent"\nrequires=["local.example@1"]\n')
        engine.add_local(dependent)
        with self.assertRaises(ValueError):
            engine.remove_local(base['reference'])
        self.assertTrue(Path(base['path']).is_file())

    def test_removing_something_that_is_not_there_says_so(self):
        with self.assertRaisesRegex(ValueError, 'No such recipe'):
            engine.remove_local('local.absent@1')


if __name__ == '__main__':
    unittest.main()
