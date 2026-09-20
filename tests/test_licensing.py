"""Licensing guardrails: no operation may silently cost the user an activation."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plugg import licensing  # noqa: E402

REGISTRY = '''WINE REGISTRY Version 2
;; All keys relative to \\\\Machine

[Software\\\\Microsoft\\\\Cryptography] 1774855987
#time=1dcc017742159a6
"MachineGuid"="0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"

[Software\\\\Microsoft\\\\Windows NT\\\\CurrentVersion] 1774855987
"ProductId"="00330-50000-00000-AAOEM"
"InstallDate"=dword:4be5019a
"DigitalProductId"=hex:a4,00,00,00,03,00,00,00,30,30,33,33,30,2d,35,30,30,30,\\
  30,2d,30,30,30,30,30,2d,41,41,4f,45,4d

[System\\\\ControlSet001\\\\Control\\\\ComputerName\\\\ComputerName] 1789112715
"ComputerName"="EXAMPLE-PC"

[System\\\\ControlSet001\\\\Services\\\\Tcpip\\\\Parameters] 1789112715
"Hostname"="example-pc"
'''


class LicensingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = Path(self.tmp.name) / 'environments' / 'one'
        (self.env / 'prefix').mkdir(parents=True)
        self.registry = self.env / 'prefix/system.reg'
        self.registry.write_text(REGISTRY)
        (self.env / 'prefix/version').write_text('UMU-Proton-10.0-4\n')

    def protect(self, recovery='deactivate-first', **extra):
        return licensing.protect(self.env, [{'name': 'Example Suite', 'recovery': recovery, **extra}])

    # Identity observation

    def test_identity_reads_declared_values_without_storing_them(self):
        observed = licensing.identity(self.env)
        self.assertEqual(observed['issues'], [])
        self.assertTrue(observed['values']['machine_guid']['present'])
        self.assertTrue(observed['values']['computer_name']['present'])
        self.assertTrue(observed['values']['windows_digital_product_id']['present'])
        # No identity value may appear in the record in the clear.
        serialized = json.dumps(observed)
        for secret in ('0f1e2d3c', 'EXAMPLE-PC', 'example-pc', '00330-50000'):
            self.assertNotIn(secret, serialized)

    def test_absent_values_are_recorded_as_absent_not_invented(self):
        observed = licensing.identity(self.env)
        self.assertEqual(observed['values']['mounted_device_c'], {'present': False, 'digest': None})

    def test_unreadable_registry_is_an_issue_and_never_a_match(self):
        self.registry.unlink()
        self.protect()
        state = licensing.verify(self.env)
        self.assertFalse(state['matches'])
        self.assertTrue(state['observed']['issues'])

    def test_same_value_under_a_different_label_has_a_different_digest(self):
        values = licensing.identity(self.env)['values']
        self.assertNotEqual(values['computer_name']['digest'], values['tcpip_hostname']['digest'])

    # Protection record

    def test_protect_requires_a_managed_environment(self):
        with self.assertRaises(Exception):
            licensing.protect(Path(self.tmp.name) / 'missing', [{'name': 'x', 'recovery': 'unknown'}])

    def test_unknown_recovery_is_as_strict_as_limited_activations(self):
        self.assertEqual(licensing.CONFIRMATION['unknown'], licensing.CONFIRMATION['limited-activations'])

    def test_severity_is_the_strictest_recorded_product(self):
        record = licensing.protect(self.env, [
            {'name': 'Reusable', 'recovery': 'reactivatable'},
            {'name': 'ExampleSynth', 'recovery': 'limited-activations', 'activations_remaining': 3},
            {'name': 'Bound', 'recovery': 'deactivate-first'}])
        self.assertEqual(licensing.severity(record['products']), 'limited-activations')

    def test_products_merge_by_name_and_keep_first_protection_time(self):
        first = self.protect()
        time.sleep(0.01)
        second = licensing.protect(self.env, [{'name': 'ExampleSynth', 'recovery': 'limited-activations'}])
        self.assertEqual([item['name'] for item in second['products']], ['Example Suite', 'ExampleSynth'])
        self.assertEqual(second['protected_since'], first['protected_since'])

    def test_product_notes_may_not_carry_licence_material(self):
        with self.assertRaises(ValueError):
            licensing.protect(self.env, [{'name': 'x', 'recovery': 'unknown', 'note': 'k' * 513}])
        with self.assertRaises(ValueError):
            licensing.protect(self.env, [{'name': 'k' * 121, 'recovery': 'unknown'}])

    def test_duplicate_and_malformed_products_are_rejected(self):
        for products in ([], [{'name': 'a', 'recovery': 'nope'}],
                         [{'name': 'a', 'recovery': 'unknown'}, {'name': 'A', 'recovery': 'unknown'}],
                         [{'name': 'a', 'recovery': 'unknown', 'activations_remaining': -1}],
                         [{'name': 'a', 'recovery': 'unknown', 'surprise': 1}]):
            with self.assertRaises(ValueError):
                licensing.validate_products(products)

    # The guard

    def test_unprotected_environments_are_never_blocked(self):
        for operation in ('configure_graphics', 'recreate_prefix'):
            self.assertTrue(licensing.guard(self.env, operation)['allowed'])

    def test_unknown_operations_fail_closed(self):
        self.protect()
        with self.assertRaises(ValueError):
            licensing.guard(self.env, 'do_something_new')

    def test_read_only_operations_are_allowed_on_protected_environments(self):
        self.protect()
        self.assertTrue(licensing.guard(self.env, 'scan')['allowed'])

    def test_identity_changing_operations_are_refused(self):
        self.protect()
        with self.assertRaises(licensing.LicensedEnvironmentError) as caught:
            licensing.guard(self.env, 'recreate_prefix')
        self.assertIn('Deactivate first', str(caught.exception))

    def test_limited_activation_refusal_names_the_unrecoverable_product(self):
        licensing.protect(self.env, [{'name': 'ExampleSynth', 'recovery': 'limited-activations',
                                      'activations_remaining': 3}])
        with self.assertRaises(licensing.LicensedEnvironmentError) as caught:
            licensing.guard(self.env, 'replace_runtime')
        message = str(caught.exception)
        self.assertIn('ExampleSynth (3 activations left)', message)
        self.assertIn('cannot be recovered', message.casefold())

    def test_in_place_operations_are_allowed_while_the_identity_matches(self):
        self.protect()
        self.assertTrue(licensing.guard(self.env, 'configure_graphics')['allowed'])

    def test_in_place_operations_stop_once_the_identity_has_drifted(self):
        self.protect()
        self.registry.write_text(REGISTRY.replace('0f1e2d3c', '569dd19a'))
        with self.assertRaises(licensing.LicensedEnvironmentError) as caught:
            licensing.guard(self.env, 'configure_graphics')
        self.assertIn('machine_guid', str(caught.exception))

    def test_moving_the_prefix_is_reported_without_blocking_in_place_work(self):
        self.protect()
        record = json.loads((self.env / licensing.RECORD).read_text())
        record['identity']['location']['prefix'] = '/somewhere/else/prefix'
        (self.env / licensing.RECORD).write_text(json.dumps(record))
        state = licensing.verify(self.env)
        self.assertEqual([item['value'] for item in state['location_drift']], ['prefix'])
        self.assertTrue(licensing.guard(self.env, 'configure_graphics')['allowed'])

    # Acknowledgement

    def test_acknowledgement_requires_the_exact_confirmation(self):
        self.protect()
        with self.assertRaises(licensing.LicensedEnvironmentError):
            licensing.acknowledge(self.env, 'recreate_prefix', 'yes')
        with self.assertRaises(licensing.LicensedEnvironmentError):
            licensing.acknowledge(self.env, 'recreate_prefix',
                                  licensing.CONFIRMATION['limited-activations'])

    def test_acknowledgement_unblocks_only_its_own_operation(self):
        self.protect()
        licensing.acknowledge(self.env, 'recreate_prefix', licensing.CONFIRMATION['deactivate-first'])
        self.assertTrue(licensing.guard(self.env, 'recreate_prefix')['acknowledged'])
        with self.assertRaises(licensing.LicensedEnvironmentError):
            licensing.guard(self.env, 'replace_runtime')

    def test_acknowledgement_is_single_use(self):
        self.protect()
        licensing.acknowledge(self.env, 'recreate_prefix', licensing.CONFIRMATION['deactivate-first'])
        licensing.consume(self.env, 'recreate_prefix')
        with self.assertRaises(licensing.LicensedEnvironmentError):
            licensing.guard(self.env, 'recreate_prefix')

    def test_acknowledgement_expires(self):
        self.protect()
        licensing.acknowledge(self.env, 'recreate_prefix', licensing.CONFIRMATION['deactivate-first'])
        record = json.loads((self.env / licensing.RECORD).read_text())
        record['acknowledgement']['expires'] = time.time() - 1
        (self.env / licensing.RECORD).write_text(json.dumps(record))
        with self.assertRaises(licensing.LicensedEnvironmentError):
            licensing.guard(self.env, 'recreate_prefix')

    def test_protection_cannot_be_removed_without_the_confirmation(self):
        self.protect(recovery='limited-activations')
        with self.assertRaises(licensing.LicensedEnvironmentError):
            licensing.unprotect(self.env, 'please')
        licensing.unprotect(self.env, licensing.CONFIRMATION['limited-activations'])
        self.assertTrue(licensing.guard(self.env, 'recreate_prefix')['allowed'])

    def test_damaged_record_is_reported_rather_than_ignored(self):
        self.protect()
        (self.env / licensing.RECORD).write_text('{ not json')
        with self.assertRaises(Exception):
            licensing.guard(self.env, 'configure_graphics')

    # Recovery points

    def test_backup_copies_identity_files_and_verifies_them(self):
        self.protect()
        manifest = licensing.backup(self.env, label='test')
        names = {item['name'] for item in manifest['files']}
        self.assertEqual(names, {'system.reg', 'version'})
        self.assertEqual([item['id'] for item in licensing.backups(self.env)], [manifest_id(manifest, self.env)])

    def test_restore_returns_the_recorded_identity(self):
        self.protect()
        manifest = licensing.backup(self.env)
        identifier = manifest_id(manifest, self.env)
        before = licensing.identity(self.env)['fingerprint']
        self.registry.write_text(REGISTRY.replace('0f1e2d3c', '999dd19a'))
        self.assertNotEqual(licensing.identity(self.env)['fingerprint'], before)
        licensing.restore(self.env, identifier, licensing.CONFIRMATION['deactivate-first'])
        self.assertEqual(licensing.identity(self.env)['fingerprint'], before)

    def test_restore_refuses_without_the_confirmation(self):
        self.protect()
        manifest = licensing.backup(self.env)
        with self.assertRaises(licensing.LicensedEnvironmentError):
            licensing.restore(self.env, manifest_id(manifest, self.env), 'ok')

    def test_restore_takes_a_recovery_point_of_the_current_state_first(self):
        self.protect()
        first = manifest_id(licensing.backup(self.env), self.env)
        self.registry.write_text(REGISTRY.replace('0f1e2d3c', '999dd19a'))
        changed = licensing.identity(self.env)['fingerprint']
        licensing.restore(self.env, first, licensing.CONFIRMATION['deactivate-first'])
        rollback = [item for item in licensing.backups(self.env) if item['id'].endswith('before-restore')]
        self.assertEqual(len(rollback), 1)
        self.assertEqual(rollback[0]['identity']['fingerprint'], changed)

    def test_status_reports_products_drift_and_recovery_points(self):
        licensing.protect(self.env, [{'name': 'ExampleSynth', 'recovery': 'limited-activations',
                                      'activations_remaining': 2, 'note': 'five validations total'}])
        licensing.backup(self.env)
        report = licensing.status(self.env)
        self.assertTrue(report['protected'])
        self.assertEqual(report['severity'], 'limited-activations')
        self.assertTrue(report['matches_recorded_identity'])
        self.assertEqual(len(report['recovery_points']), 1)


def manifest_id(manifest, environment):
    return next(path.name for path in sorted((Path(environment) / licensing.BACKUPS).iterdir())
                if json.loads((path / 'manifest.json').read_text())['created'] == manifest['created']
                and not path.name.endswith('before-restore'))


if __name__ == '__main__':
    unittest.main()


class KeyedIdentityTests(unittest.TestCase):
    """The record alone must not reveal the machine identifiers."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = Path(self.tmp.name) / 'env'
        (self.env / 'prefix').mkdir(parents=True)
        (self.env / 'prefix/system.reg').write_text(REGISTRY)

    def test_protect_creates_a_private_key_outside_the_record(self):
        licensing.protect(self.env, [{'name': 'x', 'recovery': 'deactivate-first'}])
        key = self.env / licensing.KEY
        self.assertTrue(key.is_file())
        self.assertEqual(oct(key.stat().st_mode & 0o777), '0o600')
        self.assertNotIn(key.read_text().strip(), (self.env / licensing.RECORD).read_text())

    def test_two_environments_with_the_same_identity_get_different_digests(self):
        other = Path(self.tmp.name) / 'other'
        (other / 'prefix').mkdir(parents=True)
        (other / 'prefix/system.reg').write_text(REGISTRY)
        first = licensing.protect(self.env, [{'name': 'x', 'recovery': 'deactivate-first'}])
        second = licensing.protect(other, [{'name': 'x', 'recovery': 'deactivate-first'}])
        self.assertNotEqual(first['identity']['fingerprint'], second['identity']['fingerprint'])

    def test_a_guessed_value_cannot_be_confirmed_without_the_key(self):
        import hashlib
        licensing.protect(self.env, [{'name': 'x', 'recovery': 'deactivate-first'}])
        record = json.loads((self.env / licensing.RECORD).read_text())
        digest = record['identity']['values']['computer_name']['digest']
        guess = hashlib.sha256(b'plugg/licensing/1\x00computer_name\x00EXAMPLE-PC').hexdigest()
        self.assertNotEqual(digest, guess)

    def test_losing_the_key_is_a_mismatch_not_a_match(self):
        licensing.protect(self.env, [{'name': 'x', 'recovery': 'deactivate-first'}])
        (self.env / licensing.KEY).unlink()
        state = licensing.verify(self.env)
        self.assertFalse(state['matches'])
        self.assertTrue(any(licensing.KEY in issue for issue in state['observed']['issues']))
        with self.assertRaises(licensing.LicensedEnvironmentError):
            licensing.guard(self.env, 'configure_graphics')

    def test_a_recovery_point_manifest_carries_no_identity_digests(self):
        licensing.protect(self.env, [{'name': 'ExampleSynth', 'recovery': 'limited-activations'}])
        manifest = licensing.backup(self.env)
        text = json.dumps(manifest)
        self.assertNotIn('digest', text)
        self.assertNotIn((self.env / licensing.KEY).read_text().strip(), text)
        self.assertIn('ExampleSynth', manifest['products'])


