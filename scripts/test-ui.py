#!/usr/bin/env python3
"""GTK interaction smoke checks with synthetic data and isolated settings.

Run with a working GTK display, or GDK_BACKEND=broadway GSK_RENDERER=broadway
BROADWAY_DISPLAY=:8 after starting gtk4-broadwayd :8.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plugg.gui import Manager, Gtk, GLib


def children(widget):
    child = widget.get_first_child()
    while child:
        yield child
        child = child.get_next_sibling()


def descendants(widget):
    yield widget
    for child in children(widget):
        yield from descendants(child)


with tempfile.TemporaryDirectory(prefix='plugg-ui-') as temporary:
    root = Path(temporary)
    recipe_dir = root / 'config/plugg/recipes'
    recipe_dir.mkdir(parents=True)
    jobs = [dict(id='direct', env_id='direct', kind='vst3', hash='fixture', name='Example',
                 installer='/tmp/Example.vst3', status='ready', archived=False, message='Ready')]
    plugins = [dict(name='Example', env_id='direct', hash='fixture', status='ready', message='Ready',
                    publication=str(root / 'published/Example.vst3'),
                    metadata=json.dumps({'classes': [{'name': 'Example', 'vendor': 'Example Vendor', 'version': '1.0'}]}))]
    # The library list is built from environment folders, so the example has one.
    (root / 'environments/direct').mkdir(parents=True)
    (root / 'environments/direct/environment.json').write_text(json.dumps({'recipe': 'standalone-vst3'}))
    store = SimpleNamespace(root=root, jobs=lambda: jobs, plugins=lambda: plugins,
                            job=lambda job_id: next(job for job in jobs if job['id'] == job_id))
    setups = [dict(job='direct', recipe='managed-helper', name='Example Manager',
                   vendor='Example Vendor', busy=False, can_refresh=True, has_ilok=False,
                   installer='/tmp/Example.vst3', message='Ready')]
    # A report as recipe_report.report() produces one, so the widgets are built
    # from the same shape the real catalogue hands them.
    FIXTURE = {
        'reference': 'local.example-setup@1', 'name': 'Example Vendor Setup',
        'vendor': 'Example Vendor', 'kind': 'setup', 'tier': 'local',
        'source': '/tmp/example-setup.toml', 'sha256': 'a' * 64,
        'notes': 'Fixture recipe; installs nothing.',
        'capabilities': ['create-environment', 'configure-graphics'],
        'capability_descriptions': {'create-environment': 'Create a new Windows environment',
                                    'configure-graphics': 'Change which graphics driver an environment uses'},
        'downloads': [{'component': 'plugg.vc2022-x64@1',
                       'url': 'https://example.invalid/runtime.exe', 'sha256': 'b' * 64,
                       'documented_at': 'https://example.invalid/notes'}],
        'graphics': {}, 'claims': [{'kind': 'installer', 'name': 'Example Setup.exe', 'sha256': 'c' * 64}],
        'runs': [{'what': 'Runs the vendor installer', 'arguments': ['/S', '/DIR=C:\\Example']}],
        'components': [{'reference': 'plugg.graphics-dxvk@1', 'name': 'DXVK',
                        'purpose': 'Editors that will not draw under WineD3D'}],
        'exceeds_tier': [],
        'flags': [{'level': 'note', 'code': 'configures-graphics', 'message': 'Sets the graphics driver.'}],
        'verdict': 'routine', 'removable': True,
    }
    REFUSED = dict(FIXTURE, reference='local.too-much@1', name='Too Much',
                   verdict='refused', exceeds_tier=['run-vendor-installer'], removable=False,
                   flags=[{'level': 'danger', 'code': 'exceeds-tier',
                           'message': 'Declares more than a community recipe may.'}])
    COMPONENTS = [{'reference': 'plugg.graphics-dxvk@1', 'name': 'DXVK',
                   'purpose': 'Editors that will not draw under WineD3D', 'notes': None,
                   'tier': 'shipped', 'capabilities': ['configure-graphics'], 'requires': []}]
    result = {'passed': False}
    class TestManager(Manager):
        def activate(self, *_):
            super().activate()
            GLib.idle_add(self.check_controls)

        def check_controls(self):
            try:
                details_window = self.job_details(jobs[0])
                assert any(isinstance(w, Gtk.Label) and w.get_text() == 'Saved file: Example.vst3'
                           for w in descendants(details_window))
                assert any(isinstance(w, Gtk.Button) and w.get_label() == 'Open installation files'
                           for w in descendants(details_window))
                details_window.close()
                help_window = self.help()
                assert any(isinstance(w, Gtk.Button) and w.get_label() == 'Open recipes & fixes'
                           for w in descendants(help_window))
                help_window.close()

                # The library list works from the keyboard and tells a screen
                # reader what each row is: a row is an activatable list row with
                # a spoken name, Enter opens it, and the expanded state follows.
                self.stack.set_visible_child_name('library')
                self.refresh()
                view = self.library_view
                first = view.vendor_list.get_row_at_index(0) if view.vendor_list else None
                assert first is not None, 'the library should list the example vendor'
                assert first.get_activatable(), 'Enter must be able to act on a vendor row'
                assert Gtk.test_accessible_has_property(first, Gtk.AccessibleProperty.LABEL)
                assert Gtk.test_accessible_has_state(first, Gtk.AccessibleState.EXPANDED)
                opens, settings = view.row_actions[first]
                revealer = next(w for w in descendants(first) if isinstance(w, Gtk.Revealer))
                before = revealer.get_reveal_child()
                opens()
                assert revealer.get_reveal_child() != before, 'Enter on a row should show or hide its plug-ins'
                assert settings is not None and Gtk.test_accessible_has_property(settings, Gtk.AccessibleProperty.LABEL)
                assert not any(isinstance(w, Gtk.ProgressBar)
                               and w.get_accessible_role() != Gtk.AccessibleRole.PRESENTATION
                               for w in descendants(view.widget)), 'size bars are decoration'

                # Every view exists and can be entered. Switching tabs is the
                # one interaction nothing else covers, and each one rebuilds.
                for name in ('recipes', 'library'):
                    self.stack.set_visible_child_name(name)
                    assert self.stack.get_visible_child_name() == name
                    self.refresh()
                assert json.loads((root / 'ui.json').read_text())['tab'] == 'library'

                # The capability report, built as widgets. Nothing else runs
                # this code: it is the one part of the trust model a GUI user
                # ever sees, and it had no coverage at all until it existed.
                self.recipes_loaded({'recipes': [FIXTURE], 'components': COMPONENTS, 'issues': []})
                assert any(isinstance(w, Gtk.Label) and w.get_text() == 'Example Vendor Setup'
                           for w in descendants(self.recipes))
                assert any(isinstance(w, Gtk.Button) and w.get_label() == 'What it does…'
                           for w in descendants(self.recipes))
                assert any(isinstance(w, Gtk.Button) and w.get_label() == 'Remove'
                           for w in descendants(self.recipes))
                assert any(isinstance(w, Gtk.Label) and 'graphics driver' in w.get_text()
                           for w in descendants(self.recipes)), 'the worst flag should be on the row'
                assert any(isinstance(w, Gtk.Label) and 'Reusable components' in w.get_text() for w in descendants(self.recipes))
                assert any(isinstance(w, Gtk.Label) and 'Applies graphics settings.' in w.get_text() for w in descendants(self.recipes))
                report = self.show_recipe(FIXTURE)
                shown = [w.get_text() for w in descendants(report) if isinstance(w, Gtk.Label)]
                for expected in ('Runs the vendor installer', 'https://example.invalid/runtime.exe',
                                 'Create a new Windows environment'):
                    assert any(expected in text for text in shown), expected + ' missing from the report'
                report.close()
                from plugg import recipe_engine, recipe_report
                records = recipe_engine.catalogue([Path(recipe_engine.__file__).parent / 'recipes/community'])
                components = recipe_report.component_index(records)
                assert self.window.measure(Gtk.Orientation.HORIZONTAL, -1)[0] <= 700, 'header must fit a 700px window'
                self.recipes_loaded({'recipes': [FIXTURE], 'components': components, 'issues': []})
                assert any(isinstance(w, Gtk.Button) and w.get_label() == 'Component details…' for w in descendants(self.recipes))
                component = next(item for item in components if item['reference'] == 'plugg.vc2013-x64@1')
                evidence_window = self.show_recipe(component['report'])
                assert evidence_window.measure(Gtk.Orientation.HORIZONTAL, -1)[0] <= 640, 'component details must wrap at 640px'
                assert any(isinstance(w, Gtk.Label) and 'Synthetic fixture only' in w.get_text() for w in descendants(evidence_window))
                # Its test notes are in the private plugg-lab records: named, not linked.
                assert any(isinstance(w, Gtk.Label) and w.get_text() == 'Source: plugg-lab: docs/validation/helper-vc-recipe-2026-09-12.json'
                           for w in descendants(evidence_window))
                assert not any(isinstance(w, Gtk.LinkButton) for w in descendants(evidence_window))
                evidence_window.close()
                public = next(item for item in components if item['reference'] == 'plugg.bridge-editor-detach@1')
                evidence_window = self.show_recipe(public['report'])
                assert any(isinstance(w, Gtk.LinkButton) and w.get_label() == 'Open test notes' for w in descendants(evidence_window))
                evidence_window.close()
                patch_report = recipe_report.report(records, 'plugg.ole32-foreign-window-guard@1')
                patch_window = self.show_recipe(patch_report)
                assert patch_window.measure(Gtk.Orientation.HORIZONTAL, -1)[0] <= 640, 'long patch IDs must wrap'
                patch_window.close()
                signin = self.native_access_sign_in('fixture-job')
                field = next(w for w in descendants(signin) if isinstance(w, Gtk.Entry))
                assert not field.get_visibility(), 'callback must be concealed'
                callback = 'native-access://auth?code=synthetic-test'
                field.set_text(callback)
                submit = next(w for w in descendants(signin) if isinstance(w, Gtk.Button) and w.get_label() == 'Complete sign-in')
                with patch('plugg.vendors.configuration', return_value=(root, {})), patch('plugg.native_access.complete_sign_in') as forward:
                    submit.emit('clicked')
                    forward.assert_called_once_with(root, callback)
                    assert field.get_text() == '', 'callback must be cleared immediately'
                long_summary = dict(FIXTURE, name='A very long vendor and setup name ' * 6,
                                    reference='local.' + 'longcomponent' * 12 + '@1')
                long_window = self.show_recipe(long_summary)
                assert long_window.measure(Gtk.Orientation.HORIZONTAL, -1)[0] <= 640, 'long recipe names must wrap'
                long_window.close()
                vendor_reports = [dict(recipe_report.report(records, ref), removable=False)
                                  for ref, record in records.items() if record['data']['kind'] != 'component']
                self.recipes_loaded({'recipes': vendor_reports, 'components': components, 'issues': []})
                labels = lambda: [w.get_text() for w in descendants(self.recipes) if isinstance(w, Gtk.Label)]
                assert labels().count('Windows archive tools') == 1
                assert labels().count('Plugin Alliance graphics') == 1
                assert 'Plugin Alliance graphics (r1)' not in labels()
                assert 'Klevgrand Helper (r1)' not in labels()
                self.catalogue_history.set_active(True)
                assert labels().count('Windows archive tools') == 2
                assert labels().count('Plugin Alliance graphics') == 2
                assert 'Older revision' in labels()
                assert 'Plugin Alliance graphics (r1)' in labels()
                self.catalogue_history.set_active(False)
                assert labels().count('Plugin Alliance graphics') == 1
                link = next(w for w in descendants(self.recipes) if isinstance(w, Gtk.Button)
                            and w.get_label() == 'Plugin Alliance graphics (r2)')
                with patch.object(self, 'show_recipe') as open_report:
                    link.emit('clicked')
                    assert open_report.call_args.args[0]['reference'] == 'plugg.plugin-alliance@2'
                self.recipes_loaded({'recipes': [FIXTURE], 'components': components, 'issues': []})
                self.catalogue_scope.set_selected(2)
                assert not any(isinstance(w, Gtk.Label) and w.get_text() == 'Example Vendor Setup' for w in descendants(self.recipes))
                assert any(isinstance(w, Gtk.Label) and w.get_text() == 'DXVK graphics' for w in descendants(self.recipes))
                self.catalogue_scope.set_selected(1)
                assert not any(isinstance(w, Gtk.Label) and w.get_text() == 'DXVK graphics' for w in descendants(self.recipes))
                assert any(isinstance(w, Gtk.Label) and w.get_text() == 'Example Vendor Setup' for w in descendants(self.recipes))
                self.catalogue_scope.set_selected(0)
                self.catalogue_search.set_text('VC2013')
                self.catalogue_search_changed(self.catalogue_search)
                assert any(isinstance(w, Gtk.Label) and w.get_text() == 'Visual C++ 2013 runtime' for w in descendants(self.recipes))
                assert not any(isinstance(w, Gtk.Label) and w.get_text() == 'DXVK graphics' for w in descendants(self.recipes))
                self.catalogue_search.set_text('nothing matches this phrase')
                self.catalogue_search_changed(self.catalogue_search)
                assert any(isinstance(w, Gtk.Label) and 'No components match' in w.get_text() for w in descendants(self.recipes))
                self.catalogue_search.set_text('')
                self.catalogue_search_changed(self.catalogue_search)
                assert any(isinstance(w, Gtk.Label) and w.get_text() == 'DXVK graphics' for w in descendants(self.recipes))

                # A recipe that declares more than its tier allows cannot be
                # added, however determined the person clicking is.
                self.preview_recipe(REFUSED, Path('/tmp/refused.toml'))
                add = next(w for w in descendants(self.preview)
                           if isinstance(w, Gtk.Button) and w.get_label() == 'Add recipe')
                assert not add.get_sensitive(), 'a refused recipe must not be addable'
                self.preview.close()

                self.stack.set_visible_child_name('library')
                view = self.library_view

                def row_widgets():
                    return [view.vendor_list.get_row_at_index(i) for i in range(50)
                            if view.vendor_list and view.vendor_list.get_row_at_index(i)]

                # The row leads with the vendor, and its app is one button that
                # names the app when you ask.
                assert any(isinstance(w, Gtk.Label) and w.get_text() == 'Example Vendor'
                           for w in descendants(view.widget))
                app = next(w for w in descendants(view.widget)
                           if isinstance(w, Gtk.Button) and w.get_label() == 'Open manager')
                assert app.get_tooltip_text() == 'Opens Example Manager'

                # A helper's status is news for its row's expansion, and Force
                # close is in the environment's settings, never disabled.
                setups[0]['needs_attention'] = True
                setups[0]['message'] = 'Example failed to scan'
                self.last = None
                self.refresh()
                assert any(isinstance(w, Gtk.Label) and 'Last check: Example failed to scan' in w.get_text()
                           for w in descendants(view.widget))
                settings = view.menus['direct'].get_popover()
                force = next(w for w in descendants(settings)
                             if isinstance(w, Gtk.Button) and w.get_label() == 'Force close its apps')
                assert force.get_sensitive()
                setups[0]['needs_attention'] = False
                self.last = None
                self.refresh()

                # A second manager in the same environment gets its own button.
                with patch('plugg.softube.configured', return_value=True):
                    self.last = None
                    self.refresh()
                    softube_button = next(w for w in descendants(view.widget)
                                          if isinstance(w, Gtk.Button) and w.get_tooltip_text() == 'Opens Softube Central')
                    with patch('plugg.softube.start') as launch:
                        softube_button.emit('clicked')
                        launch.assert_called_once_with(root / 'environments/direct')
                self.last = None
                self.refresh()

                # Search narrows the list, says when nothing matches, and finds a
                # plug-in by the file name a DAW reports.
                self.window.set_default_size(700, 820)
                assert len(row_widgets()) == 1, 'the fixture vendor should be listed once'
                view.search.set_text('not present')
                view.search_changed(view.search)
                assert not row_widgets()
                assert any(isinstance(w, Gtk.Label) and 'Nothing matches' in w.get_text()
                           for w in descendants(view.widget))
                view.search.set_text('example')
                view.search_changed(view.search)
                assert len(row_widgets()) == 1
                view.search.set_text('')
                view.search_changed(view.search)

                self.toggle_theme()
                assert json.loads((root / 'ui.json').read_text())['theme'] == self.theme_mode

                broken = recipe_dir / 'broken.toml'
                broken.write_text('schema = "not a schema"')
                self.refresh()
                assert self.recipe_notice.get_visible()
                assert self.recipe_notice_row.get_visible()
                assert self.recipe_details.get_sensitive()
                problem = self.show_recipe_problem()
                text_view = next(w for w in descendants(problem) if isinstance(w, Gtk.TextView))
                buffer = text_view.get_buffer()
                assert str(broken) in buffer.get_text(buffer.get_start_iter(),
                                                      buffer.get_end_iter(), False)
                assert not text_view.get_editable()
                problem.close()
                broken.unlink()
                self.refresh()
                assert not self.recipe_notice.get_visible()
                assert self.show_recipe_problem() is None

                # A plug-in's details: the file a DAW sees, which is all a DAW
                # names when it refuses one, and where it came from.
                chip = next(w for w in descendants(view.widget)
                            if isinstance(w, Gtk.MenuButton) and w.has_css_class('lib-chip-button'))
                view.chip_fillers[chip]()
                shown = [w.get_text() for w in descendants(chip.get_popover()) if isinstance(w, Gtk.Label)]
                assert any('Your DAW sees: Example.vst3' in line for line in shown), shown
                self.tab = 'recipes'
                self.save_interface_state()
                assert Manager(store).tab == 'recipes', 'the recipe tab should survive reopening'
                result['passed'] = True
                print('GTK checks passed: the library list by keyboard and screen reader, pages, vendor '
                      'row and settings, search, plug-in details, theme, the recipe report and its '
                      'refusal, and malformed-recipe isolation.', flush=True)
            except Exception as exc:
                import traceback
                traceback.print_exc()
                result['error'] = repr(exc)
                print('GTK check failed:', repr(exc), file=sys.stderr, flush=True)
            finally:
                self.quit()
            return False

    with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(root / 'config')}), patch('plugg.vendors.cards', return_value=setups):
        TestManager(store).run(['test-ui'])
    raise SystemExit(0 if result['passed'] else 1)
