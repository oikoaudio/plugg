"""A product you uninstalled must be installable again.

Publishing refuses two plug-ins with the same class identity. Without a way to
retire a record, that check quietly turns "I uninstalled this" into "I can never
install this again" — the library keeps believing it is ready and the vendor's
own uninstaller has no way to tell it otherwise.
"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugg import core
from test_core import fake_pe


class ForgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = core.Store(self.root / 'store', self.root / 'published')
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
        fake_pe(module)
        metadata = {'classes': [{'id': class_id, 'name': name}]}
        return core.publish(self.store, {'path': module, 'name': name, 'hash': core.digest(module)},
                            job, metadata)

    def published(self, identity):
        """Where it went, according to the record. A bundle name is no longer
        reconstructible from an identity, and should not need to be."""
        row, = [p for p in self.store.plugins() if p['id'] == identity]
        return Path(row['publication'])

    def test_a_published_plugin_blocks_republishing_the_same_product(self):
        self.publish('Skaka', 'class-skaka')
        with self.assertRaisesRegex(core.HostError, 'already in your managed library'):
            self.publish('Skaka', 'class-skaka', job='job-two')

    def test_forgetting_it_allows_the_product_to_be_installed_again(self):
        self.publish('Skaka', 'class-skaka')
        core.forget_plugin(self.store, [p for p in self.store.plugins()][0]['id'])
        # A fresh install gets a new identity and must not be refused.
        second = self.publish('Skaka', 'class-skaka', job='job-two')
        self.assertTrue(second)
        ready = [p for p in self.store.plugins() if p['status'] == 'ready']
        self.assertEqual([p['name'] for p in ready], ['Skaka'])

    def test_forgetting_removes_it_from_the_directory_the_daw_scans(self):
        identity = self.publish('Skaka', 'class-skaka')
        published = self.published(identity)
        self.assertTrue(published.is_symlink())
        result = core.forget_plugin(self.store, identity)
        self.assertFalse(published.is_symlink() or published.exists())
        self.assertTrue(result['unpublished'])

    def test_the_built_bundle_is_kept_so_the_removal_can_be_inspected(self):
        identity = self.publish('Skaka', 'class-skaka')
        core.forget_plugin(self.store, identity)
        self.assertTrue((self.store.root / 'bundles' / self.published(identity).name).is_dir())

    def test_the_record_says_what_happened_rather_than_disappearing(self):
        identity = self.publish('Skaka', 'class-skaka')
        core.forget_plugin(self.store, identity)
        row, = [p for p in self.store.plugins() if p['id'] == identity]
        self.assertEqual(row['status'], 'removed')
        self.assertIn('Install it again', row['message'])

    def test_an_unmanaged_file_at_the_publication_path_is_left_alone(self):
        identity = self.publish('Skaka', 'class-skaka')
        published = self.published(identity)
        published.unlink()
        published.mkdir()
        with self.assertRaisesRegex(core.HostError, 'not a managed link'):
            core.forget_plugin(self.store, identity)

    def test_forgetting_an_unknown_plugin_is_an_error(self):
        with self.assertRaisesRegex(core.HostError, 'No such plug-in'):
            core.forget_plugin(self.store, 'nothing')

    def test_an_environment_can_be_retired_in_one_step(self):
        for name, class_id in (('Skaka', 'c1'), ('Slammer', 'c2'), ('Richter', 'c3')):
            self.publish(name, class_id, job='klevgrand')
        results = core.forget_environment(self.store, 'klevgrand')
        self.assertEqual(len(results), 3)
        self.assertEqual([p for p in self.store.plugins() if p['status'] == 'ready'], [])
        with self.assertRaisesRegex(core.HostError, 'No published plug-ins remain'):
            core.forget_environment(self.store, 'klevgrand')

    def test_retiring_one_environment_leaves_another_alone(self):
        self.publish('Skaka', 'c1', job='klevgrand')
        self.publish('FerricTDS', 'c2', job='vos')
        core.forget_environment(self.store, 'klevgrand')
        ready = [p['name'] for p in self.store.plugins() if p['status'] == 'ready']
        self.assertEqual(ready, ['FerricTDS'])


class ArchivedVendorTests(unittest.TestCase):
    """An archived installation must stop holding its vendor's slot.

    Intake refuses a second install of a vendor that already has a card. If
    archiving hides the card but keeps the slot, the error tells the user to use
    a card that is no longer on screen, and the vendor can never be reinstalled.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = core.Store(self.root / 'store', self.root / 'published')

    def configured(self, job_id, recipe='klevgrand'):
        """A finished vendor installation, as the library records one."""
        directory = self.store.root / 'environments' / job_id
        (directory / 'prefix').mkdir(parents=True)
        core.atomic_json(directory / 'environment.json', {
            'id': job_id, 'recipe': recipe, 'status': 'ready',
            'helper_launcher': str(directory / 'launch-helper'),
            'session_launcher': str(directory / 'launch-plugin')})
        (directory / 'launch-helper').write_text('#!/bin/sh\n')
        now = 1.0
        with self.store.db() as db:
            db.execute('INSERT INTO jobs(id,name,installer,kind,hash,status,message,created,updated,env_id)'
                       ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (job_id, 'Vendor', '/none.exe', 'exe', 'h', 'ready', 'Ready', now, now, job_id))

    def test_an_archived_installation_no_longer_shows_a_vendor_card(self):
        from plugg import vendors
        self.configured('one')
        self.assertEqual([c['recipe'] for c in vendors.cards(self.store)], ['klevgrand'])
        self.store.archive('one', True)
        self.assertEqual(vendors.cards(self.store), [])

    def test_restoring_it_brings_the_card_back(self):
        from plugg import vendors
        self.configured('one')
        self.store.archive('one', True)
        self.store.archive('one', False)
        self.assertEqual([c['recipe'] for c in vendors.cards(self.store)], ['klevgrand'])


