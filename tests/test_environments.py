"""Reporting on environments without offering to manage them.

Choosing which prefix a plug-in lands in is how people break their own
installations, so the manager does not offer it. But that also hid the answers
to fair questions -- how many are there, which is the twelve gigabytes, which
one holds the licences -- and left a directory listing and a guess.
"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugg import core, environments, licensing


class MeasureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_it_adds_up_what_is_there(self):
        (self.root / 'a').write_bytes(b'x' * 100)
        (self.root / 'deep').mkdir()
        (self.root / 'deep/b').write_bytes(b'y' * 50)
        self.assertEqual(environments.measure(self.root), 150)

    def test_a_hard_link_is_not_counted_twice(self):
        # A prefix is full of links into shared runtimes. Counting each one
        # would report a number far larger than what deleting this would free,
        # which is the only reason anyone asked.
        (self.root / 'a').write_bytes(b'x' * 100)
        os.link(self.root / 'a', self.root / 'b')
        self.assertEqual(environments.measure(self.root), 100)

    def test_a_symlink_is_not_followed(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'big').write_bytes(b'x' * 1000)
        inside = self.root / 'env'
        inside.mkdir()
        (inside / 'link').symlink_to(outside)
        (inside / 'own').write_bytes(b'y' * 10)
        self.assertEqual(environments.measure(inside), 10)

    def test_an_unreadable_directory_does_not_stop_the_count(self):
        (self.root / 'a').write_bytes(b'x' * 10)
        blocked = self.root / 'blocked'
        blocked.mkdir()
        (blocked / 'c').write_bytes(b'z' * 10)
        blocked.chmod(0o000)
        self.addCleanup(blocked.chmod, 0o700)
        self.assertGreaterEqual(environments.measure(self.root), 10)


class SurveyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = core.Store(root / 'store', root / 'published')
        self.make('alpha', {'recipe': 'klevgrand', 'vendor': 'Klevgrand'})
        self.make('beta', {'recipe': 'standalone-vst3'})
        self.make('orphan', {'recipe': 'klevgrand'})
        self.job('j1', 'alpha', 'ready', archived=False)
        self.job('j2', 'beta', 'ready', archived=True)
        self.plugin('p1', 'alpha', 'Skaka', 'ready')
        self.plugin('p2', 'alpha', 'Slammer', 'removed')

    def make(self, env_id, config):
        directory = self.store.root / 'environments' / env_id
        (directory / 'prefix').mkdir(parents=True)
        core.atomic_json(directory / 'environment.json', {'id': env_id, **config})
        return directory

    def job(self, job_id, env_id, status, archived):
        with self.store.db() as db:
            db.execute('INSERT INTO jobs(id,name,installer,kind,hash,status,message,created,updated,env_id)'
                       ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (job_id, job_id, '/none.exe', 'exe', job_id, status, 'm', 1.0, 1.0, env_id))
            if archived:
                db.execute('INSERT INTO archived_jobs VALUES(?)', (job_id,))

    def plugin(self, plugin_id, env_id, name, status):
        with self.store.db() as db:
            db.execute('INSERT INTO plugins(id,env_id,name,module,hash,status,metadata,publication,message)'
                       ' VALUES(?,?,?,?,?,?,?,?,?)',
                       (plugin_id, env_id, name, name + '.vst3', 'h', status, '{}', '', 'ok'))

    def find(self, env_id):
        return next(r for r in environments.survey(self.store) if r['id'] == env_id)

    def test_every_environment_on_disk_is_reported(self):
        self.assertEqual(sorted(r['id'] for r in environments.survey(self.store)),
                         ['alpha', 'beta', 'orphan'])

    def test_published_and_retired_plug_ins_are_separated(self):
        alpha = self.find('alpha')
        self.assertEqual(alpha['plugins'], ['Skaka'])
        self.assertEqual(alpha['retired'], ['Slammer'])

    def test_an_environment_whose_jobs_are_all_archived_is_still_on_disk(self):
        # This is the one someone is looking for when they ask about space:
        # out of the interface, still costing gigabytes.
        beta = self.find('beta')
        self.assertFalse(beta['in_use'])
        self.assertFalse(beta['orphaned'])

    def test_an_environment_no_job_refers_to_is_flagged(self):
        self.assertTrue(self.find('orphan')['orphaned'])

    def test_an_unrecorded_environment_gets_no_line_at_all(self):
        # The absence of a note is not a status, and "Nothing recorded" on
        # every row is a question nobody asked answered over and over.
        self.assertFalse(self.find('alpha')['protected'])
        self.assertIsNone(environments.licensing_line(self.find('alpha')))

    def test_a_protected_environment_reports_what_it_holds(self):
        directory = self.store.root / 'environments' / 'alpha'
        (directory / 'prefix/system.reg').write_text(
            'WINE REGISTRY Version 2\n\n[Software\\\\Microsoft\\\\Cryptography] 1\n'
            '"MachineGuid"="0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"\n')
        licensing.protect(directory, [{'name': 'Klevgrand', 'recovery': 'deactivate-first'}])
        alpha = self.find('alpha')
        self.assertTrue(alpha['protected'])
        # The consequence, in the terms someone deciding whether to delete it
        # is thinking in -- not a classification of its licences.
        # A standing note about what the environment was set up holding, not
        # a claim about what is activated this minute. Nothing here asks a
        # vendor, and nothing should.
        # Skaka is published here but was never itself recorded, so the line
        # says so rather than implying the list is complete.
        line = environments.licensing_line(alpha)
        self.assertIn('Set up for Klevgrand; deactivate wherever they were activated before '
                      'rebuilding, if you have not already', line)
        self.assertIn('1 not yet recorded: Skaka', line)

    def test_an_unreadable_record_is_reported_as_unknown_not_as_safe(self):
        (self.store.root / 'environments/alpha/licensing.json').write_text('{ not json')
        alpha = self.find('alpha')
        self.assertIsNone(alpha['protected'])
        self.assertIn('unreadable', environments.licensing_line(alpha))

    def test_the_summary_names_the_vendor_or_what_the_environment_is_for(self):
        self.assertEqual(environments.summarize(self.find('alpha')), 'Klevgrand')
        self.assertEqual(environments.summarize(self.find('beta')), 'Directly imported plug-ins')

    def test_the_survey_never_creates_anything(self):
        before = sorted(p.name for p in (self.store.root / 'environments').iterdir())
        environments.survey(self.store)
        self.assertEqual(sorted(p.name for p in (self.store.root / 'environments').iterdir()), before)


class ReadableTests(unittest.TestCase):
    def test_sizes_are_rounded_for_comparison_not_accounting(self):
        self.assertEqual(environments.readable(512), '512 B')
        self.assertEqual(environments.readable(2048), '2 KB')
        self.assertEqual(environments.readable(5 * 1024 * 1024), '5.0 MB')
        self.assertEqual(environments.readable(3 * 1024 ** 3), '3.0 GB')

    def test_an_unmeasured_environment_does_not_claim_to_be_empty(self):
        self.assertEqual(environments.readable(None), 'Not measured')



class PresentationTests(unittest.TestCase):
    """How the environments view behaves, read from the source.

    GTK is not importable here. These cover the two decisions that are easy to
    undo by accident: that the view never offers to manage an environment, and
    that surveying and measuring do not run on every refresh.
    """

    SOURCE = Path(__file__).resolve().parents[1] / 'plugg' / 'gui.py'

    def setUp(self):
        self.text = self.SOURCE.read_text()

    def test_the_view_reports_and_does_not_manage(self):
        # Choosing or destroying a prefix is not offered. Opening the folder is
        # not management: it hands the question to the file manager.
        for forbidden in ('shutil.rmtree', 'forget_environment(', 'move_environment'):
            self.assertNotIn(forbidden, self.text)

    def test_surveying_waits_until_the_tab_is_open(self):
        # A survey reads a licensing record and a registry hive per
        # environment: nothing once, a stutter on every library change.
        # Surveying reads a licensing record and a registry hive per
        # environment, so it happens only while the library is shown.
        self.assertIn("if self.tab == 'library':\n                self.library_view.update(survey.survey(self.store)",
                      self.text)

    def test_sizes_are_measured_off_the_interface_thread_and_cached(self):
        self.assertIn('def measure_environments', self.text)
        self.assertIn('threading.Thread(target=task, daemon=True).start()', self.text)
        self.assertIn("if force or record['id'] not in self.sizes:", self.text)

    def test_the_action_names_the_question_rather_than_the_machinery(self):
        # "Record licensing" was jargon for a plain question: if this is
        # rebuilt or deleted, do you lose something you cannot get back?
        # Not a question the app answers -- a thing you tell it. An earlier
        # label read as a query the app would compute, and it is a form.
        # Not a question the app answers, and not a claim about live state
        # either: it is how the licences behave, which does not change.
        view = (self.SOURCE.parent / 'library_view.py').read_text()
        self.assertIn("item('Licence handling ✓' if record.get('protected') else 'Licence handling…',", view)
        self.assertNotIn("label='Record licensing", self.text)
        self.assertNotIn("label='Cost of rebuilding", self.text)
        self.assertNotIn("label='Note what is activated", self.text)
        self.assertIn('Not what is activated right now', self.text)
        self.assertIn('licensing.protect(Path(record[', self.text)

    def test_machine_identity_is_stated_once_and_not_as_a_warning(self):
        # It appeared in a warning colour on nearly every row, where it was
        # neither a warning nor actionable -- which teaches the reader to
        # ignore the colour.
        view = (self.SOURCE.parent / 'library_view.py').read_text()
        self.assertEqual(view.count('survey.identity_summary(records)'), 1)
        self.assertIn("box.append(text(identity, 'lib-note', wrap=True))", view)
        self.assertNotIn("'Not seen as this computer'", self.text)
        self.assertNotIn('survey.identity_line', self.text)

    def test_the_form_refuses_to_invent_a_product_or_a_count(self):
        self.assertIn('if not items:', self.text)
        self.assertIn("if not remaining.strip().isdigit():", self.text)

    def test_each_plug_in_gets_its_own_answer(self):
        # A directly-imported environment is a grab bag: one plug-in free, the
        # next serial-based, the next bound to a machine. One class for all
        # three means picking a wrong one.
        self.assertIn('for index, name in enumerate(listed):', self.text)
        self.assertIn('rows.append((name, chooser))', self.text)
        self.assertIn('for name, chooser in rows:', self.text)

    def test_what_was_recorded_can_be_seen_and_changed_afterwards(self):
        view = (self.SOURCE.parent / 'library_view.py').read_text()
        self.assertIn("'Licence handling ✓'", view)
        self.assertIn('tooltip=survey.recorded_detail(record) or', view)


class RemovalTests(unittest.TestCase):
    """Deleting an environment cannot be undone, so it cannot be done absently.

    A prefix is the installed products, their settings and, for some vendors,
    the activation itself. No recovery point covers it: a recovery point holds
    the identity files, a few kilobytes, not the gigabytes that made someone
    want the space back.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = core.Store(root / 'store', root / 'published')
        self.directory = self.store.root / 'environments' / 'alpha'
        (self.directory / 'prefix/drive_c').mkdir(parents=True)
        (self.directory / 'prefix/system.reg').write_text(
            'WINE REGISTRY Version 2\n\n[Software\\\\Microsoft\\\\Cryptography] 1\n'
            '"MachineGuid"="0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"\n')
        core.atomic_json(self.directory / 'environment.json',
                         {'id': 'alpha', 'recipe': 'klevgrand', 'vendor': 'Klevgrand'})

    def record(self):
        return next(r for r in environments.survey(self.store) if r['id'] == 'alpha')

    def job(self, job_id, archived):
        with self.store.db() as db:
            db.execute('INSERT INTO jobs(id,name,installer,kind,hash,status,message,created,updated,env_id)'
                       ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (job_id, job_id, '/none.exe', 'exe', job_id, 'ready', 'm', 1.0, 1.0, 'alpha'))
            if archived:
                db.execute('INSERT INTO archived_jobs VALUES(?)', (job_id,))

    def test_the_wrong_words_delete_nothing(self):
        record = self.record()
        for wrong in ('', 'yes', 'delete alpha', 'DELETE KLEVGRAND '):
            with self.assertRaises(core.HostError, msg=repr(wrong)):
                environments.remove(self.store, record, wrong)
        self.assertTrue(self.directory.is_dir())

    def test_the_phrase_names_the_environment_when_nothing_is_at_stake(self):
        self.assertEqual(environments.removal_phrase(self.record()), 'DELETE KLEVGRAND')

    def test_a_protected_environment_demands_the_phrase_about_its_licences(self):
        licensing.protect(self.directory, [{'name': 'Klevgrand', 'recovery': 'deactivate-first'}])
        # Not the folder's name: what is actually at stake.
        self.assertEqual(environments.removal_phrase(self.record()),
                         licensing.CONFIRMATION['deactivate-first'])

    def test_the_right_words_delete_it(self):
        record = self.record()
        environments.remove(self.store, record, environments.removal_phrase(record))
        self.assertFalse(self.directory.exists())

    def test_a_protected_environment_goes_through_the_guard(self):
        licensing.protect(self.directory, [{'name': 'Klevgrand', 'recovery': 'deactivate-first'}])
        record = self.record()
        environments.remove(self.store, record, environments.removal_phrase(record))
        self.assertFalse(self.directory.exists())

    def test_an_environment_recorded_as_holding_nothing_licensed_can_be_deleted(self):
        # Protected, but only with free plug-ins: the phrase is DELETE
        # <VENDOR>, and the guard still has to accept the removal.
        licensing.protect(self.directory, [{'name': 'Free Synth', 'recovery': 'unlicensed'}])
        record = self.record()
        self.assertTrue(record['protected'])
        self.assertEqual(environments.removal_phrase(record), 'DELETE KLEVGRAND')
        environments.remove(self.store, record, 'DELETE KLEVGRAND')
        self.assertFalse(self.directory.exists())

    def test_the_records_of_what_lived_here_go_with_it(self):
        # Asking someone to archive them first was asking for a ritual on the
        # way to the same place: they describe what was in this environment.
        self.job('old', archived=False)
        record = self.record()
        environments.remove(self.store, record, environments.removal_phrase(record))
        self.assertFalse(self.directory.exists())
        self.assertEqual(self.store.jobs(), [])

    def test_an_installation_still_running_stops_it(self):
        self.job('live', archived=False)
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='installing' WHERE id='live'")
        record = self.record()
        self.assertTrue(any('Cancel it first' in r for r in environments.blockers(self.store, record)))
        with self.assertRaisesRegex(core.HostError, 'Cancel it first'):
            environments.remove(self.store, record, environments.removal_phrase(record))
        self.assertTrue(self.directory.is_dir())

    def test_it_refuses_while_something_is_running_inside(self):
        record = self.record()
        with patch('plugg.vendors.program_names', return_value=['Helper.exe']):
            self.assertTrue(any('Helper.exe' in r for r in environments.blockers(self.store, record)))
            with self.assertRaisesRegex(core.HostError, 'still running'):
                environments.remove(self.store, record, environments.removal_phrase(record))
        self.assertTrue(self.directory.is_dir())

    def test_an_idle_session_does_not_block_and_is_stopped_first(self):
        # It stays up for minutes after the last plug-in closes. That is not a
        # reason to make someone wait with the dialog open.
        (self.directory / 'session.json').write_text('{}')
        record = self.record()
        with patch('plugg.vendors.program_names', return_value=[]), \
                patch('plugg.proton_session.foreign_prefix_processes', return_value=[42]), \
                patch('plugg.proton_session.stop_idle_session') as stop:
            self.assertEqual(environments.blockers(self.store, record), [])
            environments.remove(self.store, record, environments.removal_phrase(record))
        stop.assert_called_once_with(self.directory / 'session.json')
        self.assertFalse(self.directory.exists())

    def test_a_session_that_will_not_stop_keeps_everything_and_the_phrase(self):
        licensing.protect(self.directory, [{'name': 'Klevgrand', 'recovery': 'deactivate-first'}])
        (self.directory / 'session.json').write_text('{}')
        record = self.record()
        with patch('plugg.vendors.program_names', return_value=[]), \
                patch('plugg.proton_session.foreign_prefix_processes', return_value=[42]), \
                patch('plugg.proton_session.stop_idle_session',
                      side_effect=RuntimeError('Vendor runtime did not stop.')):
            with self.assertRaisesRegex(core.HostError, 'did not stop'):
                environments.remove(self.store, record, environments.removal_phrase(record))
        self.assertTrue(self.directory.is_dir())
        # Refused before the acknowledgement was recorded, so nothing was used up.
        self.assertIsNone(licensing.read(self.directory).get('acknowledgement'))

    def test_nothing_stands_in_the_way_of_a_finished_environment(self):
        self.job('old', archived=True)
        self.assertEqual(environments.blockers(self.store, self.record()), [])

    def test_a_link_into_another_library_unlinks_rather_than_deleting_it(self):
        # An older root adopted rather than copied. The link is the whole of
        # this library's claim; the directory at the far end is not ours.
        elsewhere = Path(self.tmp.name) / 'other-library' / 'environments' / 'beta'
        (elsewhere / 'prefix').mkdir(parents=True)
        core.atomic_json(elsewhere / 'environment.json', {'id': 'beta', 'vendor': 'Klevgrand'})
        link = self.store.root / 'environments' / 'beta'
        link.symlink_to(elsewhere)
        record = next(r for r in environments.survey(self.store) if r['id'] == 'beta')
        result = environments.remove(self.store, record, environments.removal_phrase(record))
        self.assertFalse(link.is_symlink())
        self.assertTrue(elsewhere.is_dir(), 'another library\'s data must survive')
        self.assertEqual(result['unlinked'], str(elsewhere))

    def test_what_it_published_is_retired_so_a_daw_stops_offering_it(self):
        published = self.store.publication / 'ph-alpha.vst3'
        published.parent.mkdir(parents=True, exist_ok=True)
        published.symlink_to(self.directory / 'prefix/Thing.vst3')
        with self.store.db() as db:
            db.execute('INSERT INTO plugins(id,env_id,name,module,hash,status,metadata,publication,message)'
                       ' VALUES(?,?,?,?,?,?,?,?,?)',
                       ('p1', 'alpha', 'Thing', 'Thing.vst3', 'h', 'ready', '{}', str(published), 'ok'))
        record = self.record()
        result = environments.remove(self.store, record, environments.removal_phrase(record))
        self.assertEqual(result['retired'], 1)
        self.assertEqual([p['status'] for p in self.store.plugins()], ['removed'])
        self.assertFalse(published.is_symlink())

    def test_it_will_not_delete_something_outside_the_library(self):
        outside = Path(self.tmp.name) / 'elsewhere'
        (outside / 'prefix').mkdir(parents=True)
        record = dict(self.record(), path=str(outside))
        with self.assertRaisesRegex(core.HostError, 'Not an environment of this library'):
            environments.remove(self.store, record, environments.removal_phrase(record))
        self.assertTrue(outside.is_dir())

    def test_a_name_that_is_a_path_is_refused(self):
        for bad in ('../escape', 'a/b', '..'):
            record = dict(self.record(), id=bad)
            with self.assertRaises(core.HostError, msg=bad):
                environments.remove(self.store, record, environments.removal_phrase(record))


