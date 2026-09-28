"""The library list must leave no environment in a place nobody looks.

Every environment is either a vendor row or a line under "needs attention",
and space in the library folder that nothing explains is flagged too. These
check the rules that decide which is which, without a display.
"""
import unittest

from plugg import library_view as view


def record(**changes):
    base = {'id': 'a1b2c3d4e5', 'name': None, 'vendor': 'Kilohearts', 'recipe': 'installer',
            'plugins': ['kHs Gain'], 'retired': [], 'runtime': 'UMU-Proton-10.0-4', 'path': '/x',
            'jobs': [{'id': 'j', 'name': 'Setup.exe'}], 'in_use': True, 'orphaned': False,
            'dangling': False, 'protected': False, 'severity': None, 'products': [],
            'licensing_group': None, 'plugin_vendors': ['Kilohearts']}
    base.update(changes)
    return base


class LeftoverTests(unittest.TestCase):
    def reason(self, helpers=None, **changes):
        return view.LibraryView.leftover(record(**changes), helpers)

    def test_a_vendor_with_plug_ins_is_a_vendor(self):
        self.assertIsNone(self.reason())

    def test_a_vendor_still_being_set_up_is_a_vendor(self):
        self.assertIsNone(self.reason(helpers=[{'job': 'j'}], plugins=[]))

    def test_leftovers_say_why(self):
        self.assertIn('No installation', self.reason(orphaned=True, jobs=[], plugins=[]))
        self.assertIn('archived', self.reason(in_use=False))
        self.assertIn('Nothing in your DAW', self.reason(plugins=[]))
        self.assertIn('gone', self.reason(dangling=True))

    def test_a_protected_environment_is_never_called_a_leftover(self):
        self.assertIsNone(self.reason(protected=True, orphaned=True, plugins=[], in_use=False))

    def test_an_unreadable_licensing_note_is_not_a_leftover_either(self):
        # protected None means the note could not be read, which everywhere else
        # is treated as holding activations.
        self.assertIsNone(self.reason(protected=None, plugins=[], orphaned=True, jobs=[]))


class UrgentTests(unittest.TestCase):
    def test_a_leftover_is_not_urgent(self):
        # Cleaning up is housekeeping; it never goes above the vendors.
        self.assertIsNone(view.LibraryView.urgent(record(orphaned=True, plugins=[], jobs=[]), None))

    def test_identity_drift_on_a_protected_environment_is(self):
        self.assertIn('machine identity',
                      view.LibraryView.urgent(record(protected=True, matches_recorded_identity=False), None))

    def test_a_protected_environment_whose_identity_matches_is_not(self):
        self.assertIsNone(view.LibraryView.urgent(record(protected=True, matches_recorded_identity=True), None))

    def test_a_helper_status_is_not(self):
        # "12 plug-ins waiting for activation" is news for the vendor's row, not an alarm.
        self.assertIsNone(view.LibraryView.urgent(record(), [{'needs_attention': True, 'message': 'Waiting'}]))


class NamingTests(unittest.TestCase):
    def test_an_adopted_helper_loses_its_version(self):
        self.assertEqual(view.app_title('Melodyne.5.4.2.006'), 'Melodyne')
        self.assertEqual(view.app_title('XLN Online Installer'), 'XLN Online Installer')

    def test_company_forms_do_not_split_a_vendor(self):
        self.assertEqual(view.vendor_name('Universal Audio, Inc.'), 'Universal Audio')
        self.assertEqual(view.vendor_name('Native Instruments GmbH'), 'Native Instruments')
        self.assertEqual(view.vendor_name('Klevgrand'), 'Klevgrand')
        self.assertEqual(view.vendor_name(''), 'Unknown vendor')

    def test_one_vendor_spelled_two_ways_is_one_row(self):
        import json
        found = view.plugins_by_vendor([
            {'env_id': 'e', 'name': 'A', 'metadata': json.dumps({'classes': [{'name': 'A', 'vendor': 'Softube'}]})},
            {'env_id': 'e', 'name': 'B', 'metadata': json.dumps({'classes': [{'name': 'B', 'vendor': 'SOFTUBE AB'}]})}])
        self.assertEqual(found, {'e': {'Softube': ['A', 'B']}})


class UnlistedTests(unittest.TestCase):
    def test_known_parts_are_never_flagged(self):
        big = 10 * 1024 ** 3
        self.assertEqual(view.unlisted({name: big for name in view.PARTS}), [])

    def test_a_large_unknown_folder_is_flagged_and_a_small_one_is_not(self):
        found = view.unlisted({'old-experiment': view.UNACCOUNTED_THRESHOLD, 'ui.json': 200})
        self.assertEqual([name for name, _ in found], ['old-experiment'])


class NamesTests(unittest.TestCase):
    def test_rows_that_would_read_the_same_are_told_apart(self):
        names = view.display_names([
            record(id='1', recipe='standalone-vst3', vendor=None, plugins=['Editor'], plugin_vendors=['Tests']),
            record(id='2', recipe='standalone-vst3', vendor=None, plugins=['Gain'], plugin_vendors=['Tests'])])
        self.assertEqual(names, {'1': 'Tests · Editor', '2': 'Tests · Gain'})

    def test_a_given_name_wins(self):
        self.assertEqual(view.display_names([record(name='My synths')]), {'a1b2c3d4e5': 'My synths'})


if __name__ == '__main__':
    unittest.main()