class AutomaticRetirementTests(unittest.TestCase):
    """Uninstalling in the vendor's own helper must be enough.

    Closing the helper triggers a refresh. If that refresh only adds what it
    finds, the library keeps asserting that a product the user deliberately
    uninstalled is still available to their DAW.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = core.Store(self.root / 'store', self.root / 'published')
        bridge = self.root / 'bridge'
        bridge.mkdir()
        for name in ('libyabridge-chainloader-vst3.so', 'libyabridge-vst3.so',
                     'yabridge-host.exe', 'yabridge-host.exe.so'):
            (bridge / name).write_bytes(b'fixture')
        patched = patch.object(self.store, 'bridge', return_value=bridge)
        patched.start()
        self.addCleanup(patched.stop)
        self.prefix = self.store.root / 'environments' / 'vendor' / 'prefix'
        self.prefix.mkdir(parents=True)
        self.job('vendor')

    def job(self, job_id):
        with self.store.db() as db:
            db.execute('INSERT INTO jobs(id,name,installer,kind,hash,status,message,created,updated,env_id)'
                       ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (job_id, 'Vendor', '/none.exe', 'exe', 'h', 'ready', 'Ready', 1.0, 1.0, job_id))

    def install(self, name, class_id):
        module = self.prefix / (name + '.vst3')
        fake_pe(module)
        core.publish(self.store, {'path': module, 'name': name, 'hash': core.digest(module)},
                     'vendor', {'classes': [{'id': class_id, 'name': name}]})
        return module

    def test_a_product_removed_by_the_vendor_uninstaller_is_retired(self):
        from plugg import vendors
        kept = self.install('Slammer', 'c2')
        self.install('Skaka', 'c1').unlink()
        gone = vendors.retire_uninstalled(self.store, 'vendor')
        self.assertEqual(gone, ['Skaka'])
        live = {p['name']: p['status'] for p in self.store.plugins()}
        self.assertEqual(live, {'Skaka': 'removed', 'Slammer': 'ready'})
        self.assertTrue(kept.exists())

    def test_an_unreadable_environment_never_mass_retires_a_vendor(self):
        from plugg import vendors
        self.install('Skaka', 'c1')
        self.install('Slammer', 'c2')
        import shutil
        shutil.rmtree(self.prefix)
        # The prefix is gone, not the products. Retiring everything here would
        # turn a mounting problem into a library that forgot the user's plug-ins.
        self.assertEqual(vendors.retire_uninstalled(self.store, 'vendor'), [])
        self.assertEqual({p['status'] for p in self.store.plugins()}, {'ready'})

    def test_another_environment_is_never_touched(self):
        from plugg import vendors
        self.install('Skaka', 'c1').unlink()
        other = self.store.root / 'environments' / 'other' / 'prefix'
        other.mkdir(parents=True)
        self.job('other')
        module = other / 'FerricTDS.vst3'
        fake_pe(module)
        core.publish(self.store, {'path': module, 'name': 'FerricTDS', 'hash': core.digest(module)},
                     'other', {'classes': [{'id': 'c9', 'name': 'FerricTDS'}]})
        vendors.retire_uninstalled(self.store, 'vendor')
        live = {p['name']: p['status'] for p in self.store.plugins()}
        self.assertEqual(live['FerricTDS'], 'ready')

    def test_retiring_frees_the_product_to_be_installed_again(self):
        from plugg import vendors
        self.install('Skaka', 'c1').unlink()
        vendors.retire_uninstalled(self.store, 'vendor')
        self.install('Skaka', 'c1')  # must not raise
        ready = [p['name'] for p in self.store.plugins() if p['status'] == 'ready']
        self.assertEqual(ready, ['Skaka'])


class StaleHelperStateTests(unittest.TestCase):
    """A status that outlived its process must not wedge a vendor card.

    The card reads helper-state.json. If the process that would have cleared it
    is killed, the card goes on claiming the helper is open and its buttons stay
    disabled — and a vendor whose card has no refresh button has no way out.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = core.Store(self.root / 'store', self.root / 'published')
        self.directory = self.store.root / 'environments' / 'vendor'
        (self.directory / 'prefix').mkdir(parents=True)
        core.atomic_json(self.directory / 'environment.json', {
            'id': 'vendor', 'recipe': 'pace-service-experiment', 'status': 'ready',
            'helper_launcher': str(self.directory / 'launch-helper'),
            'session_launcher': str(self.directory / 'launch-plugin')})
        (self.directory / 'launch-helper').write_text('#!/bin/sh\n')
        with self.store.db() as db:
            db.execute('INSERT INTO jobs(id,name,installer,kind,hash,status,message,created,updated,env_id)'
                       ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                       ('vendor', 'UA', '/none.exe', 'exe', 'h', 'ready', 'Ready', 1.0, 1.0, 'vendor'))
        core.atomic_json(self.directory / 'helper-state.json', {
            'status': 'running', 'message': 'UA Connect is open.', 'pid': 999999})

    def test_a_stale_status_does_not_leave_the_card_busy(self):
        from plugg import vendors
        card, = vendors.cards(self.store)
        self.assertFalse(card['busy'])

    def test_the_card_says_something_the_user_can_act_on(self):
        from plugg import vendors
        card, = vendors.cards(self.store)
        # This vendor has no refresh button, so telling them to refresh is useless.
        self.assertFalse(card['can_refresh'])
        self.assertIn('helper-reset', card['message'])
        self.assertNotIn('UA Connect is open', card['message'])

    def test_resetting_clears_it(self):
        from plugg import vendors
        result = vendors.reset_helper_state(self.store, 'vendor')
        self.assertEqual(result['cleared'], 'running')
        self.assertFalse((self.directory / 'helper-state.json').exists())
        card, = vendors.cards(self.store)
        self.assertFalse(card['needs_attention'])

    def test_resetting_is_refused_while_something_is_really_running(self):
        import fcntl
        from plugg import vendors
        with (self.directory / 'helper.lock').open('w') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(core.HostError) as caught:
                vendors.reset_helper_state(self.store, 'vendor')
        # Advice the interface can actually carry out: there may be no window
        # to close, which is the whole reason this state is reachable.
        self.assertIn('Force close', str(caught.exception))

    def test_resetting_an_environment_with_no_status_is_harmless(self):
        from plugg import vendors
        vendors.reset_helper_state(self.store, 'vendor')
        self.assertIsNone(vendors.reset_helper_state(self.store, 'vendor')['cleared'])