class BundleTests(unittest.TestCase):
    """A bundle is the Linux-side adapter a DAW loads for one Windows plug-in.

    Unpublishing keeps it, so the plug-in can be published again. Deleting the
    environment it loads from leaves nothing to load, so the bundle goes too,
    and any left over from before are listed for cleanup.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = core.Store(root / 'store', root / 'published')
        for env_id in ('alpha', 'beta'):
            directory = self.store.root / 'environments' / env_id
            (directory / 'prefix/drive_c/VST3').mkdir(parents=True)
            core.atomic_json(directory / 'environment.json', {'id': env_id, 'vendor': env_id.title()})

    def bundle(self, name, env_id, publish=False):
        module = self.store.root / 'environments' / env_id / 'prefix/drive_c/VST3' / name
        module.write_bytes(b'MZ')
        bundle = self.store.root / 'bundles' / name
        (bundle / 'Contents/x86_64-linux').mkdir(parents=True)
        (bundle / 'Contents/x86_64-linux/.plugg-managed').write_text('1\n')
        (bundle / 'Contents/x86_64-win').mkdir()
        (bundle / 'Contents/x86_64-win' / name).symlink_to(module)
        core.atomic_json(bundle / 'plugg.json', {'id': name, 'environment': env_id})
        if publish:
            self.store.publication.mkdir(parents=True, exist_ok=True)
            (self.store.publication / name).symlink_to(bundle, target_is_directory=True)
        return bundle, module

    def record(self, env_id):
        return next(r for r in environments.survey(self.store) if r['id'] == env_id)

    def test_deleting_an_environment_deletes_its_bundles_and_only_those(self):
        mine, _ = self.bundle('Mine.vst3', 'alpha')
        theirs, _ = self.bundle('Theirs.vst3', 'beta')
        record = self.record('alpha')
        result = environments.remove(self.store, record, environments.removal_phrase(record))
        self.assertEqual(result['bundles_removed'], 1)
        self.assertFalse(mine.exists())
        self.assertTrue(theirs.is_dir())

    def test_a_bundle_whose_plug_in_is_gone_is_a_leftover(self):
        bundle, module = self.bundle('Gone.vst3', 'alpha')
        self.assertEqual(environments.dead_bundles(self.store), [])
        module.unlink()
        self.assertEqual([b['name'] for b in environments.dead_bundles(self.store)], ['Gone.vst3'])
        environments.remove_dead_bundle(self.store, 'Gone.vst3')
        self.assertFalse(bundle.exists())

    def test_a_bundle_a_daw_can_still_see_is_never_a_leftover(self):
        bundle, module = self.bundle('Seen.vst3', 'alpha', publish=True)
        module.unlink()
        self.assertEqual(environments.dead_bundles(self.store), [])
        with self.assertRaises(core.HostError):
            environments.remove_dead_bundle(self.store, 'Seen.vst3')
        self.assertTrue(bundle.is_dir())

    def test_only_bundles_this_library_built_are_touched(self):
        stray = self.store.root / 'bundles' / 'Stray.vst3' / 'Contents/x86_64-win'
        stray.mkdir(parents=True)
        (stray / 'Stray.vst3').symlink_to(self.store.root / 'nowhere')
        self.assertEqual(environments.dead_bundles(self.store), [])
        for bad in ('../environments', 'a/b', '..', ''):
            with self.assertRaises(core.HostError, msg=bad):
                environments.remove_dead_bundle(self.store, bad)


class RemovalPresentationTests(unittest.TestCase):
    """The destructive path stays out of the interface layer."""

    SOURCE = Path(__file__).resolve().parents[1] / 'plugg' / 'gui.py'

    def setUp(self):
        self.text = self.SOURCE.read_text()

    def test_the_interface_asks_but_never_deletes_anything_itself(self):
        # Every check -- what still refers to it, what is running in it, what
        # the guard says -- lives where it can be tested without GTK.
        self.assertNotIn('shutil.rmtree', self.text)
        self.assertIn('survey.remove(self.store, record, confirmation)', self.text)

    def test_the_button_stays_dead_until_the_words_match_exactly(self):
        self.assertIn('confirm.set_sensitive(False)', self.text)
        self.assertIn("entry.get_text() == phrase", self.text)

    def test_the_dialog_says_what_will_not_survive(self):
        self.assertIn('It cannot be undone, and no recovery point covers it.', self.text)
        self.assertIn("if record['protected']:", self.text)
        self.assertIn('Deactivate them in the vendor', self.text)

    def test_what_stops_it_is_said_before_anyone_is_asked_to_type(self):
        # Asking for a confirmation phrase and only then refusing wastes the
        # one moment the person was paying full attention.
        self.assertIn('stopped = survey.blockers(self.store, record)', self.text)
        self.assertIn('typed.set_sensitive(not stopped)', self.text)
        self.assertIn("label(reason, 'error', True)", self.text)
        self.assertIn('not stopped and entry.get_text() == phrase', self.text)

    def test_a_link_into_another_library_says_so_while_it_is_still_a_choice(self):
        self.assertIn('This entry is a link into another library.', self.text)
        self.assertIn("'Remove link' if linked is not None else 'Delete permanently'", self.text)

    def test_the_second_group_is_never_called_inactive(self):
        # This library knows what it published and what it was told to
        # protect. A vendor may count a machine it was never told about, so
        # claiming these are inactive would be claiming something unknown.
        view = (self.SOURCE.parent / 'library_view.py').read_text()
        self.assertNotIn('Inactive', view)
        self.assertNotIn('inactive', view.replace('knowing they are inactive', ''))
        self.assertIn('That is not proof they hold', view)

    def test_the_groups_are_separated_and_counted(self):
        # Vendors and cleanup are read with opposite intentions, so they are
        # apart: cleanup is a counted, folded section below the vendors.
        view = (self.SOURCE.parent / 'library_view.py').read_text()
        self.assertIn("Section('vendors'", view)
        self.assertIn("title.append(text('cleanup', 'lib-section-title'))", view)
        self.assertIn("plural(items, 'item')", view)

    def test_the_two_invisible_leftovers_are_now_listed(self):
        # Both were found only by looking at the disk and wondering what a
        # directory was. Neither had any route through the interface.
        self.assertIn('survey.nested_libraries(self.store)', self.text)
        self.assertIn('survey.unused_runtimes(self.store)', self.text)
        view = (self.SOURCE.parent / 'library_view.py').read_text()
        self.assertIn("'Separate library ' + library['name']", view)
        self.assertIn("'Unused runtime ' + name", view)

    def test_a_nested_library_is_deleted_on_the_same_terms_as_an_environment(self):
        # It holds environments, so it can hold activations.
        self.assertIn('survey.nested_phrase(', self.text)
        self.assertIn('run_nested_delete(dialog, nested, typed.get_text())', self.text)

    def test_reclaiming_a_runtime_needs_no_phrase(self):
        # Unlike everything else here it is recoverable: it comes back by
        # download. Making it ceremonial would teach people to type through
        # ceremonies that matter.
        start = self.text.index('def reclaim_runtime')
        body = self.text[start:self.text.index('def delete_nested')]
        self.assertNotIn('phrase', body)
        self.assertIn('survey.remove_runtime(self.store, name)', body)

    def test_the_size_it_frees_is_shown_when_it_is_known(self):
        # The reason anyone opened this dialog.
        self.assertIn("'Frees about ' + survey.readable(size)", self.text)


class RuntimeReclaimTests(unittest.TestCase):
    """A runtime outlives the last environment that used it, silently.

    Nothing ever looked, so a gigabyte of Wine stayed behind when its only
    environment went. It is the one leftover here genuinely safe to delete: it
    is provisioned by download and comes back on demand.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = core.Store(root / 'store', root / 'published')
        for name in ('proton-10.0-4-guard', 'wine-11.0-amd64-wow64', 'proton-stub'):
            (self.store.root / 'runtimes' / name).mkdir(parents=True)
            (self.store.root / 'runtimes' / name / 'file').write_bytes(b'x' * 10)
        self.env('alpha', 'proton-10.0-4-guard', where='session.json')
        self.env('beta', 'wine-11.0-amd64-wow64', where='launch-wine')

    def env(self, name, runtime, where):
        directory = self.store.root / 'environments' / name
        (directory / 'prefix').mkdir(parents=True)
        core.atomic_json(directory / 'environment.json', {'id': name})
        (directory / where).write_text(
            str(self.store.root / 'runtimes' / runtime / 'proton'))
        return directory

    def test_a_runtime_named_only_in_a_launcher_script_still_counts(self):
        # Being wrong towards "still used" costs disk. Being wrong the other
        # way deletes what a working environment needs.
        self.assertNotIn('wine-11.0-amd64-wow64', environments.unused_runtimes(self.store))

    def test_a_runtime_nothing_refers_to_is_offered(self):
        self.assertEqual(environments.unused_runtimes(self.store), ['proton-stub'])

    def test_removing_it_frees_it(self):
        result = environments.remove_runtime(self.store, 'proton-stub')
        self.assertEqual(result['freed'], 10)
        self.assertFalse((self.store.root / 'runtimes' / 'proton-stub').exists())

    def test_a_runtime_in_use_is_refused(self):
        with self.assertRaisesRegex(core.HostError, 'still used'):
            environments.remove_runtime(self.store, 'proton-10.0-4-guard')
        self.assertTrue((self.store.root / 'runtimes' / 'proton-10.0-4-guard').is_dir())

    def test_deleting_the_last_environment_makes_its_runtime_reclaimable(self):
        import shutil
        shutil.rmtree(self.store.root / 'environments' / 'beta')
        self.assertIn('wine-11.0-amd64-wow64', environments.unused_runtimes(self.store))

    def test_a_name_that_is_a_path_is_refused(self):
        for bad in ('../runtimes', 'a/b', '..'):
            with self.assertRaises(core.HostError, msg=bad):
                environments.remove_runtime(self.store, bad)


