"""Every operation that writes into an existing environment must pass the guard.

These are structural tests, and they are deliberately annoying to satisfy.
Adding a function that writes into an environment should force a decision about
what it does to one holding someone's activations — so the audit DISCOVERS
writers rather than checking a list someone remembered to update. A new writer
fails until it is either guarded or exempted here with a reason.
"""
import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugg import archive_component, core, helper_component, licensing, vc_component

SOURCE = Path(__file__).resolve().parents[1] / 'plugg'

#: Calls that put something on disk.
WRITES = {'write_text', 'write_bytes', 'mkdir', 'copy2', 'copytree', 'copyfile',
          'atomic_json', 'run_process', 'symlink_to', 'chmod', 'unlink', 'rmtree', 'touch'}
#: Parameter names that mean "somewhere in a managed environment".
PLACES = {'prefix', 'environment', 'directory', 'env', 'place'}

#: Writers that do not need a guard, each with the reason. An entry here is a
#: decision on the record, not a way to silence the audit.
EXEMPT = {
    ('vc_component.py', 'run_installer'):
        'Private to vc_component.install, which guards install_vc_runtime before calling it.',
    ('core.py', 'create_launcher'):
        'Writes the launcher while an environment is being created; the callers that '
        'create or reuse an environment own that decision and are guarded themselves.',
    ('core.py', 'write_module_launcher'):
        'Writes only the launcher script its caller names; softube.configure and '
        'ua_connect.configure guard before calling it. It touches no prefix or identity value.',
    ('core.py', 'publish'):
        'Writes into the DAW publication directory, which is outside every environment.',
    ('recipes.py', '_configure_graphics_locked'):
        'Private. Both public entry points, recipe_engine.apply and '
        'recipes.configure_graphics, guard before calling it.',
    ('ua_connect.py', 'prepare_runtime'):
        'Quiesces an environment before use and refuses while anything is running. '
        'It writes no identity value; its caller ua_connect.configure is guarded.',
    ('ua_connect.py', '_run'):
        'Records launcher state for an environment ua_connect.configure has guarded.',
    ('vendors.py', 'clear_helper_state'):
        'Removes this library\'s own helper-state.json beside the prefix. It writes nothing '
        'inside the prefix and reads no identity value, so it cannot change what a vendor '
        'sees; it only stops the card claiming a program is open.',
    ('licensing.py', '_key'): 'Licensing itself: writes the key the guard depends on.',
    ('licensing.py', 'protect'): 'Licensing itself: writes the record the guard reads.',
    ('licensing.py', 'unprotect'): 'Licensing itself; requires the confirmation phrase.',
    ('licensing.py', 'deactivated'): 'Licensing itself; the user names each product and repeats the phrase.',
    ('ilok_setup.py', '_record_group'): 'Writes the library-level record of which environment is the iLok one, not an environment.',
    ('licensing.py', 'acknowledge'): 'Licensing itself; requires the confirmation phrase.',
    ('licensing.py', 'consume'): 'Licensing itself: marks an acknowledgement as used.',
    ('licensing.py', 'guard'): 'Licensing itself: this is the guard.',
    ('licensing.py', 'backup'): 'Adds a recovery point; removes nothing.',
    ('licensing.py', 'restore'):
        'Requires the confirmation phrase, refuses while plug-ins are running, and '
        'takes a recovery point of the current state first.',
}


def functions():
    for path in sorted(SOURCE.glob('*.py')):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                yield path.name, node


def writes_into_an_environment(node):
    params = {arg.arg for arg in node.args.args} | {arg.arg for arg in node.args.kwonlyargs}
    if not params & PLACES:
        return False
    return any(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
               and call.func.attr in WRITES for call in ast.walk(node))


def guarded_operations(node):
    """Operations passed to guard(), whether called bare or through a module."""
    names = []
    for call in ast.walk(node):
        if not isinstance(call, ast.Call) or len(call.args) != 2:
            continue
        function = call.func
        called = function.attr if isinstance(function, ast.Attribute) else getattr(function, 'id', None)
        if called == 'guard' and isinstance(call.args[1], ast.Constant):
            names.append(call.args[1].value)
    return names