class StopHelperTests(unittest.TestCase):
    """Closing a window is not closing a program, so there must be a way to say so."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = core.Store(self.root / 'store', self.root / 'published')
        self.directory = self.store.root / 'environments' / 'vendor'
        (self.directory / 'prefix').mkdir(parents=True)
        runtime = self.root / 'runtime'
        (runtime / 'files/bin').mkdir(parents=True)
        self.server = runtime / 'files/bin/wineserver'
        self.server.write_text('#!/bin/sh\n')
        self.server.chmod(0o755)
        core.atomic_json(self.directory / 'environment.json', {
            'id': 'vendor', 'recipe': 'pace-service-experiment', 'status': 'ready',
            'helper_launcher': str(self.directory / 'launch-helper')})
        core.atomic_json(self.directory / 'session.json', {'proton': str(runtime / 'proton')})
        (self.directory / 'launch-helper').write_text('#!/bin/sh\n')
        core.atomic_json(self.directory / 'helper-state.json',
                         {'status': 'running', 'message': 'UA Connect is open.'})
        with self.store.db() as db:
            db.execute('INSERT INTO jobs(id,name,installer,kind,hash,status,message,created,updated,env_id)'
                       ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                       ('vendor', 'UA', '/none.exe', 'exe', 'h', 'ready', 'Ready', 1.0, 1.0, 'vendor'))

    def running(self, *sequences):
        """Patch the one place process names come from, with real pid shapes."""
        from plugg import vendors
        if len(sequences) == 1:
            return patch('plugg.vendors.running_programs', return_value=list(sequences[0]))
        remaining = iter(sequences)
        return patch('plugg.vendors.running_programs',
                     side_effect=lambda *a, **k: list(next(remaining, ())))

    def test_it_refuses_while_a_daw_is_open(self):
        from plugg import vendors
        with self.running([(4321, 'UA Connect.exe')]), \
             patch('plugg.ua_connect.require_idle_desktop',
                   side_effect=core.HostError('Close Bitwig first')):
            with self.assertRaisesRegex(core.HostError, 'Close Bitwig'):
                vendors.stop_helper(self.store, 'vendor')

    def test_it_never_stops_another_runtimes_server(self):
        from plugg import vendors
        other = self.root / 'elsewhere'
        other.mkdir()
        stranger = other / 'wineserver'
        stranger.write_text('#!/bin/sh\n')
        with self.running([(4321, 'UA Connect.exe')]), \
             patch('plugg.ua_connect.require_idle_desktop'), \
             patch('plugg.proton_session.foreign_prefix_processes', return_value=[1]), \
             patch('pathlib.Path.resolve', autospec=True,
                   side_effect=lambda self, **k: stranger if 'proc' in str(self) else Path(str(self))):
            with self.assertRaisesRegex(core.HostError, 'different Wine runtime'):
                vendors.stop_helper(self.store, 'vendor')

    def test_an_environment_with_nothing_running_just_clears_its_status(self):
        from plugg import vendors
        with self.running([]), patch('subprocess.run', side_effect=AssertionError('killed something')):
            result = vendors.stop_helper(self.store, 'vendor')
        self.assertEqual(result['stopped'], [])
        self.assertEqual(result['state'], 'running')
        self.assertFalse((self.directory / 'helper-state.json').exists())

    def test_stopping_reports_what_it_ended_and_clears_the_card(self):
        from plugg import vendors
        with self.running([(4321, 'UA Connect.exe'), (4322, 'uahelperservice.exe')], []), \
             patch('plugg.ua_connect.require_idle_desktop'), \
             patch('plugg.proton_session.foreign_prefix_processes', return_value=[]), \
             patch('plugg.proton_session.stop_idle_session'), \
             patch('subprocess.run') as run:
            result = vendors.stop_helper(self.store, 'vendor')
        self.assertEqual(result['stopped'], ['UA Connect.exe', 'uahelperservice.exe'])
        self.assertTrue(result['settled'])
        self.assertFalse((self.directory / 'helper-state.json').exists())
        run.assert_not_called()  # no server of ours was found to kill

    def test_everything_in_a_shared_environment_goes_together(self):
        # iLok and the vendor manager share one prefix and one Wine server.
        # Reporting only the card's own application would understate what the
        # person just agreed to.
        from plugg import vendors
        with self.running([(1, 'UA Connect.exe'), (2, 'iLok License Manager.exe')], []), \
             patch('plugg.ua_connect.require_idle_desktop'), \
             patch('plugg.proton_session.foreign_prefix_processes', return_value=[]), \
             patch('plugg.proton_session.stop_idle_session'), \
             patch('subprocess.run'):
            result = vendors.stop_helper(self.store, 'vendor')
        self.assertEqual(result['stopped'], ['UA Connect.exe', 'iLok License Manager.exe'])

    def test_programs_that_survive_are_named_not_numbered(self):
        # The report must read like something a person can act on. Listing the
        # process ids instead would not merely be unhelpful: joining them is a
        # TypeError, so the refusal never reaches the user at all.
        from plugg import vendors
        with self.running([(48812, 'stubborn.exe')]), \
             patch('plugg.ua_connect.require_idle_desktop'), \
             patch('plugg.proton_session.foreign_prefix_processes', return_value=[]), \
             patch('time.sleep'):
            with self.assertRaises(core.HostError) as caught:
                vendors.stop_helper(self.store, 'vendor')
        self.assertIn('stubborn.exe', str(caught.exception))
        self.assertNotIn('48812', str(caught.exception))

    def test_a_status_that_cannot_be_cleared_yet_is_not_a_failure(self):
        # The worker that was watching the helper still holds the lock while it
        # writes its own last word. The programs are gone; reporting failure
        # here would send the person back to press the button again, after the
        # destructive part had already succeeded.
        import fcntl
        from plugg import vendors
        with (self.directory / 'helper.lock').open('w') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.running([(1, 'UA Connect.exe')], []), \
                 patch('plugg.ua_connect.require_idle_desktop'), \
                 patch('plugg.proton_session.foreign_prefix_processes', return_value=[]), \
                 patch('plugg.proton_session.stop_idle_session'), \
                 patch('subprocess.run'), patch('time.sleep'):
                result = vendors.stop_helper(self.store, 'vendor', settle=0.0)
        self.assertEqual(result['stopped'], ['UA Connect.exe'])
        self.assertFalse(result['settled'])
        self.assertIsNone(result['state'])

    def test_it_waits_for_the_worker_and_then_clears(self):
        from plugg import vendors
        import fcntl, threading
        handle = (self.directory / 'helper.lock').open('w')
        self.addCleanup(handle.close)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        threading.Timer(0.3, lambda: fcntl.flock(handle, fcntl.LOCK_UN)).start()
        with self.running([]):
            result = vendors.stop_helper(self.store, 'vendor', settle=10.0)
        self.assertTrue(result['settled'])
        self.assertEqual(result['state'], 'running')


class ForceCloseControlTests(unittest.TestCase):
    """The one control on a vendor card that must survive a busy card.

    GTK is not importable here, so this reads the source. That is the point:
    the risk is a later refactor sweeping Force close into the "disable while
    busy" loop beside it, which would remove the only way out of exactly the
    state it exists for.
    """

    SOURCE = Path(__file__).resolve().parents[1] / 'plugg' / 'gui.py'

    def test_the_force_close_control_calls_stop_helper(self):
        text = self.SOURCE.read_text()
        self.assertIn("Gtk.Button(label='Force close')", text)
        self.assertIn('vendors.stop_helper(', text)

    def test_force_close_is_never_disabled_with_the_other_buttons(self):
        import ast
        tree = ast.parse(self.SOURCE.read_text())
        disabled = [node.lineno for node in ast.walk(tree)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'set_sensitive'
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == 'force']
        self.assertEqual(disabled, [], 'Force close exists for the case where the card is busy '
                                       'because a program never exited. Disabling it alongside '
                                       'the other buttons removes the only way out of that state.')


class RunningApplicationTests(unittest.TestCase):
    """A hidden window is not a stopped program, and the card should say so.

    Greying the Open button out while the application is alive tells the person
    the opposite of what the manager can see, and leaves ending it as the only
    offer. These cover the two halves: the card reports what is running, and
    there is a way back into it that starts nothing new.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = core.Store(self.root / 'store', self.root / 'published')
        self.directory = self.store.root / 'environments' / 'vendor'
        (self.directory / 'prefix').mkdir(parents=True)
        core.atomic_json(self.directory / 'environment.json', {
            'id': 'vendor', 'recipe': 'pace-service-experiment', 'status': 'ready',
            'helper_launcher': str(self.directory / 'launch-helper'),
            'ilok_launcher': str(self.directory / 'launch-ilok')})
        (self.directory / 'launch-helper').write_text('#!/bin/sh\n')
        with self.store.db() as db:
            db.execute('INSERT INTO jobs(id,name,installer,kind,hash,status,message,created,updated,env_id)'
                       ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                       ('vendor', 'UA', '/none.exe', 'exe', 'h', 'ready', 'Ready', 1.0, 1.0, 'vendor'))
        core.atomic_json(self.directory / 'helper-state.json',
                         {'status': 'running', 'message': 'UA Connect is open.'})

    def alive(self, *names):
        return patch('plugg.vendors.running_programs',
                     side_effect=lambda *a, **k: [(4000 + i, n) for i, n in enumerate(names)])

    def test_the_card_names_what_is_running_in_the_environment(self):
        from plugg import vendors
        with self.alive('UA Connect.exe', 'iLok License Manager.exe'):
            card, = vendors.cards(self.store)
        self.assertEqual(card['running'], ['UA Connect.exe', 'iLok License Manager.exe'])

    def test_a_stale_status_over_live_programs_says_so(self):
        # The old wording — "Nothing is running now" — was the exact opposite of
        # the truth in the case that sent someone looking for this button.
        from plugg import vendors
        with self.alive('UA Connect.exe'):
            card, = vendors.cards(self.store)
        self.assertNotIn('Nothing is running', card['message'])
        self.assertIn('still running', card['message'])

    def test_an_environment_with_nothing_alive_reports_nothing(self):
        from plugg import vendors
        with self.alive():
            card, = vendors.cards(self.store)
        self.assertEqual(card['running'], [])
        self.assertIn('Nothing is running', card['message'])

    def test_an_existing_window_is_focused_without_launching_anything(self):
        from plugg import vendors
        with self.alive('UA Connect.exe'), \
             patch('plugg.vendors.visible_window', return_value={'address': '0x1', 'pid': 4000}), \
             patch('plugg.vendors.open_native_access',
                   side_effect=AssertionError('launched over a live window')):
            result = vendors.show_helper(self.store, 'vendor')
        self.assertTrue(result['restored'])
        self.assertTrue(result['focused'])

    def test_asking_a_windowless_program_to_show_itself_is_verified(self):
        # Closing an Electron window destroys it. Whether the program can make
        # another is the vendor's decision, so the only honest report is
        # whether a window actually appeared.
        from plugg import vendors
        with self.alive('UA Connect.exe'), \
             patch('plugg.vendors.visible_window', return_value=None), \
             patch('plugg.vendors.open_native_access', return_value=4000) as opened, \
             patch('time.sleep'):
            result = vendors.show_helper(self.store, 'vendor', wait=0.0)
        self.assertFalse(result['restored'])
        # Matched on the window's own title, not the card's friendly heading.
        self.assertEqual(opened.call_args.kwargs['title'], 'UA Connect')
        self.assertEqual(opened.call_args.args[1], str(self.directory / 'launch-helper'))

    def test_the_licence_manager_opens_with_its_own_launcher(self):
        from plugg import vendors
        with self.alive('iLok License Manager.exe'), \
             patch('plugg.vendors.visible_window', return_value=None), \
             patch('plugg.vendors.open_native_access', return_value=4000) as opened, \
             patch('time.sleep'):
            vendors.show_helper(self.store, 'vendor', ilok=True, wait=0.0)
        self.assertEqual(opened.call_args.kwargs['title'], 'iLok License Manager')
        self.assertEqual(opened.call_args.args[1], str(self.directory / 'launch-ilok'))

    def test_it_refuses_to_resurrect_something_that_is_not_running(self):
        from plugg import vendors
        with self.alive(), patch('plugg.vendors.visible_window', return_value=None), \
             patch('plugg.vendors.open_native_access',
                   side_effect=AssertionError('started something')):
            with self.assertRaisesRegex(core.HostError, 'Nothing is running'):
                vendors.show_helper(self.store, 'vendor')

    def test_the_card_scans_process_state_once_for_the_whole_library(self):
        # Once per card, several times a second, is a full walk of /proc per
        # card. The interface must ask once and look each environment up.
        from plugg import vendors
        with patch('plugg.proton_session.prefix_processes', return_value={}) as scan, \
             patch('plugg.proton_session.foreign_prefix_processes',
                   side_effect=AssertionError('scanned per card')):
            vendors.cards(self.store)
        self.assertEqual(scan.call_count, 1)