class NestedLibraryTests(unittest.TestCase):
    """A whole library nested inside this one, which no view reached.

    Setting one up for a vendor produces a complete library -- its own
    database, downloads and runtimes. Nothing listed them, so they were found
    by looking at the disk and wondering what that directory was.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = core.Store(root / 'store', root / 'published')
        self.nested = self.store.root / 'managed-libraries' / 'klevgrand'
        (self.nested / 'environments' / 'one' / 'prefix').mkdir(parents=True)
        (self.nested / 'downloads').mkdir(parents=True)
        (self.nested / 'downloads' / 'runtime.tar').write_bytes(b'x' * 100)

    def test_a_nested_library_is_listed_with_what_it_holds(self):
        found, = environments.nested_libraries(self.store)
        self.assertEqual(found['name'], 'klevgrand')
        self.assertEqual(found['environments'], 1)

    def test_it_is_deleted_on_the_same_terms_as_anything_else(self):
        # It holds environments, so it can hold activations. Not a tidier's
        # decision, and not one made by pressing a button once.
        with self.assertRaises(core.HostError):
            environments.remove_nested_library(self.store, 'klevgrand', 'delete')
        self.assertTrue(self.nested.is_dir())
        environments.remove_nested_library(self.store, 'klevgrand',
                                           environments.nested_phrase('klevgrand'))
        self.assertFalse(self.nested.exists())

    def test_it_reports_what_it_freed(self):
        result = environments.remove_nested_library(self.store, 'klevgrand',
                                                    environments.nested_phrase('klevgrand'))
        self.assertEqual(result['freed'], 100)

    def test_external_runtime_link_blocks_nested_library_deletion(self):
        runtimes = self.store.root / 'runtimes'
        runtimes.mkdir(exist_ok=True)
        (runtimes / 'shared').symlink_to(self.nested / 'runtimes' / 'runtime')
        found, = environments.nested_libraries(self.store)
        self.assertIn('runtimes/shared', found['required_by'])
        with self.assertRaisesRegex(core.HostError, 'still required'):
            environments.remove_nested_library(self.store, 'klevgrand', environments.nested_phrase('klevgrand'))
        self.assertTrue(self.nested.exists())

    def test_a_library_with_no_nested_libraries_lists_none(self):
        import shutil
        shutil.rmtree(self.store.root / 'managed-libraries')
        self.assertEqual(environments.nested_libraries(self.store), [])


class DanglingEntryTests(unittest.TestCase):
    """A link whose target is gone is the entry you most want to be rid of.

    Listing only entries that resolve made a dangling link invisible in the one
    view that could have removed it -- so the leftover stayed, and the only
    evidence it existed was a directory listing.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = core.Store(root / 'store', root / 'published')
        (self.store.root / 'environments').mkdir(parents=True, exist_ok=True)
        self.link = self.store.root / 'environments' / 'ghost'
        self.link.symlink_to(root / 'gone' / 'environments' / 'ghost')

    def record(self):
        return next(r for r in environments.survey(self.store) if r['id'] == 'ghost')

    def test_it_is_listed_at_all(self):
        self.assertEqual([r['id'] for r in environments.survey(self.store)], ['ghost'])

    def test_it_says_what_it_is_rather_than_guessing(self):
        record = self.record()
        self.assertTrue(record['dangling'])
        self.assertEqual(environments.summarize(record), 'Link to an environment that is gone')

    def test_removing_it_removes_the_link(self):
        record = self.record()
        environments.remove(self.store, record, environments.removal_phrase(record))
        self.assertFalse(self.link.is_symlink())

    def test_nothing_stands_in_the_way_of_removing_it(self):
        self.assertEqual(environments.blockers(self.store, self.record()), [])


