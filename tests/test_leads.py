"""Recipe leads are attributed research: loadable, credited, and never executable."""
import contextlib
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from plugg import leads, recipe_engine as engine, recipe_scaffold
from plugg.__main__ import main
from test_core import fake_pe

CABINET = leads.DIRECTORY / 'cabinet'


class BundledLeadTests(unittest.TestCase):
    def test_every_bundled_lead_loads(self):
        files = leads.load_all()
        cabinet = [data for data in files if data['source'] == 'cabinet']
        self.assertEqual(len(cabinet), 26)
        self.assertEqual(sum(len(data['products']) for data in cabinet), 51)

    def test_every_file_credits_its_source_and_commit(self):
        for path in CABINET.glob('*.toml'):
            text = path.read_text()
            self.assertTrue(text.startswith('# Recipe leads imported from Cabinet, https://github.com/Mark12870/cabinet'),
                            path.name)
            data = leads.load_file(path)
            self.assertEqual(data['licence'], 'GPL-3.0-or-later')
            self.assertRegex(data['source_commit'], r'^[0-9a-f]{40}$')
            self.assertEqual(data['source_path'], 'data/library/' + path.stem)

    def test_every_named_script_is_included(self):
        for data in leads.load_all():
            self.assertEqual(sorted(data.get('reference_scripts', {})), leads.product_scripts(data), data['file'])

    def test_no_machine_specific_data_was_carried_over(self):
        mac = re.compile(r'\b[0-9a-f]{2}(?:[-:][0-9a-f]{2}){5}\b', re.I)
        for path in CABINET.glob('*.toml'):
            text = path.read_text()
            self.assertIsNone(mac.search(text), path.name)
            self.assertNotIn('/home/', text, path.name)

    def test_leads_are_not_part_of_the_recipe_catalogue(self):
        records = engine.catalogue(engine.default_directories())
        self.assertFalse(any(reference.startswith('cabinet') for reference in records))

    def test_held_back_entries_say_why(self):
        held = [product for product in leads.products() if product['held_back']]
        self.assertEqual({product['vendor'] for product in held}, {'Spitfire Audio', 'Splice'})
        self.assertTrue(all(product['held_back_reason'] for product in held))


class LookupTests(unittest.TestCase):
    def test_vendor_match_is_on_whole_words(self):
        self.assertEqual({product['vendor'] for product in leads.for_vendor('TAL Software')}, {'TAL Software'})
        self.assertEqual(leads.for_vendor('TA'), [])
        self.assertEqual(leads.for_vendor(''), [])

    def test_native_builds_are_recognised(self):
        self.assertTrue(leads.native(leads.for_vendor('u-he')))
        self.assertEqual(leads.native(leads.for_vendor('Valhalla DSP')), [])

    def test_our_own_notes_correct_the_import_without_touching_its_files(self):
        serum = [product for product in leads.for_vendor('Xfer Records') if product['name'] == 'Serum 2']
        self.assertEqual({product['source']: product['kind'] for product in serum},
                         {'cabinet': 'windows', 'plugg': 'native'})
        self.assertIn("Plugg's own note", leads.attribution(leads.native(serum)[0]))

    def test_support_files_the_scripts_read_are_included(self):
        celemony = leads.load_file(CABINET / 'celemony.toml')
        self.assertIn('[InstallShield Silent]', celemony['reference_files']['melodyne.iss'])

    def test_download_hash_finds_its_lead(self):
        found = leads.for_file('67e0cedbed9e680b11dfb582618dd257e2dba8b8d10189d59811e4c10414911d')
        self.assertEqual([product['id'] for product in found], ['valhalla-supermassive'])

    def test_search_needs_every_word(self):
        self.assertEqual([product['id'] for product in leads.search('valhalla super')], ['valhalla-supermassive'])

    def test_overlap_with_our_recipes_is_reported(self):
        records = engine.catalogue(engine.default_directories())
        product = leads.search('klevgrand helper')[0]
        self.assertEqual(leads.recipes_for(product, records), ['plugg.klevgrand@1'])
        self.assertIn('plugg.klevgrand@1', leads.render(product, leads.recipes_for(product, records)))


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'lead.toml'

    def load(self, extra='', product=''):
        self.path.write_text('schema = 1\nsource = "x"\nsource_url = "https://example.invalid"\n'
                             'source_commit = "' + '0' * 40 + '"\nlicence = "GPL-3.0-or-later"\nvendor = "V"\n' + extra
                             + '[[products]]\nid = "p"\nname = "P"\nkind = "windows"\n' + product)
        return leads.load_file(self.path)

    def test_a_minimal_lead_loads(self):
        self.assertEqual(self.load()['vendor'], 'V')

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(leads.LeadError):
            self.load(product='run = "rm -rf"\n')
        with self.assertRaises(leads.LeadError):
            self.load(extra='command = "x"\n')

    def test_downloads_must_be_https_and_hashes_exact(self):
        with self.assertRaises(leads.LeadError):
            self.load(product='[products.download]\nurl = "http://example.invalid/a.exe"\n')
        with self.assertRaises(leads.LeadError):
            self.load(product='[products.download]\nsha256 = "abc"\n')

    def test_a_named_script_must_be_present(self):
        with self.assertRaises(leads.LeadError):
            self.load(product='[products.cabinet]\nscript = "missing.sh"\n')


class ScaffoldAndCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def invoke(self, *arguments):
        output, errors = io.StringIO(), io.StringIO()
        with patch('sys.argv', ['plugg', 'recipe', *arguments]), \
                patch('plugg.__main__.Store', side_effect=AssertionError('initialized a library')), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main()
        return code, output.getvalue(), errors.getvalue()

    def bundle(self, name='Example.vst3'):
        inner = self.root / name / 'Contents' / 'x86_64-win'
        inner.mkdir(parents=True)
        fake_pe(inner / name)
        return self.root / name

    def test_generated_recipe_carries_lead_notes_and_still_validates(self):
        text = recipe_scaffold.scaffold(self.bundle(), vendor='Valhalla DSP')
        self.assertIn('# Leads for this vendor', text)
        self.assertIn('Valhalla Supermassive', text)
        path = self.root / 'generated.toml'
        path.write_text(text)
        engine.load(path)

    def test_unrelated_vendor_gets_no_lead_notes(self):
        self.assertNotIn('Leads for this vendor', recipe_scaffold.scaffold(self.bundle(), vendor='Nobody Audio'))

    def test_init_warns_when_a_native_build_exists(self):
        code, _, errors = self.invoke('init', str(self.bundle()), '--vendor', 'u-he')
        self.assertEqual(code, 0)
        self.assertIn('native Linux build', errors)

    def test_leads_command_lists_and_filters(self):
        code, output, _ = self.invoke('leads', '--json')
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(output)), sum(len(data['products']) for data in leads.load_all()))
        code, output, _ = self.invoke('leads', 'surge')
        self.assertIn('Surge XT', output)
        self.assertIn('native Linux build', output)
        self.assertIn('From Cabinet', output)


if __name__ == '__main__':
    unittest.main()