class RunningControlPresentationTests(unittest.TestCase):
    """What the card offers while an application is alive but hidden."""

    SOURCE = Path(__file__).resolve().parents[1] / 'plugg' / 'gui.py'

    def test_a_running_application_gets_a_way_back_in(self):
        text = self.SOURCE.read_text()
        self.assertIn("add_css_class('running')", text)
        self.assertIn('vendors.show_helper(', text)

    def test_the_running_style_exists_in_the_theme(self):
        from plugg import theme
        for mode in ('dark', 'light'):
            self.assertIn(b'button.running', theme.css(mode))
            self.assertIn(b'.running-note', theme.css(mode))


class LibraryLayoutTests(unittest.TestCase):
    """Where each section sits, and what a managed plug-in points at.

    GTK cannot be imported here, so these read the source. They exist because
    the arrangement is the feature: helpers above the list they fill, one
    plug-in list with the maker as a column, and a managed plug-in pointing at
    the helper that manages it rather than at an installer file.
    """

    SOURCE = Path(__file__).resolve().parents[1] / 'plugg' / 'gui.py'

    def setUp(self):
        self.text = self.SOURCE.read_text()

    def test_each_view_is_a_tab_rather_than_another_screenful(self):
        # Stacked down one page these had grown taller than any screen, and the
        # cost of that is not scrolling: it is that nothing can be found
        # without scrolling past everything else.
        for name in ('plugins', 'helpers', 'environments'):
            self.assertIn("'%s'," % name, self.text)
        # No tab of past attempts. An attempt is either something you are still
        # dealing with, which is in the strip above every tab, or something you
        # are not, which is gone.
        self.assertNotIn("'history', 'History'", self.text)
        self.assertIn('Gtk.StackSwitcher(stack=self.stack)', self.text)
        # The library list is the window; the older views sit behind one toggle.
        self.assertIn("self.stack.add_titled(library_page, 'library', 'Library')", self.text)
        self.assertIn('title.append(switcher)', self.text)

    def test_adding_a_file_stays_reachable_from_every_tab(self):
        drop = self.text.index('content.append(drop)')
        activity = self.text.index('content.append(self.activity)')
        stack = self.text.index('content.append(self.stack)')
        self.assertLess(drop, stack, 'The drop area must not belong to one tab.')
        self.assertLess(activity, stack, 'Work in progress must be visible from all of them.')

    def test_the_chosen_tab_is_remembered(self):
        self.assertIn("'tab': self.tab", self.text)
        self.assertIn('self.stack.set_visible_child_name(self.tab)', self.text)

    def test_every_header_is_one_bar_across_the_window(self):
        from plugg import theme
        self.assertIn("toolbar.add_css_class('section-header')", self.text)
        self.assertIn("heading_row.add_css_class('section-header')", self.text)
        for mode in ('dark', 'light'):
            self.assertIn(b'.section-header', theme.css(mode))

    def test_a_managed_plug_in_is_pointed_at_its_helper_not_an_installer(self):
        self.assertIn('self.reveal_helper(', self.text)
        managed = self.text.index("if managed:")
        saved = self.text.index("saved = Gtk.Button(label='Open saved files')")
        self.assertLess(managed, saved, 'The saved-file route must be the branch for plug-ins '
                                        'that were not installed through a helper.')

    def test_a_helper_card_shows_a_count_rather_than_every_product(self):
        self.assertIn("self.listing('Manages %d plug-in'", self.text)
        # This rule concerns helper cards, not component-to-recipe attribution.
        refresh = self.text.split('    def refresh(self):', 1)[1]
        self.assertNotIn("'Used by: '", refresh)