class DanglingRuntimeTests(unittest.TestCase):
    """The same for a runtime link into a library that is gone."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = core.Store(root / 'store', root / 'published')
        (self.store.root / 'runtimes').mkdir(parents=True, exist_ok=True)
        self.link = self.store.root / 'runtimes' / 'proton-elsewhere'
        self.link.symlink_to(root / 'gone' / 'runtimes' / 'proton-elsewhere')

    def test_it_counts_as_unused(self):
        self.assertEqual(environments.unused_runtimes(self.store), ['proton-elsewhere'])

    def test_reclaiming_it_removes_the_link_and_says_where_it_pointed(self):
        result = environments.remove_runtime(self.store, 'proton-elsewhere')
        self.assertFalse(self.link.is_symlink())
        self.assertIn('proton-elsewhere', result['unlinked'])
        self.assertEqual(result['freed'], 0)


class PartitionTests(unittest.TestCase):
    """Separating what is carrying something from what appears not to be.

    These two lists are read with opposite intentions: one is checked, the
    other is emptied. Mixed together, every deletion starts with working out
    which kind each row is.
    """

    def record(self, **fields):
        base = {'id': 'x', 'plugins': [], 'protected': False, 'dangling': False}
        return {**base, **fields}

    def test_an_environment_publishing_plug_ins_is_in_the_first_list(self):
        holding, spare = environments.partition([self.record(plugins=['Skaka'])])
        self.assertEqual(len(holding), 1)
        self.assertEqual(spare, [])

    def test_a_protected_environment_with_nothing_published_is_too(self):
        # It was recorded as holding activations. Publishing nothing is not a
        # reason to file it with the leftovers.
        holding, spare = environments.partition([self.record(protected=True)])
        self.assertEqual(len(holding), 1)
        self.assertEqual(spare, [])

    def test_an_environment_with_neither_goes_to_the_second(self):
        holding, spare = environments.partition([self.record()])
        self.assertEqual(holding, [])
        self.assertEqual(len(spare), 1)

    def test_an_unreadable_licensing_record_is_not_treated_as_nothing(self):
        # status None means the record could not be read, which is the case
        # where guessing "empty" is worst.
        holding, _ = environments.partition([self.record(protected=None)])
        self.assertEqual(holding, [])  # falls to the second list...
        # ...where the interface must say what it does and does not know.
        from plugg import environments as env
        self.assertIn('unreadable', env.licensing_line(self.record(protected=None)))

    def test_largest_first_because_that_is_the_question_being_asked(self):
        records = [self.record(id='small'), self.record(id='big'), self.record(id='unmeasured')]
        ordered = environments.by_size(records, {'small': 10, 'big': 900})
        self.assertEqual([r['id'] for r in ordered], ['big', 'small', 'unmeasured'])


class TidyAfterFailureTests(unittest.TestCase):
    """A setup that got nowhere should not leave gigabytes for someone to find.

    Keeping every failure's prefix looked like caution. It was really a few
    gigabytes, invisible, for the person to discover and decide about months
    later -- which is the maintenance burden this view was otherwise going to
    hand them and call a feature.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = core.Store(root / 'store', root / 'published')
        self.directory = self.store.root / 'environments' / 'job'
        (self.directory / 'prefix/drive_c').mkdir(parents=True)
        (self.directory / 'prefix/big').write_bytes(b'x' * 5000)
        with self.store.db() as db:
            db.execute('INSERT INTO jobs(id,name,installer,kind,hash,status,message,created,updated,env_id)'
                       ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                       ('job', 'Vendor', '/none.exe', 'exe', 'h', 'failed', 'It broke', 1.0, 1.0, 'job'))

    def stage(self, name):
        core.atomic_json(self.store.root / 'jobs' / 'job' / 'helper-setup.json',
                         {'schema': 1, 'stage': name})

    def test_a_failure_before_any_vendor_code_ran_is_cleared_up(self):
        self.stage('preparing-environment')
        result = environments.tidy_after_failure(self.store, 'job')
        self.assertEqual(result['freed'], 5000)
        self.assertFalse(self.directory.exists())

    def test_a_failure_after_the_vendor_installer_started_is_kept(self):
        # It may hold an installed product, or an activation. Nobody can tell
        # from here, so nobody here decides.
        self.stage('installing-helper')
        self.assertIsNone(environments.tidy_after_failure(self.store, 'job'))
        self.assertTrue(self.directory.is_dir())

    def test_an_unreadable_journal_keeps_everything(self):
        (self.store.root / 'jobs' / 'job').mkdir(parents=True, exist_ok=True)
        (self.store.root / 'jobs' / 'job' / 'helper-setup.json').write_text('{ not json')
        self.assertIsNone(environments.tidy_after_failure(self.store, 'job'))
        self.assertTrue(self.directory.is_dir())

    def test_a_missing_journal_keeps_everything(self):
        self.assertIsNone(environments.tidy_after_failure(self.store, 'job'))
        self.assertTrue(self.directory.is_dir())

    def test_a_licensing_record_keeps_everything(self):
        self.stage('preparing-environment')
        (self.directory / 'licensing.json').write_text('{}')
        self.assertIsNone(environments.tidy_after_failure(self.store, 'job'))
        self.assertTrue(self.directory.is_dir())

    def test_a_published_plug_in_keeps_everything(self):
        self.stage('preparing-environment')
        with self.store.db() as db:
            db.execute('INSERT INTO plugins(id,env_id,name,module,hash,status,metadata,publication,message)'
                       " VALUES('p','job','Thing','Thing.vst3','h','ready','{}','','ok')")
        self.assertIsNone(environments.tidy_after_failure(self.store, 'job'))
        self.assertTrue(self.directory.is_dir())

    def test_a_successful_job_is_never_tidied(self):
        self.stage('preparing-environment')
        self.store.update('job', 'ready', 'Fine')
        self.assertIsNone(environments.tidy_after_failure(self.store, 'job'))
        self.assertTrue(self.directory.is_dir())

    def test_an_environment_shared_with_another_job_is_never_tidied(self):
        # Only an environment this job made for itself, which is the only kind
        # it can speak for.
        self.stage('preparing-environment')
        with self.store.db() as db:
            db.execute("UPDATE jobs SET env_id='shared' WHERE id='job'")
        self.assertIsNone(environments.tidy_after_failure(self.store, 'job'))
        self.assertTrue(self.directory.is_dir())

    def test_the_worker_clears_up_when_it_marks_a_job_failed(self):
        self.stage('preparing-environment')
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='preparing' WHERE id='job'")
        with patch('plugg.core._work', side_effect=core.HostError('download failed')):
            with self.assertRaises(core.HostError):
                core.work(self.store, 'job')
        self.assertEqual(self.store.job('job')['status'], 'failed')
        self.assertFalse(self.directory.exists())

    def test_an_installer_without_a_recipe_is_judged_by_its_own_journal(self):
        core.record_stage(self.store, 'job', 'preparing-environment')
        self.assertIsNotNone(environments.tidy_after_failure(self.store, 'job'))
        self.assertFalse(self.directory.exists())

    def test_an_installer_without_a_recipe_that_ran_is_kept(self):
        core.record_stage(self.store, 'job', 'running-installer')
        self.assertIsNone(environments.tidy_after_failure(self.store, 'job'))
        self.assertTrue(self.directory.is_dir())

    def test_a_plain_installer_that_fails_while_preparing_leaves_nothing(self):
        # The generic path used to write no journal, so every failure kept its
        # prefix, however early it stopped.
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='queued' WHERE id='job'")
        with patch.object(core.Store, 'bridge'), patch('plugg.core.verify_installer'), \
                patch('plugg.recipes.provision', return_value={}), \
                patch('plugg.recipes.configure', side_effect=core.HostError('prefix failed')):
            with self.assertRaises(core.HostError):
                core.work(self.store, 'job')
        self.assertEqual(self.store.job('job')['status'], 'failed')
        self.assertFalse(self.directory.exists())


