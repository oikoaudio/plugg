"""A published plug-in must not depend on where the source tree happens to be.

Bundles used to link their bridge files straight into the build directory,
which for a developer is a checkout. When the checkout was renamed, every
plug-in published from it failed at once, and Bitwig said only that it
could not initialize the plug-in. yabridge itself was never at fault and
the library looked healthy.

So the library keeps its own copy of each bridge build it publishes with,
and existing bundles can be moved onto one without changing which build
they run.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from plugg import bridge_bundle, core
from test_core import fake_pe


def build(directory, flavour='a'):
    directory.mkdir(parents=True)
    for name in bridge_bundle.RELEASE_FILES:
        (directory / name).write_bytes(('%s %s' % (name, flavour)).encode())
    (directory / 'COPYING.yabridge').write_text('licence')
    return directory


class Library(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = core.Store(self.root / 'library', self.root / 'published')
        self.checkout = build(self.root / 'checkout/bundle/bridge')
        source = patch.object(self.store, 'bridge_source', return_value=self.checkout)
        source.start()
        self.addCleanup(source.stop)

    def publish(self, name='Gain'):
        installer = fake_pe(self.root / (name + '.exe'))
        with installer.open('ab') as stream:
            stream.write(name.encode())  # two identical installers are one installation
        job = self.store.ingest(installer)
        module = fake_pe(self.store.prefix(job) / 'drive_c' / (name + '.vst3'))
        item = {'path': module, 'name': name, 'hash': core.digest(module)}
        core.publish(self.store, item, job, {'classes': [{'id': name.encode().hex(), 'name': name}]})
        return Path(next(x for x in self.store.plugins() if x['name'] == name)['publication'])

    def links(self, publication):
        native = publication / 'Contents/x86_64-linux'
        return {name: Path(os.readlink(native / name)) for name in core.BRIDGE_LINKS}


class ReleaseTests(Library):
    def test_new_bundles_link_into_the_library_and_survive_the_checkout_moving(self):
        publication = self.publish()
        for target in self.links(publication).values():
            self.assertEqual(target.parent.parent, self.store.root / 'bridge-releases')
        shutil.move(self.checkout.parents[1], self.root / 'renamed')
        for name in core.BRIDGE_LINKS:
            self.assertTrue((publication / 'Contents/x86_64-linux' / name).exists(), name)

    def test_the_same_build_is_one_release_and_a_new_build_is_another(self):
        first = self.store.bridge()
        self.assertEqual(self.store.bridge(), first)
        self.assertTrue((first / 'COPYING.yabridge').is_file())
        (self.checkout / 'yabridge-host.exe.so').write_bytes(b'patched')
        second = self.store.bridge()
        self.assertNotEqual(second, first)
        self.assertEqual((first / 'yabridge-host.exe.so').read_bytes(), b'yabridge-host.exe.so a')

    def test_a_release_changed_after_it_was_made_is_refused(self):
        release = self.store.bridge()
        (release / 'libyabridge-vst3.so').write_bytes(b'tampered')
        with self.assertRaisesRegex(core.HostError, 'has been changed'):
            self.store.bridge()

    def test_an_incomplete_build_is_refused(self):
        (self.checkout / 'plugg-scan').unlink()
        with self.assertRaisesRegex(core.HostError, 'plugg-scan'):
            self.store.bridge()


class RelinkTests(Library):
    def legacy(self, name, bridge):
        """Publish the way it was done before the library kept releases."""
        with patch.object(self.store, 'bridge', return_value=bridge):
            return self.publish(name)

    def test_plan_changes_nothing(self):
        publication = self.legacy('Gain', self.checkout)
        before = self.links(publication)
        result = core.relink_publications(self.store)
        self.assertEqual([x['name'] for x in result['planned']], ['Gain'])
        self.assertEqual(self.links(publication), before)
        self.assertFalse((self.store.root / 'bridge-releases').exists())
        self.assertFalse((self.store.root / 'migration-backups').exists())

    def test_each_bundle_keeps_the_build_it_had(self):
        current = self.legacy('Current', self.checkout)
        patched = self.legacy('Patched', build(self.root / 'checkout/bundle/bridge-releases/fix', 'fix'))
        result = core.relink_publications(self.store, apply=True)
        self.assertEqual(result['problems'], [])
        shutil.rmtree(self.root / 'checkout')
        for publication, flavour in ((current, 'a'), (patched, 'fix')):
            host = publication / 'Contents/x86_64-linux/yabridge-host.exe.so'
            self.assertEqual(host.read_bytes(), ('yabridge-host.exe.so ' + flavour).encode())
            self.assertEqual(Path(os.readlink(host)).parent.parent, self.store.root / 'bridge-releases')
        record = json.loads(Path(result['record']).read_text())
        self.assertTrue(record['applied'])
        self.assertEqual(record['relinks'][0]['links'][0]['from'],
                         str(self.checkout / 'libyabridge-vst3.so'))

    def test_a_second_run_finds_nothing_and_keeps_the_first_record(self):
        self.legacy('Gain', self.checkout)
        first = core.relink_publications(self.store, apply=True)['record']
        self.assertEqual(core.relink_publications(self.store)['planned'], [])
        again = core.relink_publications(self.store, apply=True)
        self.assertNotEqual(again['record'], first)
        self.assertTrue(json.loads(Path(first).read_text())['relinks'])

    def test_a_daw_link_through_an_old_library_path_is_moved(self):
        publication = self.publish()
        alias = self.root / 'plugg'
        alias.symlink_to(self.store.root)
        publication.unlink()
        publication.symlink_to(alias / 'bundles' / publication.name)
        planned = core.relink_publications(self.store)['planned']
        self.assertEqual([len(x['links']) for x in planned], [1])
        core.relink_publications(self.store, apply=True)
        self.assertEqual(Path(os.readlink(publication)), self.store.root / 'bundles' / publication.name)
        self.assertEqual(core.relink_publications(self.store)['planned'], [])

    def test_a_bundle_whose_build_is_gone_is_reported_and_left_alone(self):
        gone = build(self.root / 'elsewhere')
        publication = self.legacy('Gain', gone)
        shutil.rmtree(gone)
        result = core.relink_publications(self.store, apply=True)
        self.assertEqual(result['planned'], [])
        self.assertIn('missing', result['problems'][0]['problem'])
        self.assertEqual(self.links(publication)['libyabridge-vst3.so'], gone / 'libyabridge-vst3.so')

    def test_doctor_counts_what_depends_on_the_outside(self):
        self.legacy('Gain', self.checkout)
        self.publish('Other')
        self.assertEqual(core.doctor(self.store)['publications_outside_library']['relink'], 1)



class LauncherTests(unittest.TestCase):
    """Vendor launchers kept in an environment must not name the checkout either."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = core.Store(Path(temporary.name) / 'library', Path(temporary.name) / 'published')
        self.environment = self.store.root / 'environments' / 'e1'
        self.environment.mkdir(parents=True)

    def test_a_launcher_reaches_the_package_through_the_library(self):
        launcher = self.environment / 'launch-helper'
        core.write_module_launcher(launcher, 'plugg', self.environment)
        self.assertNotIn(str(core.REPO), launcher.read_text())
        self.assertIn(str(self.store.root / 'bin/python-module'), launcher.read_text())
        runner = self.store.root / 'bin/python-module'
        result = subprocess.run([runner, 'plugg', '--help'], cwd='/',
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_opening_the_library_repairs_a_runner_left_by_a_moved_checkout(self):
        runner = self.store.root / 'bin/python-module'
        runner.write_text('#!/bin/sh\nexec /old/checkout/python -m "$@"\n')
        core.Store(self.store.root)
        self.assertIn(str(core.REPO), runner.read_text())


if __name__ == '__main__':
    unittest.main()


class AdoptCurrentBridgeTests(Library):
    """Rebuilding the bridge must be able to reach plug-ins that already exist.

    A fix in the bridge is worth nothing if every published plug-in keeps
    loading the build it was published against. Relinking deliberately does not
    do this, so there has to be something that does.
    """

    def test_plan_changes_nothing(self):
        publication = self.publish()
        before = self.links(publication)
        (self.checkout / 'yabridge-host.exe.so').write_bytes(b'fixed')
        result = core.adopt_current_bridge(self.store)
        self.assertEqual([x['name'] for x in result['planned']], ['Gain'])
        self.assertEqual(self.links(publication), before)
        self.assertFalse((self.store.root / 'migration-backups').exists())

    def test_it_moves_publications_onto_the_new_build(self):
        publication = self.publish()
        old = self.links(publication)['yabridge-host.exe.so']
        (self.checkout / 'yabridge-host.exe.so').write_bytes(b'fixed')
        result = core.adopt_current_bridge(self.store, apply=True)
        self.assertEqual(result['problems'], [])
        links = self.links(publication)
        self.assertNotEqual(links['yabridge-host.exe.so'], old)
        self.assertEqual(links['yabridge-host.exe.so'].read_bytes(), b'fixed')
        for target in links.values():
            self.assertEqual(target.parent.name, result['release'])

    def test_the_loader_in_the_bundle_is_replaced_too(self):
        """The chainloader is a copy, not a link, so moving the links is not enough."""
        publication = self.publish()
        (self.checkout / 'libyabridge-chainloader-vst3.so').write_bytes(b'new chainloader')
        core.adopt_current_bridge(self.store, apply=True)
        loader = publication / 'Contents/x86_64-linux' / (publication.stem + '.so')
        self.assertEqual(loader.read_bytes(), b'new chainloader')
        self.assertFalse(loader.is_symlink())

    def test_the_publication_and_its_identity_do_not_move(self):
        publication = self.publish()
        before = os.readlink(publication) if publication.is_symlink() else None
        identity = [dict(row) for row in self.store.plugins()][0]['id']
        (self.checkout / 'yabridge-host.exe.so').write_bytes(b'fixed')
        core.adopt_current_bridge(self.store, apply=True)
        self.assertEqual([dict(row) for row in self.store.plugins()][0]['id'], identity)
        self.assertEqual(os.readlink(publication) if publication.is_symlink() else None, before)

    def test_repeating_it_does_nothing(self):
        self.publish()
        (self.checkout / 'yabridge-host.exe.so').write_bytes(b'fixed')
        core.adopt_current_bridge(self.store, apply=True)
        self.assertEqual(core.adopt_current_bridge(self.store)['planned'], [])

    def test_what_the_links_pointed_at_is_recorded(self):
        publication = self.publish()
        old = str(self.links(publication)['yabridge-host.exe.so'])
        (self.checkout / 'yabridge-host.exe.so').write_bytes(b'fixed')
        result = core.adopt_current_bridge(self.store, apply=True)
        record = json.loads(Path(result['record']).read_text())
        self.assertTrue(record['applied'])
        froms = [c['from'] for move in record['moves'] for c in move['links']]
        self.assertIn(old, froms)

    def test_doctor_says_when_plug_ins_are_on_an_older_build(self):
        self.publish()
        self.assertEqual(core.doctor(self.store)['bridge_in_use']['plugins_on_older_builds'], 0)
        (self.checkout / 'yabridge-host.exe.so').write_bytes(b'fixed')
        report = core.doctor(self.store)['bridge_in_use']
        self.assertEqual(report['plugins_on_older_builds'], 1)
        self.assertEqual(report['problems'], [])