class FilterScrollPositionTests(unittest.TestCase):
    """Filtering must not leave you at the end of the results you asked for.

    A scrolled window keeps its position by clamping it to whatever content is
    left. Shorten the list by filtering and that clamp lands at the bottom, so
    the answer to "show me this vendor" arrives scrolled past.
    """

    SOURCE = Path(__file__).resolve().parents[1] / 'plugg' / 'gui.py'

    def setUp(self):
        self.text = self.SOURCE.read_text()

    def test_changing_either_filter_asks_for_the_list_header(self):
        import ast
        tree = ast.parse(self.text)
        wanted = {'filter_changed', 'search_changed'}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in wanted:
                sets = [n for n in ast.walk(node)
                        if isinstance(n, ast.Attribute) and n.attr == 'reveal_list']
                self.assertTrue(sets, node.name + ' must ask for the list header')
                wanted.discard(node.name)
        self.assertFalse(wanted, 'missing handlers: ' + ', '.join(sorted(wanted)))

    def test_the_position_is_set_after_layout_not_during_it(self):
        self.assertIn('GLib.idle_add(self.scroll_to_library', self.text)

    def test_it_never_scrolls_past_what_exists(self):
        self.assertIn('adjustment.get_upper() - adjustment.get_page_size()', self.text)


class HelperCardTests(unittest.TestCase):
    """What a helper card leads with, and in what order.

    A row of cards is scanned for whose plug-ins these are; the application
    that installs them is the next question, not the first. And the controls
    come before the inventory, because the card exists to be used.
    """

    SOURCE = Path(__file__).resolve().parents[1] / 'plugg' / 'gui.py'

    def setUp(self):
        self.text = self.SOURCE.read_text()

    def test_the_card_leads_with_the_vendor_and_names_the_helper_under_it(self):
        self.assertIn("heading = label(vendor, 'card-title')", self.text)
        self.assertIn("card.append(label(title, 'status'))", self.text)
        self.assertLess(self.text.index("card.append(heading)"),
                        self.text.index("card.append(label(title, 'status'))"))

    def test_the_controls_come_before_the_inventory(self):
        actions = self.text.index('card.append(self.button_grid(buttons))')
        listing = self.text.index("self.listing('Manages %d plug-in'")
        self.assertLess(actions, listing, 'The buttons are what the card is for; the count of '
                                          'what it manages is reference, and belongs under them.')

    def test_the_controls_sit_on_a_grid_of_equal_columns(self):
        # Labels differ in length, so a row of them is ragged and a wrapping
        # box is worse: the break moves as the window resizes.
        from plugg import theme
        self.assertIn('Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)', self.text)
        self.assertIn("button.add_css_class('compact')", self.text)
        for mode in ('dark', 'light'):
            self.assertIn(b'button.compact', theme.css(mode))

    def test_a_standing_caveat_is_one_line_with_the_rest_on_hover(self):
        # Several helper messages are permanent notes about an experimental
        # integration, not news. As a paragraph they set the height of every
        # card in the row.
        self.assertIn("message = label(setup['message'], 'status')", self.text)
        self.assertIn("message.set_ellipsize(Pango.EllipsizeMode.END)", self.text)
        self.assertIn("message.set_tooltip_text(setup['message'])", self.text)