class ActivationKnowledgeTests(unittest.TestCase):
    """The app does not know what is activated, and must not pretend to.

    Finding out would mean reading PACE or a vendor account to see what is
    currently licensed -- inspecting a licensing system, which this project
    does not do. So the note says what the environment was set up for, and the
    person supplies the present tense by typing the phrase.
    """

    SOURCE = Path(__file__).resolve().parents[1] / 'plugg' / 'gui.py'

    def test_the_note_is_about_setup_not_about_now(self):
        from plugg import environments as env
        record = {'protected': True, 'severity': 'deactivate-first', 'products': ['soothe'],
                  'plugins': ['soothe'], 'recorded': [], 'deactivate_at': []}
        line = env.licensing_line(record)
        self.assertIn('Set up for', line)
        self.assertIn('if you have not already', line)

    def test_the_dialog_admits_it_cannot_know(self):
        text = self.SOURCE.read_text()
        self.assertIn('Nothing here asks the vendor whether those are still activated', text)
        self.assertIn('typing the phrase below is how you', text)

    def test_nothing_reads_a_licensing_system_to_find_out(self):
        # The line this project does not cross, kept where it can be checked.
        from plugg import environments, licensing
        for module in (environments, licensing):
            source = Path(module.__file__).read_text().lower()
            for forbidden in ('ilok api', 'pacekeychain', 'activation_state', 'query_licence'):
                self.assertNotIn(forbidden, source, module.__name__)


