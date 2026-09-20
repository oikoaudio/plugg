"""A plug-in folder full of hashes tells its owner nothing.

Publishing under `ph-<hash>` kept every bundle name the same short length,
which mattered because yabridge builds a Unix socket path out of that name
and the kernel caps it at 108 bytes. The cost only became visible when a
host refused to load them: Audacity listed 38 paths of hex, and there was
no way to tell which plug-in any of them was, or that most of them were
simply waiting on an authorization.

So the budget is computed rather than avoided, and a name is used whenever
it fits. These tests pin both halves: that what is published stays inside
the socket limit, and that it is recognizable when it can be.
"""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from plugg import core


def longest_socket_path(stem, directory=None):
    """The path yabridge would build for this bundle, at its longest."""
    directory = directory or core.socket_directory()
    return str(Path(directory) / ("yabridge-" + stem + "-" + "A" * 8) / core.LONGEST_SOCKET_FILE)


class TheBudgetIsReal(unittest.TestCase):
    def test_a_name_at_the_budget_still_fits_a_socket_path(self):
        budget = core.name_budget()
        self.assertGreater(budget, len("ph-") + 20, 'a hash must always fit')
        self.assertLessEqual(len(longest_socket_path('x' * budget)), core.SOCKET_PATH_LIMIT)

    def test_one_character_more_would_not_fit(self):
        over = longest_socket_path('x' * (core.name_budget() + 1))
        self.assertGreater(len(over), core.SOCKET_PATH_LIMIT)

    def test_every_name_this_produces_fits(self):
        budget = core.name_budget()
        for name in ('Skaka', 'Black Box Analog Design HG-2', 'x' * 300, 'Über/Comp: "Wide"',
                     'uaudio_teletronix_la-2a_tc', '', '...', 'a b  c   d'):
            with self.subTest(name=name):
                chosen = core.readable_name(name, 'f' * 20)
                self.assertLessEqual(len(chosen), budget)
                self.assertLessEqual(len(longest_socket_path(chosen)), core.SOCKET_PATH_LIMIT)

    def test_a_directory_so_long_that_no_name_fits_falls_back_to_the_hash(self):
        # Nothing creates one, but the arithmetic must not produce a name that
        # cannot open a socket.
        tiny = core.name_budget('/' + 'd' * 200)
        self.assertEqual(core.readable_name('Skaka', 'a' * 20, budget=tiny), 'ph-' + 'a' * 20)


class NamesPeopleCanRead(unittest.TestCase):
    def test_an_ordinary_name_is_used_as_it_is(self):
        self.assertEqual(core.readable_name('Skaka', 'a' * 20), 'Skaka')
        self.assertEqual(core.readable_name('Lindell 50 Buss', 'a' * 20), 'Lindell 50 Buss')

    def test_vendor_punctuation_is_not_carried_into_a_path(self):
        chosen = core.readable_name('Über: Comp/Deluxe "v2"', 'a' * 20)
        for character in '/:"':
            self.assertNotIn(character, chosen)
        self.assertTrue(chosen.startswith('Über'), chosen)

    def test_a_long_name_loses_its_front_and_keeps_the_product(self):
        """The maker leads and the product ends it, and the product is the
        half a person recognizes in a plug-in list."""
        self.assertEqual(core.readable_name('Unfiltered Audio Bass Mint', 'a' * 20, budget=24),
                         'UA Bass Mint')
        self.assertEqual(core.readable_name('Shadow Hills Mastering Compressor', 'a' * 20, budget=24),
                         'SH Mastering Compressor')

    def test_a_known_brand_is_written_short_whatever_the_length(self):
        """Consistency is the point: a maker's plug-ins sit together in the
        folder instead of one being abbreviated and the next not. The short
        name has to come from the table, because every one of these reports
        its distributor as the vendor, not its maker."""
        for name, expected in (('Unfiltered Audio Silo', 'UA Silo'),
                               ('Unfiltered Audio Bass Mint', 'UA Bass Mint'),
                               ('Unfiltered Audio Sandman Pro', 'UA Sandman Pro')):
            with self.subTest(name=name):
                self.assertEqual(core.readable_name(name, 'a' * 20, budget=24,
                                                    vendor='Plugin Alliance'), expected)

    def test_a_brand_is_written_the_way_the_table_says_not_as_initials(self):
        self.assertEqual(core.readable_name('Universal Audio LA-2A', 'a' * 20, budget=24,
                                            vendor='Universal Audio'), 'uaudio LA-2A')

    def test_the_vendors_own_name_leading_a_product_is_abbreviated_too(self):
        self.assertEqual(core.readable_name('Acme Audio Widget', 'a' * 20, budget=24,
                                            vendor='Acme Audio'), 'AA Widget')

    def test_a_name_that_does_not_lead_with_its_maker_is_left_alone(self):
        self.assertEqual(core.readable_name('Massive X', 'a' * 20, vendor='Native Instruments'),
                         'Massive X')
        self.assertEqual(core.readable_name('Lindell 50 Buss', 'a' * 20, vendor='Lindell Audio'),
                         'Lindell 50 Buss')

    def test_one_word_makers_are_not_turned_into_a_single_letter(self):
        self.assertEqual(core.readable_name('Klevgrand Skaka', 'a' * 20, vendor='Klevgrand'),
                         'Klevgrand Skaka')

    def test_a_two_word_name_has_no_maker_to_abbreviate_so_it_loses_its_tail(self):
        self.assertEqual(core.readable_name('ThrillseekerXTCmkIII (64)', 'a' * 20, budget=24),
                         'ThrillseekerXTCmkIII')

    def test_a_long_name_with_no_word_boundary_keeps_its_front_and_stays_unique(self):
        chosen = core.readable_name('SuperLongNameWithNoBoundariesAtAll', 'abcd' + 'f' * 16, budget=24)
        self.assertTrue(chosen.startswith('SuperLong'), chosen)
        self.assertTrue(chosen.endswith('-abcd'), chosen)

    def test_shortening_never_steals_a_name_another_plug_in_uses(self):
        chosen = core.readable_name('Unfiltered Audio Sandman Pro', 'abcd' + 'f' * 16,
                                    taken={'Unfiltered Audio Sandman'}, budget=24)
        self.assertNotEqual(chosen, 'Unfiltered Audio Sandman')

    def test_a_name_already_taken_does_not_collide(self):
        first = core.readable_name('Massive', 'a' * 20)
        second = core.readable_name('Massive', 'b' * 20, taken={first})
        self.assertEqual(first, 'Massive')
        self.assertNotEqual(second, first)
        self.assertTrue(second.startswith('Massive'), second)

    def test_a_name_with_nothing_usable_in_it_becomes_the_hash(self):
        self.assertEqual(core.readable_name('///', 'c' * 20), 'ph-' + 'c' * 20)
        self.assertEqual(core.readable_name('', 'c' * 20), 'ph-' + 'c' * 20)

    def test_names_stay_stable_for_the_same_plug_in(self):
        """A republished plug-in must not land on a different path each time."""
        self.assertEqual(core.readable_name('Raum', 'a' * 20), core.readable_name('Raum', 'a' * 20))