class ArchiveCommandTests(unittest.TestCase):
    """Retiring the installation that holds a vendor's slot must be reachable.

    A vendor card has no archive control -- and the job behind it is filtered
    out of the list that does -- so the one action that frees a vendor for a
    fresh install had no route through either interface.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = core.Store(root / 'store', root / 'published')
        with self.store.db() as db:
            db.execute('INSERT INTO jobs(id,name,installer,kind,hash,status,message,created,updated,env_id)'
                       ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                       ('helper', 'Klevgrand Helper', '/none.exe', 'exe', 'h', 'ready', 'Ready',
                        1.0, 1.0, 'helper'))

    def run_cli(self, *argv):
        from plugg.__main__ import main
        import io, contextlib
        with patch('sys.argv', ['plugg', '--data', str(self.store.root), *argv]), \
             patch('plugg.__main__.Store', return_value=self.store), \
             contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
            return main(), out.getvalue()

    def archived(self):
        return [job['id'] for job in self.store.jobs() if job['archived']]

    def test_archiving_retires_the_installation(self):
        code, _ = self.run_cli('archive', 'helper')
        self.assertEqual(code, 0)
        self.assertEqual(self.archived(), ['helper'])

    def test_restoring_brings_it_back(self):
        self.run_cli('archive', 'helper')
        code, _ = self.run_cli('archive', 'helper', '--restore')
        self.assertEqual(code, 0)
        self.assertEqual(self.archived(), [])

    def test_it_frees_the_vendor_slot_without_removing_anything(self):
        # The point of archiving here: the card stops holding the vendor, while
        # the environment and everything published from it stay put.
        directory = self.store.root / 'environments' / 'helper'
        (directory / 'prefix').mkdir(parents=True)
        core.atomic_json(directory / 'environment.json',
                         {'id': 'helper', 'recipe': 'klevgrand', 'status': 'ready',
                          'helper_launcher': str(directory / 'launch-helper')})
        from plugg import vendors
        self.assertEqual([c['recipe'] for c in vendors.cards(self.store)], ['klevgrand'])
        self.run_cli('archive', 'helper')
        self.assertEqual(vendors.cards(self.store), [])
        self.assertTrue((directory / 'prefix').is_dir())
        self.assertTrue((directory / 'environment.json').is_file())

    def test_an_unfinished_installation_is_not_archived_underneath_itself(self):
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='installing' WHERE id='helper'")
        code, _ = self.run_cli('archive', 'helper')
        self.assertEqual(code, 1)
        self.assertEqual(self.archived(), [])


class FailureVisibilityTests(unittest.TestCase):
    """A failed installation must not read as "nothing happened".

    Attempts live in a folded section. Drop an installer, have it fail, and the
    only evidence is behind an arrow you had no reason to open.
    """

    SOURCE = Path(__file__).resolve().parents[1] / 'plugg' / 'gui.py'

    def test_a_failure_stays_above_the_tabs_until_dismissed(self):
        # With tabs, a failure filed under History is invisible to someone
        # looking at Plug-ins -- which is exactly the "nothing happened" this
        # was meant to fix. It stays in the activity strip instead.
        text = self.SOURCE.read_text()
        self.assertIn("if job['status'] not in ('failed', 'cancelled', 'needs_attention')", text)
        placed = text.index("if job['status'] not in ('failed', 'cancelled', 'needs_attention')")
        strip = text.index('content.append(self.activity)')
        self.assertLess(strip, placed)
        # Dismissing forgets the attempt rather than filing it somewhere else.
        self.assertIn('self.discard_job(j)', text)
        self.assertIn('self.store.discard(job_id)', text)


class StuckJobTests(unittest.TestCase):
    """A worker that gives up must not leave the row saying it is about to start.

    Losing a race for a setup lock is ordinary: drop the same installer twice
    and the second worker exits immediately. It used to exit with the job still
    reading "queued", owned by no process, which nothing would ever move -- a
    spinner for work that had already given up.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = core.Store(root / 'store', root / 'published')
        with self.store.db() as db:
            db.execute('INSERT INTO jobs(id,name,installer,kind,hash,status,message,created,updated,env_id)'
                       ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                       ('job', 'Klevgrand Helper', '/none.exe', 'exe', 'h', 'queued', 'Preparing installation',
                        1.0, 1.0, 'job'))

    def status(self):
        return self.store.job('job')['status']

    def test_a_worker_that_loses_a_race_marks_the_job_failed(self):
        with patch('plugg.core._work', side_effect=core.HostError('This operation is already running.')):
            with self.assertRaisesRegex(core.HostError, 'already running'):
                core.work(self.store, 'job')
        self.assertEqual(self.status(), 'failed')
        self.assertIn('already running', self.store.job('job')['message'])

    def test_cancellation_is_recorded_as_cancellation_not_failure(self):
        with patch('plugg.core._work', side_effect=core.Cancelled('Cancelled')):
            with self.assertRaises(core.Cancelled):
                core.work(self.store, 'job')
        self.assertEqual(self.status(), 'cancelled')

    def test_a_job_the_worker_already_settled_is_left_alone(self):
        def settled(store, job_id, rescan=False):
            store.update(job_id, 'needs_attention', 'The installer reported a problem')
            raise core.HostError('and then raised')
        with patch('plugg.core._work', side_effect=settled):
            with self.assertRaises(core.HostError):
                core.work(self.store, 'job')
        self.assertEqual(self.status(), 'needs_attention')
        self.assertEqual(self.store.job('job')['message'], 'The installer reported a problem')

    def test_a_successful_run_is_untouched(self):
        with patch('plugg.core._work', return_value='done'):
            self.assertEqual(core.work(self.store, 'job'), 'done')
        self.assertEqual(self.status(), 'queued')