class IdentitySummaryTests(unittest.TestCase):
    """Why a vendor might think this one computer is several, said once."""

    def record(self, own_identity):
        return {'id': 'x', 'identity_is_this_computer': None if own_identity is None
                else not own_identity}

    def test_nothing_is_said_when_every_environment_is_this_computer(self):
        records = [self.record(False), self.record(False)]
        self.assertIsNone(environments.identity_summary(records))

    def test_it_counts_the_ones_with_an_identity_of_their_own(self):
        records = [self.record(True), self.record(True), self.record(False)]
        note = environments.identity_summary(records)
        self.assertTrue(note.startswith('2 of these'))

    def test_it_says_the_state_is_deliberate_rather_than_broken(self):
        # Rewriting one is what loses its licences. Someone reading this must
        # not come away thinking it is damage to repair.
        note = environments.identity_summary([self.record(True)])
        self.assertIn('deliberately', note)
        self.assertIn('is what would lose them', note)

    def test_an_unreadable_record_is_not_counted_as_either(self):
        self.assertIsNone(environments.identity_summary([self.record(None)]))


class GrabBagTests(unittest.TestCase):
    """A directly-imported environment holds unrelated plug-ins, and grows.

    Several dragged-in VST3s share one prefix when they are compatible, so one
    answer for the environment is the wrong shape: a free plug-in, a
    serial-based one and something machine-bound can sit side by side.
    """

    def record(self, recorded, published):
        return {'id': 'x', 'protected': bool(recorded), 'severity': 'unlicensed' if recorded else None,
                'products': [item['name'] for item in recorded], 'recorded': recorded,
                'plugins': published, 'deactivate_at': []}

    def test_answering_for_everything_reports_only_what_was_answered(self):
        record = self.record([{'name': 'FerricTDS', 'recovery': 'unlicensed'}], ['FerricTDS'])
        self.assertEqual(environments.licensing_line(record),
                         'Nothing here needs activating — FerricTDS')

    def test_a_plug_in_added_afterwards_is_reported_as_unanswered(self):
        # Answer for four, drag in a fifth: reporting the strictest of an
        # incomplete list as though it were the whole picture is the failure.
        record = self.record([{'name': 'FerricTDS', 'recovery': 'unlicensed'}],
                             ['FerricTDS', 'epicVerb'])
        line = environments.licensing_line(record)
        self.assertIn('1 not yet recorded: epicVerb', line)

    def test_the_detail_lists_each_product_and_its_handling(self):
        record = self.record([{'name': 'soothe', 'recovery': 'deactivate-first',
                               'deactivate_at': 'iLok License Manager'},
                              {'name': 'FerricTDS', 'recovery': 'unlicensed'}],
                             ['soothe', 'FerricTDS'])
        detail = environments.recorded_detail(record)
        self.assertIn('soothe — deactivate before rebuilding; at iLok License Manager', detail)
        self.assertIn('FerricTDS — needs no activation', detail)

    def test_the_form_offers_every_plug_in_recorded_or_not(self):
        source = (Path(__file__).resolve().parents[1] / 'plugg' / 'gui.py').read_text()
        self.assertIn("set(record['products']) | set(record['plugins'])", source)

