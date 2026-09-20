import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from plugg.__main__ import main


class RecipeCliTest(unittest.TestCase):
    def invoke(self, *arguments):
        output = io.StringIO()
        with patch('sys.argv', ['plugg', 'recipe', *arguments]),              patch('plugg.__main__.Store', side_effect=AssertionError('Recipe command initialized a library')),              contextlib.redirect_stderr(output), contextlib.redirect_stdout(output):
            code = main()
        return code, output.getvalue()

    def test_ignored_targets_and_options_are_rejected(self):
        for arguments in [('check', 'my-recipe.toml'), ('list', '--environment', '/tmp/env'),
                          ('validate', 'example.toml', '--recipe-dir', '/tmp'),
                          ('add', 'example.toml', '--recipe-dir', '/tmp'),
                          ('add', 'example.toml', '--environment', '/tmp/env')]:
            code, message = self.invoke(*arguments)
            self.assertEqual(code, 1)
            self.assertIn('does not', message)

    def test_explicit_missing_directory_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            code, message = self.invoke('check', '--recipe-dir', str(Path(temporary) / 'missing'))
        self.assertEqual(code, 1)
        self.assertIn('Recipe directory does not exist', message)

    def test_invalid_file_error_names_the_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'bad-vendor.toml'
            source.write_text('schema = "wrong"')
            code, message = self.invoke('validate', str(source))
        self.assertEqual(code, 1)
        self.assertIn('bad-vendor.toml', message)
        self.assertIn('Missing recipe field', message)

    def test_duplicate_reference_error_identifies_both_sources(self):
        from plugg.recipe_engine import catalogue
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('one.toml', 'two.toml'):
                (root / name).write_text('schema=1\nid="local.example"\nrevision=1\nkind="component"\nname="Example"')
            with self.assertRaises(ValueError) as caught:
                catalogue([root])
        self.assertIn('one.toml', str(caught.exception))
        self.assertIn('two.toml', str(caught.exception))

    def test_add_saves_recipe_once_without_initializing_library(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'example.toml'
            source.write_text('schema=1\nid="local.cli-example"\nrevision=1\nkind="component"\nname="Example"\n')
            with patch.dict('os.environ', {'XDG_CONFIG_HOME': str(root / 'config'),
                                           'XDG_DATA_HOME': str(root / 'data')}):
                code, output = self.invoke('add', str(source))
                self.assertEqual(code, 0, output)
                result = json.loads(output)
                self.assertTrue(result['added'])
                self.assertEqual(result['reference'], 'local.cli-example@1')
                self.assertEqual(Path(result['path']).read_bytes(), source.read_bytes())
                code, output = self.invoke('add', str(source))
                self.assertEqual(code, 0, output)
                self.assertFalse(json.loads(output)['added'])
                self.assertFalse((root / 'data').exists())

    def test_add_requires_path(self):
        code, message = self.invoke('add')
        self.assertEqual(code, 1)
        self.assertIn('Provide a recipe TOML path', message)