class ArrivalFeedbackTests(unittest.TestCase):
    """Dropping a file must show something before the slow part finishes.

    Copying an installer and preparing an environment take minutes, and until
    one of them wrote a record there was nothing on screen saying the drop had
    registered. The natural response is to drop it again -- and every one of
    those was a real job.
    """

    SOURCE = Path(__file__).resolve().parents[1] / 'plugg' / 'gui.py'

    def setUp(self):
        self.text = self.SOURCE.read_text()

    def test_the_same_file_dropped_twice_is_taken_in_once(self):
        self.assertIn('if key in self.pending:', self.text)
        self.assertIn('self.pending[key] = path.name', self.text)
        self.assertIn('self.pending.pop(key, None)', self.text)

    def test_arrival_is_shown_before_the_work_starts(self):
        # The refresh compares a tuple; a pending file has to be part of it or
        # the interface will not redraw to show it.
        self.assertIn('tuple(sorted(self.pending.values()))', self.text)
        self.assertIn("self.activity.append(self.busy_row('Adding '", self.text)

    def test_running_work_is_shown_where_it_was_started(self):
        activity = self.text.index('content.append(self.activity)')
        views = self.text.index('content.append(self.stack)')
        self.assertLess(activity, views, 'Work in progress belongs under the drop area, above '
                                         'every tab, not filed inside one of them.')
        self.assertIn('Gtk.Spinner(spinning=True)', self.text)


class CancelTests(unittest.TestCase):
    """Cancel must end the job, not only leave a message for a process.

    The flag is read by a running worker. A job whose worker never started, or
    died before claiming it, has no reader -- so the button and the command
    both did nothing, quietly, and the row waited for a reply that could not
    come.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = core.Store(root / 'store', root / 'published')
        with self.store.db() as db:
            db.execute('INSERT INTO jobs(id,name,installer,kind,hash,status,message,created,updated,env_id)'
                       ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                       ('job', 'Klevgrand Helper', '/none.exe', 'exe', 'h', 'queued',
                        'Preparing installation', 1.0, 1.0, 'job'))
        self.lock = self.store.root / 'jobs' / 'job' / 'job.lock'
        self.lock.parent.mkdir(parents=True, exist_ok=True)

    def test_a_job_no_worker_owns_is_ended_immediately(self):
        self.store.cancel('job')
        self.assertEqual(self.store.job('job')['status'], 'cancelled')

    def test_a_job_a_worker_still_owns_is_only_asked_to_stop(self):
        import fcntl
        with self.lock.open('a') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.store.cancel('job')
        # The worker is alive and will see the flag and settle the job itself;
        # deciding on its behalf would race with whatever it is part-way
        # through doing.
        self.assertEqual(self.store.job('job')['status'], 'queued')
        self.assertTrue(self.store.job('job')['cancel'])

    def test_a_finished_job_is_not_reopened_as_cancelled(self):
        self.store.update('job', 'ready', 'Installed')
        self.store.cancel('job')
        self.assertEqual(self.store.job('job')['status'], 'ready')

    def test_a_cancelled_job_can_then_be_archived(self):
        # The sequence a person actually needs: end it, then get it off screen.
        self.store.cancel('job')
        self.store.archive('job')
        self.assertEqual([j['id'] for j in self.store.jobs() if j['archived']], ['job'])


class QueueAffordanceTests(unittest.TestCase):
    """Adding a second installer while the first runs is allowed, and said out loud."""

    SOURCE = Path(__file__).resolve().parents[1] / 'plugg' / 'gui.py'

    def test_the_drop_area_stays_open_and_reports_what_is_under_way(self):
        text = self.SOURCE.read_text()
        # Replacing the drop area would forbid the useful case -- queueing a
        # different product -- to prevent the accidental one, which the
        # same-file guard already prevents.
        self.assertIn('self.drop_note.set_visible(bool(working))', text)
        self.assertIn('You can add another.', text)
        self.assertNotIn('self.drop_area.set_visible(False)', text)

    def test_cancelling_from_the_card_goes_through_the_store(self):
        text = self.SOURCE.read_text()
        self.assertIn('self.cancel_job(j)', text)
        self.assertIn('self.store.cancel(job_id)', text)


class DuplicateInstallerTests(unittest.TestCase):
    """The same file twice is the same product, and the bytes are what say so."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = core.Store(self.root / 'store', self.root / 'published')
        self.source = self.root / 'Vendor Installer.exe'
        fake_pe(self.source)
        self.digest = core.digest(self.source)

    def add(self, status, name='Vendor Installer', fingerprint=None, job_id='old'):
        with self.store.db() as db:
            db.execute('INSERT INTO jobs(id,name,installer,kind,hash,status,message,created,updated,env_id)'
                       ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (job_id, name, str(self.source), 'exe', fingerprint or self.digest,
                        status, 'm', 1.0, 1.0, job_id))

    def test_a_second_copy_while_the_first_is_running_is_refused(self):
        self.add('preparing')
        with self.assertRaises(core.DuplicateInstaller) as caught:
            self.store.ingest(self.source)
        self.assertFalse(caught.exception.replaceable)

    def test_a_finished_installation_offers_to_be_done_over(self):
        self.add('ready')
        with self.assertRaises(core.DuplicateInstaller) as caught:
            self.store.ingest(self.source)
        self.assertTrue(caught.exception.replaceable)
        self.assertEqual(caught.exception.job['id'], 'old')

    def test_a_new_version_under_the_same_name_is_not_a_duplicate(self):
        # The case that must keep working: next year's installer arrives under
        # exactly the name this one had. Different bytes, different product.
        self.add('ready')
        self.store.duplicate('b' * 64)

    def test_a_failed_attempt_can_be_added_again(self):
        self.add('failed')
        self.store.duplicate(self.digest)

    def test_an_archived_installation_can_be_added_again(self):
        self.add('ready')
        self.store.archive('old')
        self.store.duplicate(self.digest)

    def test_replacing_archives_the_old_one_and_retires_its_plug_ins(self):
        self.add('ready')
        with self.store.db() as db:
            db.execute('INSERT INTO plugins(id,env_id,name,module,hash,status,metadata,publication,message)'
                       " VALUES(?,?,?,?,?,?,?,?,?)",
                       ('p1', 'old', 'Thing', 'Thing.vst3', 'h', 'ready', '{}', '', 'ok'))
        self.store.duplicate(self.digest, replace=True)
        self.assertEqual([j['id'] for j in self.store.jobs() if j['archived']], ['old'])
        self.assertEqual([p['status'] for p in self.store.plugins()], ['removed'])

    def test_replacing_an_installation_that_published_nothing_still_works(self):
        self.add('ready')
        self.store.duplicate(self.digest, replace=True)
        self.assertEqual([j['id'] for j in self.store.jobs() if j['archived']], ['old'])


