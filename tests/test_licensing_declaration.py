"""A recipe states its vendor's licensing once, so nobody has to be asked.

Whether losing an activation can be undone is a fact about the vendor, the same
for everyone who installs the product. Asking the person installing means asking
at the moment they are least likely to know and least likely to care -- and the
moment they would think to ask is after the environment already holds something
to lose.
"""
from pathlib import Path
import json
import tempfile
import unittest

from plugg import core, licensing, recipe_engine, recipes


class DeclarationTests(unittest.TestCase):
    def test_a_recipe_may_not_claim_how_many_activations_remain(self):
        # That is a fact about one purchase, not about the product. A recipe
        # shared with strangers has no business carrying it.
        with self.assertRaisesRegex(ValueError, 'Unknown licensing fields'):
            licensing.validate_declaration({'vendor': 'X', 'recovery': 'deactivate-first',
                                            'activations_remaining': 3})

    def test_recovery_must_be_one_of_the_known_classes(self):
        for bad in ('whatever', '', None, 5):
            with self.assertRaises(ValueError, msg=repr(bad)):
                licensing.validate_declaration({'vendor': 'X', 'recovery': bad})

    def test_the_vendor_and_the_class_are_both_required(self):
        for partial in ({'vendor': 'X'}, {'recovery': 'reactivatable'}, {}):
            with self.assertRaisesRegex(ValueError, 'licensing requires'):
                licensing.validate_declaration(partial)

    def test_a_note_is_bounded_so_it_cannot_become_a_place_for_secrets(self):
        with self.assertRaisesRegex(ValueError, 'at most'):
            licensing.validate_declaration({'vendor': 'X', 'recovery': 'reactivatable',
                                            'note': 'x' * 513})


class ProtectFromRecipeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = Path(self.tmp.name) / 'env'
        (self.env / 'prefix/drive_c').mkdir(parents=True)
        (self.env / 'prefix/system.reg').write_text(
            'WINE REGISTRY Version 2\n\n[Software\\\\Microsoft\\\\Cryptography] 1\n'
            '"MachineGuid"="0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"\n')

    def test_declaring_it_protects_the_environment(self):
        licensing.protect_declared(self.env, {'vendor': 'Klevgrand', 'recovery': 'deactivate-first',
                                              'note': 'Three machines, one at a time.'})
        state = licensing.status(self.env)
        self.assertTrue(state['protected'])
        self.assertEqual([p['name'] for p in state['products']], ['Klevgrand'])
        self.assertEqual(state['severity'], 'deactivate-first')

    def test_the_guard_then_refuses_a_rebuild_without_deactivating(self):
        # The whole point: the warning arrives when someone tries to destroy
        # the environment, which is the only moment it is useful.
        licensing.protect_declared(self.env, {'vendor': 'Klevgrand', 'recovery': 'deactivate-first'})
        with self.assertRaises(licensing.LicensedEnvironmentError) as caught:
            licensing.guard(self.env, 'recreate_prefix')
        self.assertIn('Deactivate', str(caught.exception))
        self.assertIn('Klevgrand', str(caught.exception))

    def test_a_recipe_that_says_nothing_protects_nothing(self):
        self.assertIsNone(licensing.protect_declared(self.env, None))
        self.assertFalse(licensing.status(self.env)['protected'])


class ShippedRecipeTests(unittest.TestCase):
    def test_the_klevgrand_recipe_declares_what_a_rebuild_costs(self):
        declaration = recipes.recipe()['licensing']
        licensing.validate_declaration(declaration)
        self.assertEqual(declaration['recovery'], 'deactivate-first')
        self.assertEqual(declaration['vendor'], 'Klevgrand')

    def test_every_vendor_setup_protects_the_environment_it_built(self):
        # Discovered, not listed: a new vendor setup path that forgets this
        # leaves its users exactly where the terminal-only flow left them.
        import ast
        from plugg import helper_recipes
        for module in (recipes, helper_recipes):
            tree = ast.parse(Path(module.__file__).read_text())
            work = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef) and n.name == 'work')
            calls = [n.func.attr for n in ast.walk(work)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
            self.assertIn('protect_declared', calls, module.__name__)


class RecipeSchemaTests(unittest.TestCase):
    def write(self, body):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: None)
        path = directory / 'r.toml'
        path.write_text(body)
        return path

    def test_a_vendor_recipe_may_declare_licensing(self):
        path = self.write('schema = 1\nid = "local.v"\nrevision = 1\nkind = "vendor"\n'
                          'name = "V"\n[licensing]\nvendor = "V"\nrecovery = "reactivatable"\n')
        self.assertEqual(recipe_engine.load(path)['data']['licensing']['recovery'], 'reactivatable')

    def test_a_component_may_not(self):
        path = self.write('schema = 1\nid = "local.c"\nrevision = 1\nkind = "component"\n'
                          'name = "C"\npurpose = "p"\n[licensing]\nvendor = "V"\nrecovery = "reactivatable"\n')
        with self.assertRaisesRegex(ValueError, 'describes a vendor'):
            recipe_engine.load(path)

    def test_a_bad_declaration_stops_the_recipe_loading(self):
        path = self.write('schema = 1\nid = "local.v"\nrevision = 1\nkind = "vendor"\n'
                          'name = "V"\n[licensing]\nvendor = "V"\nrecovery = "sometimes"\n')
        with self.assertRaisesRegex(ValueError, 'recovery must be one of'):
            recipe_engine.load(path)


if __name__ == '__main__':
    unittest.main()