class GuardCoverageTests(unittest.TestCase):
    def test_every_writer_is_guarded_or_exempt_with_a_reason(self):
        missing = [f'{name}:{node.name}' for name, node in functions()
                   if writes_into_an_environment(node)
                   and not guarded_operations(node)
                   and (name, node.name) not in EXEMPT]
        self.assertEqual(missing, [], 'These write into an environment without calling '
                                      'licensing.guard. Guard them, or add an entry to EXEMPT '
                                      'saying why they are safe: ' + ', '.join(missing))

    def test_exemptions_name_functions_that_still_exist(self):
        known = {(name, node.name) for name, node in functions()}
        stale = [f'{a}:{b}' for a, b in EXEMPT if (a, b) not in known]
        self.assertEqual(stale, [], 'EXEMPT names functions that no longer exist: ' + ', '.join(stale))

    def test_every_exemption_gives_a_real_reason(self):
        for key, reason in EXEMPT.items():
            self.assertGreater(len(reason), 20, key)

    def test_the_operations_that_matter_are_guarded_by_name(self):
        expected = {('recipe_engine.py', 'apply'): 'configure_graphics',
                    ('vc_component.py', 'install'): 'install_vc_runtime',
                    ('archive_component.py', 'install'): 'prepare_archive_tools',
                    ('helper_component.py', 'install'): 'install_helper',
                    ('recipes.py', 'configure_graphics'): 'configure_graphics',
                    ('standalone.py', 'work'): 'import_module'}
        found = {(name, node.name): guarded_operations(node) for name, node in functions()}
        for key, operation in expected.items():
            self.assertIn(operation, found.get(key, []), f'{key[0]}:{key[1]} must guard {operation}')

    def test_every_guarded_operation_is_a_classified_one(self):
        known = licensing.READ_ONLY | licensing.IN_PLACE | licensing.IDENTITY_CHANGING
        for name, node in functions():
            for operation in guarded_operations(node):
                self.assertIn(operation, known, f'{name} guards an unknown operation')


class GuardBehaviourTests(unittest.TestCase):
    """The guard must actually refuse, not merely be called."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = Path(self.tmp.name) / 'env'
        (self.env / 'prefix/drive_c').mkdir(parents=True)
        self.write('0f1e2d3c')
        licensing.protect(self.env, [{'name': 'ExampleSynth', 'recovery': 'limited-activations',
                                      'activations_remaining': 2}])
        self.write('999e2d3c')  # Something changed the environment after activation.

    def write(self, guid):
        (self.env / 'prefix/system.reg').write_text(
            'WINE REGISTRY Version 2\n\n[Software\\\\Microsoft\\\\Cryptography] 1\n'
            '"MachineGuid"="%s-f41a-4974-b30e-74c830008ade"\n' % guid)

    def test_vc_installation_stops_before_downloading_anything(self):
        with patch('plugg.artifacts.fetch', side_effect=AssertionError('downloaded')):
            with self.assertRaises(licensing.LicensedEnvironmentError):
                vc_component.install(None, self.env, 'launcher', [{'sha256': 'a' * 64}],
                                     lambda _: None, lambda: None)

    def test_archive_preparation_stops_before_downloading_anything(self):
        with patch('plugg.artifacts.fetch', side_effect=AssertionError('downloaded')):
            with self.assertRaises(licensing.LicensedEnvironmentError):
                archive_component.install(None, self.env / 'prefix', [{'sha256': 'a' * 64}],
                                          lambda _: None, lambda: None)

    def test_helper_installation_stops_before_running_the_installer(self):
        with patch('plugg.core.run_process', side_effect=AssertionError('ran installer')):
            with self.assertRaises(licensing.LicensedEnvironmentError):
                helper_component.install({'installer': '/none'}, self.env / 'prefix', 'launcher',
                                         {'name': 'x', 'executable': 'x/x.exe', 'archive_tools': False},
                                         [], lambda: None)

    def test_the_documented_graphics_entry_point_refuses_too(self):
        from plugg import recipes
        with self.assertRaises(licensing.LicensedEnvironmentError):
            recipes.configure_graphics(self.env, {'schema': 1, 'default': 'dxvk', 'plugins': {}})

    def test_the_guard_refuses_a_path_that_is_not_the_environment(self):
        # An off-by-one in a caller must fail rather than silently find no
        # record and allow everything.
        for wrong in (self.env / 'prefix', self.env / 'prefix/drive_c', self.env.parent):
            with self.assertRaises(core.HostError, msg=str(wrong)):
                licensing.guard(wrong, 'recreate_prefix')

    def test_an_acknowledgement_authorizes_one_attempt_only(self):
        licensing.acknowledge(self.env, 'recreate_prefix',
                              licensing.CONFIRMATION['limited-activations'])
        self.assertTrue(licensing.guard(self.env, 'recreate_prefix')['acknowledged'])
        with self.assertRaises(licensing.LicensedEnvironmentError):
            licensing.guard(self.env, 'recreate_prefix')


if __name__ == '__main__':
    unittest.main()