class MachineIdentityTests(unittest.TestCase):
    """One computer must present as one machine, not one machine per prefix.

    Wine generates a fresh MachineGuid for every prefix it creates. Licences are
    sold per machine, so left alone this spends a person's machine allowance on
    environments that are all one desk.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.library = Path(self.tmp.name) / 'library'
        self.env = self.library / 'environments' / 'one'
        (self.env / 'prefix').mkdir(parents=True)
        self.registry = self.env / 'prefix/system.reg'
        self.registry.write_text(REGISTRY)

    def test_the_host_identity_is_stable_and_shaped_like_a_guid(self):
        first = licensing.host_machine_guid(self.library)
        self.assertTrue(licensing.GUID.fullmatch(first))
        self.assertEqual(first, licensing.host_machine_guid(self.library))

    def test_a_computer_without_a_machine_id_gets_one_per_library(self):
        from unittest.mock import patch
        with patch.object(licensing, 'MACHINE_ID_SOURCES', ()):
            first = licensing.host_machine_guid(self.library)
            self.assertTrue(licensing.GUID.fullmatch(first))
            self.assertEqual(first, licensing.host_machine_guid(self.library))
            other = Path(self.tmp.name) / 'other-library'
            self.assertNotEqual(first, licensing.host_machine_guid(other))

    def test_the_host_identity_does_not_expose_the_host_identifier(self):
        # Derived by hashing, so the machine-id itself is never handed to
        # Windows software, and two computers cannot collide by accident.
        for source in licensing.MACHINE_ID_SOURCES:
            try:
                material = Path(source).read_text().strip()
            except OSError:
                continue
            if material:
                self.assertNotIn(material[:8], licensing.host_machine_guid(self.library))
                return
        self.skipTest('this machine has no machine-id to derive from')

    def test_the_current_identity_is_read_from_the_prefix(self):
        self.assertEqual(licensing.current_machine_guid(self.env),
                         '0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0')

    def test_an_environment_with_its_own_invented_identity_is_reported(self):
        self.assertFalse(licensing.is_this_computer(self.env))

    def test_an_environment_carrying_this_computer_is_reported(self):
        wanted = licensing.host_machine_guid(self.library)
        self.registry.write_text(REGISTRY.replace('0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0', wanted))
        self.assertTrue(licensing.is_this_computer(self.env))

    def test_adopting_sets_the_identity_through_wine_and_verifies_it(self):
        from unittest.mock import patch
        wanted = licensing.host_machine_guid(self.library)
        seen = []

        def run(command, *args, **kwargs):
            seen.append(command)
            self.registry.write_text(REGISTRY.replace('0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0', wanted))
            return 0

        with patch('plugg.core.run_process', side_effect=run):
            result = licensing.adopt_machine_identity(self.env, ['launcher'], {})
        self.assertTrue(result['changed'])
        self.assertIn('MachineGuid', seen[0])
        self.assertIn(wanted, seen[0])
        self.assertTrue(licensing.is_this_computer(self.env))

    def test_adopting_is_skipped_when_the_environment_already_matches(self):
        from unittest.mock import patch
        wanted = licensing.host_machine_guid(self.library)
        self.registry.write_text(REGISTRY.replace('0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0', wanted))
        with patch('plugg.core.run_process', side_effect=AssertionError('ran wine')):
            self.assertFalse(licensing.adopt_machine_identity(self.env, ['launcher'], {})['changed'])

    def test_a_refusal_to_take_the_identity_is_an_error_not_a_shrug(self):
        from unittest.mock import patch
        with patch('plugg.core.run_process', return_value=0):
            with self.assertRaises(Exception):
                licensing.adopt_machine_identity(self.env, ['launcher'], {})

    def test_a_failing_launcher_explains_itself(self):
        from unittest.mock import patch

        def run(command, env, log, *args, **kwargs):
            log.write_text('INFO: umu-launcher\nERROR: something specific went wrong\n')
            return 1

        with patch('plugg.core.run_process', side_effect=run):
            with self.assertRaisesRegex(Exception, 'something specific went wrong'):
                licensing.adopt_machine_identity(self.env, ['launcher'], {})
        self.assertTrue((self.env / 'machine-identity.log').is_file())

    def test_an_uninitialized_environment_is_unverifiable_rather_than_failed(self):
        from unittest.mock import patch
        self.registry.unlink()
        with patch('plugg.core.run_process', return_value=0):
            result = licensing.adopt_machine_identity(self.env, ['launcher'], {})
        self.assertIsNone(result['changed'])
        self.assertIsNone(licensing.is_this_computer(self.env))

    def test_an_activated_environment_is_never_re_identified(self):
        licensing.protect(self.env, [{'name': 'Bound', 'recovery': 'deactivate-first'}])
        from unittest.mock import patch
        with patch('plugg.core.run_process', side_effect=AssertionError('ran wine')):
            with self.assertRaises(licensing.LicensedEnvironmentError):
                licensing.adopt_machine_identity(self.env, ['launcher'], {})

    def test_status_says_whether_an_environment_is_this_computer(self):
        licensing.protect(self.env, [{'name': 'Bound', 'recovery': 'deactivate-first'}])
        self.assertFalse(licensing.status(self.env)['machine_identity_is_this_computer'])