if __name__ == '__main__':
    unittest.main()


class EnvironmentNameTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from plugg import core
        self.store = core.Store(Path(self.tmp.name) / 'library', Path(self.tmp.name) / 'published')
        self.directory = self.store.root / 'environments' / '71237ec9'
        self.directory.mkdir(parents=True)

    def record(self, **extra):
        from plugg import environments
        record = environments.describe(self.store, self.directory, [], [])
        record.update(extra)
        return record

    def test_a_name_is_kept_in_the_library_and_shown_first(self):
        from plugg import environments
        environments.rename(self.store, '71237ec9', '  Kilohearts   plug-ins ')
        self.assertEqual(environments.summarize(self.record()), 'Kilohearts plug-ins')
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), [])
        environments.rename(self.store, '71237ec9', '')
        self.assertEqual(environments.summarize(self.record()), 'Unrecognized environment')

    def test_an_unnamed_installer_environment_is_named_by_what_it_holds(self):
        from plugg import environments
        self.assertEqual(environments.summarize(self.record(plugin_vendors=['Kilohearts'])), 'Kilohearts')
        self.assertEqual(environments.summarize(self.record(jobs=[{'name': 'Kilohearts Installer'}])),
                         'Installed from Kilohearts Installer')

    def test_names_are_short_and_only_for_existing_environments(self):
        from plugg import core, environments
        with self.assertRaises(core.HostError):
            environments.rename(self.store, 'missing', 'x')
        with self.assertRaises(core.HostError):
            environments.rename(self.store, '71237ec9', 'x' * 61)
