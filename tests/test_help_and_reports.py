"""Help people find answers, and make a good bug report easy but not a lazy one.

Plugg has no helpdesk. These check the parts that carry that: the vendor
notes installers are matched against, what is already known about a file
when it is added, and a report that will not go anywhere without the answers
that make it useful, and that carries nothing private.
"""
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import tempfile
import unittest

from plugg import help_content, known_fixes, report


class VendorNoteTests(unittest.TestCase):
    def test_a_company_form_still_finds_the_vendor(self):
        self.assertEqual(help_content.vendor_note('Klevgrand Produkter')[0], 'Klevgrand')
        self.assertEqual(help_content.vendor_note('Native Instruments GmbH')[0], 'Native Instruments')

    def test_a_different_vendor_finds_nothing(self):
        self.assertIsNone(help_content.vendor_note('Kilohearts'))
        self.assertIsNone(help_content.vendor_note(''))

    def test_every_answer_is_a_question_and_an_answer(self):
        for group, entries in help_content.FAQ:
            self.assertTrue(entries, group)
            for question, answer in entries:
                self.assertTrue(question and len(answer) > 40, question)


def lead(name, vendor, kind='windows', sha256=None, setup=None):
    return {'vendor': vendor, 'source': 'cabinet', 'file': vendor.casefold() + '.toml',
            'source_url': 'https://example.invalid', 'source_commit': 'c' * 40, 'source_path': 'data/' + vendor,
            'products': [{'id': name.casefold(), 'name': name, 'kind': kind, 'developer': vendor,
                          'download': {'sha256': sha256} if sha256 else {}, 'cabinet': setup or {}}]}


class KnownFixesTests(unittest.TestCase):
    FILES = [lead('Example Synth', 'Example Audio', sha256='a' * 64, setup={'dxvk': True, 'winetricks': ['vcrun2019']}),
             lead('Example Synth', 'Example Audio', kind='native'),
             lead('Other Thing', 'Somebody Else')]

    def test_an_exact_file_says_what_ran_elsewhere_and_that_it_is_a_hint(self):
        found = known_fixes.lookup('Example Synth Setup.exe', 'a' * 64, vendor='Example Audio', files=self.FILES)
        lead_texts = [f['text'] for f in found if f['kind'] == 'lead']
        self.assertTrue(any('DXVK graphics' in t and 'vcrun2019' in t for t in lead_texts), lead_texts)

    def test_a_native_version_is_pointed_out(self):
        found = known_fixes.lookup('Example Synth Setup.exe', 'b' * 64, vendor='Example Audio', files=self.FILES)
        self.assertTrue(any(f['kind'] == 'native' for f in found))
        self.assertEqual(known_fixes.summary(found, limit=1)[0], found[[f['kind'] for f in found].index('native')]['text'])

    def test_an_unrelated_file_learns_nothing(self):
        self.assertEqual(known_fixes.lookup('Unrelated.exe', 'c' * 64, vendor='Nobody', files=self.FILES), [])

    def test_hints_use_plugg_words(self):
        self.assertEqual(known_fixes.hints({'dxvk': True, 'virtual_desktop': '1024x768'}),
                         ['DXVK graphics', 'a Wine virtual desktop'])


class ReportTests(unittest.TestCase):
    ANSWERS = {'what': 'The row stays amber after activating in iLok.',
               'steps': '1. Activate soothe in iLok\n2. Close iLok License Manager',
               'frequency': 'Every time', 'daw': 'Bitwig Studio 5.3'}

    def test_a_report_without_the_answers_goes_nowhere(self):
        gaps = report.missing('bug', {})
        self.assertIn('what happened and what you expected', gaps)
        self.assertIn('how often it happens', gaps)
        self.assertEqual(report.missing('bug', {**self.ANSWERS, 'what': 'broken'}),
                         ['what happened and what you expected'])
        self.assertEqual(report.missing('bug', self.ANSWERS), [])

    def test_a_finding_needs_to_say_how_far_it_got(self):
        answers = {'product': 'Example Synth 1.2.3', 'steps': 'Drop the installer, open in Bitwig', 'daw': 'Bitwig 5'}
        self.assertIn('how far it got at each stage', report.missing('compatibility', answers))
        answers['stages'] = {'Installation': 'yes', 'Audio': 'no sound'}
        self.assertEqual(report.missing('compatibility', answers), [])

    def test_the_form_is_filled_by_its_own_field_ids(self):
        filled = report.fields('bug', self.ANSWERS, 'Plugg: x')
        self.assertEqual(set(filled), {'what', 'steps', 'frequency', 'version', 'daw', 'setup'})
        query = parse_qs(urlparse(report.issue_url('bug', filled)).query)
        self.assertEqual(query['template'], ['bug.yml'])
        self.assertEqual(query['frequency'], ['Every time'])

    def test_nothing_carries_the_user_name(self):
        home = str(Path.home())
        filled = report.fields('bug', {**self.ANSWERS, 'what': 'Crashed in ' + home + '/Music/song.bwproject'}, '')
        self.assertNotIn(home, filled['what'])
        self.assertIn('~/Music/song.bwproject', filled['what'])

    def test_the_summary_says_protected_but_never_what_the_licences_are(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SimpleNamespace(root=Path(tmp), bridge=lambda: (_ for _ in ()).throw(OSError('none')))
            record = {'id': 'e', 'name': None, 'vendor': 'Klevgrand', 'recipe': 'klevgrand', 'plugins': ['Skaka'],
                      'runtime': 'UMU-Proton-10.0-4', 'protected': True, 'severity': 'deactivate-first',
                      'products': ['Skaka'], 'recorded': [{'name': 'Skaka', 'serial': 'SECRET-123'}],
                      'licensing_group': None, 'jobs': [], 'plugin_vendors': []}
            summary = report.setup_summary(store, [record], [], [])
        self.assertIn('protected (deactivate-first)', summary)
        self.assertNotIn('SECRET-123', summary)

    def test_every_field_stays_short_enough_for_an_address(self):
        filled = report.fields('bug', {**self.ANSWERS, 'what': 'x' * 10000}, 'y' * 10000)
        self.assertTrue(all(len(v) <= report.FIELD_LIMIT for v in filled.values()))


if __name__ == '__main__':
    unittest.main()