class WhatTheDawSees(unittest.TestCase):
    """The publication directory, as a person browsing it would find it."""

    def setUp(self):
        import tempfile
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = core.Store(self.root / 'data', self.root / 'published')
        bridge = self.root / 'bridge'
        bridge.mkdir()
        for name in ('libyabridge-chainloader-vst3.so', 'libyabridge-vst3.so',
                     'yabridge-host.exe', 'yabridge-host.exe.so'):
            (bridge / name).write_bytes(b'fixture')
        patched = patch.object(self.store, 'bridge', return_value=bridge)
        patched.start()
        self.addCleanup(patched.stop)

    def publish(self, name, class_id, job='job-one'):
        module = self.root / 'prefix' / (name + '.vst3')
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_bytes(b'module ' + name.encode())
        return core.publish(self.store, {'path': module, 'name': name, 'hash': core.digest(module)},
                            job, {'classes': [{'id': class_id, 'name': name}]})

    def names(self):
        return sorted(path.name for path in self.store.publication.iterdir())

    def test_a_plug_in_is_published_under_its_own_name(self):
        self.publish('Skaka', 'class-skaka')
        self.assertEqual(self.names(), ['Skaka.vst3'])

    def test_the_linux_module_inside_matches_the_bundle_name(self):
        """A VST3 bundle's module is found by name; they must agree."""
        self.publish('Skaka', 'class-skaka')
        bundle = self.store.publication / 'Skaka.vst3'
        self.assertTrue((bundle / 'Contents/x86_64-linux/Skaka.so').is_file())
        self.assertTrue((bundle / 'Contents/x86_64-win/Skaka.vst3').is_symlink())

    def test_two_plug_ins_with_one_name_do_not_fight_over_it(self):
        self.publish('Compressor', 'class-one', job='job-one')
        self.publish('Compressor', 'class-two', job='job-two')
        published = self.names()
        self.assertEqual(len(published), 2)
        self.assertIn('Compressor.vst3', published)
        self.assertTrue(all(name.startswith('Compressor') for name in published), published)

    def test_reinstalling_gets_its_name_back(self):
        """The bundle kept from the retired install must not hold the name."""
        first = self.publish('Skaka', 'class-skaka')
        core.forget_plugin(self.store, first)
        self.publish('Skaka', 'class-skaka', job='job-two')
        self.assertEqual(self.names(), ['Skaka.vst3'])
        self.assertTrue((self.store.root / 'bundles' / ('ph-' + first + '.vst3')).is_dir(),
                        'the retired bundle is kept, under its identity')

    def test_migration_republishes_hashed_names_and_keeps_the_old_bundle(self):
        identity = self.publish('Skaka', 'class-skaka')
        # Put it back the way an older version of this app published it.
        old = self.store.publication / ('ph-' + identity + '.vst3')
        current = self.store.publication / 'Skaka.vst3'
        target = current.resolve()
        current.unlink()
        (self.store.root / 'bundles' / ('ph-' + identity + '.vst3')).symlink_to(target)
        old.symlink_to(self.store.root / 'bundles' / ('ph-' + identity + '.vst3'),
                       target_is_directory=True)
        with self.store.db() as db:
            db.execute('UPDATE plugins SET publication=? WHERE id=?', (str(old), identity))

        planned = core.rename_publications(self.store)
        self.assertEqual([item['name'] for item in planned], ['Skaka'])
        self.assertEqual(self.names(), ['ph-' + identity + '.vst3'], 'a plan changes nothing')

        core.rename_publications(self.store, apply=True)
        self.assertEqual(self.names(), ['Skaka.vst3'])
        row, = self.store.plugins()
        self.assertEqual(Path(row['publication']).name, 'Skaka.vst3')
        record = json.loads((self.store.root / 'migration-backups' /
                             'publication-names.json').read_text())
        self.assertTrue(record['applied'])
        self.assertEqual(Path(record['renames'][0]['from']).name, 'ph-' + identity + '.vst3')

    def test_nothing_to_rename_says_so_rather_than_doing_work(self):
        self.publish('Skaka', 'class-skaka')
        self.assertEqual(core.rename_publications(self.store), [])


if __name__ == '__main__':
    unittest.main()