class ReplaceOfferTests(unittest.TestCase):
    """The second drop of a finished install is usually "do that one over"."""

    SOURCE = Path(__file__).resolve().parents[1] / 'plugg' / 'gui.py'

    def test_the_two_duplicate_cases_are_answered_differently(self):
        text = self.SOURCE.read_text()
        self.assertIn('except DuplicateInstaller as exc:', text)
        self.assertIn('if exc.replaceable:', text)
        self.assertIn('self.offer_replace, path, str(exc)', text)
        # Nothing to offer while it is still running but waiting.
        self.assertIn("self.message, 'Already being added'", text)

    def test_replacing_is_asked_for_and_says_what_it_does(self):
        text = self.SOURCE.read_text()
        self.assertIn("buttons=['Cancel', 'Install again']", text)
        self.assertIn('self.install(path, replace=True)', text)
        self.assertIn('archives that installation and retires the', text)


class DiscardTests(unittest.TestCase):
    """Forgetting an attempt, now that the environment can be seen on its own.

    A failed setup was kept because it pointed at an environment that might
    already hold installed or activation data. The environments view shows that
    environment directly, so the pointer had become the only thing standing
    between someone and a window with nothing dead in it.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = core.Store(root / 'store', root / 'published')
        self.directory = self.store.root / 'jobs' / 'job'
        (self.directory / 'payload').mkdir(parents=True)
        (self.directory / 'payload/installer.exe').write_bytes(b'x' * 100)
        self.environment = self.store.root / 'environments' / 'env'
        (self.environment / 'prefix').mkdir(parents=True)
        with self.store.db() as db:
            db.execute('INSERT INTO jobs(id,name,installer,kind,hash,status,message,created,updated,env_id)'
                       ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                       ('job', 'Attempt', '/none.exe', 'exe', 'h', 'failed', 'It broke', 1.0, 1.0, 'env'))

    def test_discarding_forgets_the_record(self):
        self.store.discard('job')
        self.assertEqual(self.store.jobs(), [])

    def test_the_environment_it_made_is_left_alone(self):
        # It may hold installed products or activation data. Deleting it is a
        # separate, deliberate act with its own typed confirmation.
        self.store.discard('job')
        self.assertTrue((self.environment / 'prefix').is_dir())

    def test_the_installer_copy_goes_with_the_record_that_kept_it(self):
        self.store.discard('job')
        self.assertFalse(self.directory.exists())

    def test_an_archived_marker_does_not_survive_its_job(self):
        self.store.archive('job')
        self.store.discard('job')
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM archived_jobs').fetchone()[0], 0)

    def test_an_unfinished_attempt_is_not_discarded_underneath_itself(self):
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='installing' WHERE id='job'")
        with self.assertRaisesRegex(core.HostError, 'Cancel this installation'):
            self.store.discard('job')
        self.assertEqual(len(self.store.jobs()), 1)

    def test_it_refuses_while_a_worker_still_holds_the_job(self):
        import fcntl
        with (self.directory / 'job.lock').open('a') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(core.HostError, 'still working'):
                self.store.discard('job')
        self.assertEqual(len(self.store.jobs()), 1)

    def test_the_environment_then_shows_as_referred_to_by_nothing(self):
        # Which is how it becomes findable and deletable, rather than lost.
        from plugg import environments
        core.atomic_json(self.environment / 'environment.json', {'id': 'env', 'recipe': 'klevgrand'})
        self.store.discard('job')
        record = next(r for r in environments.survey(self.store) if r['id'] == 'env')
        self.assertTrue(record['orphaned'])


class ArchivedButLiveTests(unittest.TestCase):
    """Archiving a vendor whose plug-ins are still in use must not hide it.

    Archiving means "this installation is finished with". An environment still
    serving three plug-ins to a DAW is not finished with, and hiding its card
    left no way to open the manager those plug-ins came from -- nor, once the
    attempts list was gone, any way to undo it.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = core.Store(root / 'store', root / 'published')
        self.directory = self.store.root / 'environments' / 'vendor'
        (self.directory / 'prefix').mkdir(parents=True)
        core.atomic_json(self.directory / 'environment.json', {
            'id': 'vendor', 'recipe': 'pace-service-experiment', 'status': 'ready',
            'helper_launcher': str(self.directory / 'launch-helper')})
        with self.store.db() as db:
            db.execute('INSERT INTO jobs(id,name,installer,kind,hash,status,message,created,updated,env_id)'
                       ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                       ('vendor', 'UA Connect', '/none.exe', 'exe', 'h', 'ready', 'm', 1.0, 1.0, 'vendor'))

    def publish(self, status='ready'):
        with self.store.db() as db:
            db.execute('INSERT INTO plugins(id,env_id,name,module,hash,status,metadata,publication,message)'
                       ' VALUES(?,?,?,?,?,?,?,?,?)',
                       ('p1', 'vendor', 'LA-2A', 'LA2A.vst3', 'h', status, '{}', '', 'ok'))

    def cards(self):
        from plugg import vendors
        return vendors.cards(self.store)

    def test_an_archived_vendor_still_publishing_keeps_its_card(self):
        self.publish()
        self.store.archive('vendor')
        self.assertEqual([c['job'] for c in self.cards()], ['vendor'])

    def test_an_archived_vendor_publishing_nothing_stays_hidden(self):
        # The case archiving is for: a finished attempt, out of the way, and
        # its vendor slot released for a fresh install.
        self.store.archive('vendor')
        self.assertEqual(self.cards(), [])

    def test_retired_plug_ins_do_not_keep_a_card_alive(self):
        self.publish(status='removed')
        self.store.archive('vendor')
        self.assertEqual(self.cards(), [])
