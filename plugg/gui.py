"""Native GTK4 manager. Install workers survive closing this window.

SPDX-License-Identifier: GPL-3.0-or-later
"""
import json
import subprocess
import os
from pathlib import Path
import sys

# The manager needs no GPU rendering. This avoids Vulkan startup failures on
# some NVIDIA/Wayland configurations; explicit user renderer choices win.
os.environ.setdefault("GSK_RENDERER", "cairo")

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, Gio, GLib, Pango

from .core import TERMINAL, doctor
from . import vendors, standalone


from . import theme
from .library_view import LibraryView, measure_breakdown



def label(text, css=None, wrap=False):
    widget = Gtk.Label(label=text, xalign=0)
    widget.set_wrap(wrap)
    if wrap:
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if css:
        widget.add_css_class(css)
    return widget


from .provenance import installation_source, setup_recipe_summary, installation_progress, licensing_summary


class Manager(Gtk.Application):
    def __init__(self, store):
        super().__init__(application_id="com.oikoaudio.Plugg", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.store = store
        self.last = None
        self.catalogue_query = ""
        self.catalogue_payload = None
        try:
            saved_theme = json.loads((self.store.root / 'ui.json').read_text()).get('theme', 'dark')
        except (OSError, ValueError):
            saved_theme = 'dark'
        self.theme_mode = saved_theme if saved_theme in theme.PALETTES else 'dark'
        try:
            saved_tab = json.loads((self.store.root / 'ui.json').read_text()).get('tab', 'library')
        except (OSError, ValueError):
            saved_tab = 'library'
        self.tab = saved_tab if saved_tab in ('library', 'recipes') else 'library'
        #: Bytes per top-level entry of the library folder, measured in the
        #: background, so the library view can add the whole folder up.
        self.breakdown = None
        self.pending = {}
        self.helper_offers_cache = {}
        self.known_cache = {}
        #: Measured once, on request. Walking a Proton prefix is felt, and this
        #: interface refreshes continuously.
        self.sizes = {}
        self.measuring = False
        self.connect("activate", self.activate)

    def activate(self, *_):
        self.window = Gtk.ApplicationWindow(application=self, title="Plugg")
        self.window.set_default_size(1120, 820)
        theme.install_font()
        provider = Gtk.CssProvider()
        self.theme_provider = provider
        provider.load_from_data(theme.css(self.theme_mode))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        header = Gtk.HeaderBar()
        details = Gtk.Button(label="Details")
        details.connect("clicked", self.details)
        header.pack_end(details)
        help_button = Gtk.Button(label="Help")
        help_button.connect("clicked", self.help)
        header.pack_end(help_button)
        switch_theme = Gtk.Button(icon_name='weather-clear-night-symbolic', tooltip_text='Switch light / dark theme')
        switch_theme.connect('clicked', self.toggle_theme)
        header.pack_end(switch_theme)
        self.window.set_titlebar(header)
        scroll = Gtk.ScrolledWindow()
        self.scroll = scroll
        self.window.set_child(scroll)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        for side in ("top", "bottom", "start", "end"):
            getattr(content, "set_margin_" + side)(28)
        scroll.set_child(content)
        # The welcome is for an empty library. Once there is something in it,
        # the drop area shrinks to one line and the library gets the room.
        self.hero = label("Windows audio plug-ins in your Linux DAW", "hero", True)
        content.append(self.hero)
        self.subtitle = label("Add a Windows installer or VST3 plug-in. Plugg handles setup and makes your plug-ins available in your DAW.", "subtitle", True)
        content.append(self.subtitle)
        drop = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.drop_area = drop
        drop.add_css_class("drop-area")
        icon = Gtk.Image.new_from_icon_name('folder-download-symbolic')
        icon.set_pixel_size(28)
        icon.set_valign(Gtk.Align.CENTER)
        icon.add_css_class('muted')
        drop.append(icon)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text.set_hexpand(True)
        text.set_valign(Gtk.Align.CENTER)
        self.drop_title = label("Add your Windows plug-ins", "section-title", True)
        text.append(self.drop_title)
        self.drop_line = label("Drop an installer or VST3 here, or choose a file to get started.", "muted", True)
        text.append(self.drop_line)
        self.drop_hint = label("Keep any installer .bin files beside the .exe.", "status", True)
        text.append(self.drop_hint)
        # Adding a second, different installer while the first runs is fine and
        # useful. Dropping the SAME one again because nothing acknowledged it
        # is not, and that is what happened -- so the drop area says what is
        # already under way, at the spot where the gesture is made.
        self.drop_note = label('', 'running-note', True)
        self.drop_note.set_visible(False)
        text.append(self.drop_note)
        drop.append(text)
        choose = Gtk.Button(label="Choose file…")
        choose.add_css_class("suggested-action")
        choose.set_valign(Gtk.Align.CENTER)
        choose.connect("clicked", self.choose)
        drop.append(choose)
        # Dolphin on Wayland offers a plain drag as MOVE, and a COPY-only
        # target turned it down without a word. Plugg copies the file in
        # either way, and Dolphin keeps its own after a MOVE drop.
        target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        target.connect("drop", self.drop)
        drop.add_controller(target)
        content.append(drop)
        # Work in progress belongs where the work was started. Anything further
        # down the window is somewhere you have to already suspect it is.
        self.activity = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.append(self.activity)
        # One view of the library, and the recipe catalogue behind it. The
        # four tabs this replaced split one vendor's facts across three of
        # them; everything they did now lives on the vendor's row or its
        # settings (docs/decisions/0004-one-library-list.md).
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)
        header.set_title_widget(label('Plugg', 'window-title'))
        self.library_view = LibraryView(self)
        library_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        library_page.append(self.library_view.widget)
        self.stack.add_named(library_page, 'library')

        # Everything a recipe can do is computed from the file, and until now
        # the only way to see any of it was a terminal — which is not where
        # someone opens a file a stranger posted on a forum. The person who
        # most needs the report was the one person who could not get at it.
        recipes_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        recipes_row = Gtk.Box(spacing=12)
        recipes_row.add_css_class('section-header')
        back = Gtk.Button(label='← Library')
        back.add_css_class('compact')
        back.set_valign(Gtk.Align.CENTER)
        back.set_tooltip_text('Back to your vendors and plug-ins (Escape)')
        back.connect('clicked', lambda *_: self.stack.set_visible_child_name('library'))
        recipes_row.append(back)
        self.recipes_heading = label('Setup recipes', 'section-title')
        self.recipes_heading.set_hexpand(True)
        self.recipes_heading.set_valign(Gtk.Align.CENTER)
        recipes_row.append(self.recipes_heading)
        add_recipe = Gtk.Button(label='Add recipe…')
        add_recipe.add_css_class('compact')
        add_recipe.set_valign(Gtk.Align.CENTER)
        add_recipe.connect('clicked', self.choose_recipe)
        recipes_row.append(add_recipe)
        recipes_page.append(recipes_row)
        recipes_page.append(label('Vendor setups and reusable fixes. Open details to see their requirements and exact actions.', 'muted', True))
        self.catalogue_search = Gtk.SearchEntry(placeholder_text='Find a recipe, component or problem…')
        self.catalogue_search.connect('search-changed', self.catalogue_search_changed)
        catalogue_tools = Gtk.Box(spacing=10)
        self.catalogue_search.set_hexpand(True)
        catalogue_tools.append(self.catalogue_search)
        self.catalogue_scope = Gtk.DropDown.new_from_strings(['All', 'Vendor setups', 'Components'])
        self.catalogue_scope.set_tooltip_text('Choose which parts of the catalogue to show')
        self.catalogue_scope.connect('notify::selected', self.catalogue_scope_changed)
        catalogue_tools.append(self.catalogue_scope)
        recipes_page.append(catalogue_tools)
        self.catalogue_history = Gtk.CheckButton(label='Show older recipe revisions')
        self.catalogue_history.connect('toggled', self.catalogue_scope_changed)
        recipes_page.append(self.catalogue_history)
        self.recipes = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        recipes_page.append(self.recipes)
        self.stack.add_named(recipes_page, 'recipes')
        escape = Gtk.ShortcutController(scope=Gtk.ShortcutScope.LOCAL)
        escape.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string('Escape'),
                                         action=Gtk.CallbackAction.new(
                                             lambda *_: self.stack.set_visible_child_name('library') or True)))
        recipes_page.add_controller(escape)

        content.append(self.stack)
        self.stack.set_visible_child_name(self.tab)
        self.recipe_notice = label("", "status", True)
        self.recipe_notice.set_visible(False)
        self.recipe_problem = None
        self.recipe_notice_row = Gtk.Box(spacing=12)
        self.recipe_notice.set_hexpand(True)
        self.recipe_notice_row.append(self.recipe_notice)
        self.recipe_details = Gtk.Button(label="View problem")
        self.recipe_details.set_valign(Gtk.Align.CENTER)
        self.recipe_details.connect("clicked", self.show_recipe_problem)
        self.recipe_notice_row.append(self.recipe_details)
        self.recipe_notice_row.set_visible(False)
        content.append(self.recipe_notice_row)
        content.append(label("Developer preview · Separate environments are not security sandboxes. Compatibility testing is in progress.", "muted", True))
        # Who makes it, and where to find out more. Quiet, once, at the end.
        credit = Gtk.Label(xalign=0.0)
        credit.set_markup('Plugg by Oiko Audio · <a href="https://www.oikoaudio.com">oikoaudio.com</a>')
        credit.add_css_class('muted')
        credit.add_css_class('credit')
        content.append(credit)
        self.stack.connect('notify::visible-child-name', self.tab_changed)
        # Keys: typing searches the library, Ctrl+F goes to its search, Ctrl+O adds a file.
        self.library_view.attach(self.window)
        if self.tab != 'library':
            self.library_view.search.set_key_capture_widget(None)
        adding = Gtk.ShortcutController(scope=Gtk.ShortcutScope.GLOBAL)
        adding.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string('<Control>o'),
                                         action=Gtk.CallbackAction.new(lambda *_: self.choose() or True)))
        self.window.add_controller(adding)
        self.refresh()
        if self.tab == 'library':
            self.measure_environments()
            self.measure_library()
        if self.tab == 'recipes':
            self.load_recipes()
        GLib.timeout_add(700, self.refresh)
        self.window.present()
        if os.environ.get("PLUGG_UI_SMOKE"):
            GLib.timeout_add(int(os.environ.get('PLUGG_UI_SMOKE_MS', '1800')), self.smoke_done)

    def save_interface_state(self):
        from .core import atomic_json
        atomic_json(self.store.root / 'ui.json', {'theme': self.theme_mode, 'tab': self.tab})

    def toggle_theme(self, *_):
        self.theme_mode = 'light' if self.theme_mode == 'dark' else 'dark'
        self.theme_provider.load_from_data(theme.css(self.theme_mode))
        self.save_interface_state()

    def open_recipes(self, scope=0):
        """The catalogue, from the library: where a new plug-in goes when it does not just work."""
        self.catalogue_scope.set_selected(scope)
        self.stack.set_visible_child_name('recipes')

    def troubleshoot(self, record=None, vendor=None):
        """The fixes others found, already searched for this vendor when there is one."""
        from . import environments as survey
        vendor = vendor or (survey.summarize(record) if record else '')
        self.open_recipes(scope=0 if vendor else 2)
        self.catalogue_search.set_text(vendor if vendor and 'iLok' not in vendor else '')

    def show_path(self, path):
        Gio.AppInfo.launch_default_for_uri(Path(path).as_uri(), None)

    def show_folder(self, name):
        self.show_path(self.store.root / name)

    def measure_library(self):
        import threading
        if getattr(self, 'measuring_library', False):
            return
        self.measuring_library = True

        def task():
            found = measure_breakdown(self.store.root)
            GLib.idle_add(self.library_measured, found)
        threading.Thread(target=task, daemon=True).start()

    def library_measured(self, found):
        self.measuring_library = False
        self.breakdown = found
        self.last = None
        self.refresh()
        return False

    def tab_changed(self, stack, _):
        """Come back to the view you were working in, and survey only on arrival."""
        self.tab = stack.get_visible_child_name() or 'library'
        # Typing searches the library only while the library is what you see.
        self.library_view.search.set_key_capture_widget(self.window if self.tab == 'library' else None)
        self.save_interface_state()
        self.last = None
        self.refresh()
        if self.tab == 'library':
            self.measure_environments()
            self.measure_library()
        if self.tab == 'recipes':
            self.load_recipes()

    def smoke_done(self):
        print("GTK smoke test: window presented, controls created, registry read", flush=True)
        if os.environ.get('PLUGG_UI_SNAPSHOT'):
            from .library_view import save_snapshot
            save_snapshot(self.window, os.environ['PLUGG_UI_SNAPSHOT'])
        self.quit()
        return False

    def message(self, title, text):
        Gtk.AlertDialog(message=title, detail=text).show(self.window)

    def details(self, *_):
        dialog = Gtk.Window(title="Plugg details", transient_for=self.window, modal=True)
        dialog.set_default_size(700, 480)
        view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        view.get_buffer().set_text(json.dumps(doctor(self.store), indent=2))
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(view)
        dialog.set_child(scroll)
        dialog.present()

    def show_recipe_problem(self, *_):
        if not self.recipe_problem:
            return None
        dialog = Gtk.Window(title="Setup recipe problem", transient_for=self.window, modal=True)
        dialog.set_default_size(620, 360)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for edge in ('top', 'bottom', 'start', 'end'):
            getattr(content, 'set_margin_' + edge)(16)
        content.append(label("Correct the recipe file below, or move it out of your local recipes folder. "
                             "The app will check it again automatically.", None, True))
        view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        view.get_buffer().set_text(self.recipe_problem)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(view)
        content.append(scroll)
        close = Gtk.Button(label="Close")
        close.set_halign(Gtk.Align.END)
        close.connect("clicked", lambda *_: dialog.close())
        content.append(close)
        dialog.set_child(content)
        dialog.present()
        return dialog

    def help(self, *_):
        """Questions people ask, what has been tested, and what to do when neither helps."""
        from .help_content import FAQ, VENDORS, UNTESTED
        dialog = Gtk.Window(title="Help · Plugg", transient_for=self.window)
        dialog.set_default_size(700, 680)
        scroll = Gtk.ScrolledWindow()
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(body, 'set_margin_' + side)(20)
        for group, entries in FAQ:
            body.append(label(group, 'section-title'))
            for question, answer in entries:
                # One line per question, the answer when asked: the list is
                # scanned for the question you have, not read top to bottom.
                expander = Gtk.Expander(label=question)
                expander.add_css_class('faq')
                paragraph = label(answer, wrap=True)
                paragraph.set_selectable(True)
                paragraph.set_max_width_chars(76)
                paragraph.set_margin_start(18)
                paragraph.set_margin_bottom(6)
                expander.set_child(paragraph)
                body.append(expander)
        body.append(label('What has been tested', 'section-title'))
        for vendor, (status, note) in VENDORS.items():
            expander = Gtk.Expander(label='%s · %s' % (vendor, status))
            expander.add_css_class('faq')
            paragraph = label(note, wrap=True)
            paragraph.set_selectable(True)
            paragraph.set_max_width_chars(76)
            paragraph.set_margin_start(18)
            expander.set_child(paragraph)
            body.append(expander)
        body.append(label(UNTESTED, 'muted', True))
        body.append(label('Plugg has no helpdesk', 'section-title'))
        body.append(label("Plugg is made by one person, with no support desk behind it. Most answers are "
                          "above, in the known fixes Plugg shows when you install something, and under "
                          "Recipes & fixes. Good bug reports get read and fixed; a request to get one "
                          "particular setup working usually cannot be answered. A compatibility finding, "
                          "what you tried and how far it got, helps everyone after you.", wrap=True))
        actions = Gtk.Box(spacing=8)
        for title, handler in (("Open recipes & fixes", self.go_to_recipes),
                               ("Report a bug in Plugg…", lambda *_: self.report('bug')),
                               ("Share a compatibility finding…", lambda *_: self.report('compatibility'))):
            button = Gtk.Button(label=title)
            button.add_css_class('compact')
            button.connect("clicked", handler)
            actions.append(button)
        body.append(actions)
        scroll.set_child(body)
        dialog.set_child(scroll)
        dialog.present()
        return dialog

    def report(self, kind='bug', record=None):
        """A guided report: known fixes first, then the answers a report needs, then the issue form.

        Nothing goes further until the answers that make a report useful are
        there and the person says they looked at the known fixes. The issue form
        opens with their answers filled in; they review and submit it on GitHub.
        """
        from . import environments as survey, known_fixes, report as reporting
        records = survey.survey(self.store)
        jobs = self.store.jobs()
        setups = self.last[2] if self.last else []
        focus = record['id'] if record else None
        dialog = Gtk.Window(title='Report a bug' if kind == 'bug' else 'Share a compatibility finding',
                            transient_for=self.window, modal=True)
        dialog.set_default_size(640, 720)
        scroll = Gtk.ScrolledWindow()
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(body, 'set_margin_' + side)(20)
        body.append(label('Plugg has no helpdesk', 'section-title'))
        body.append(label('Good bug reports get read and fixed. A good one says what you did, what happened, '
                          'what you expected and how often, and Plugg adds the facts about your setup.'
                          if kind == 'bug' else
                          'A finding says how far a plug-in got and what you tried, so the next person '
                          'starts from there. The best ones end with a fix.', 'muted', True))
        if record:
            installer = next((j.get('installer') for j in jobs if j['env_id'] == record['id']), None)
            known = known_fixes.lookup(installer, None, vendor=survey.summarize(record)) if installer else []
            if known:
                body.append(label('Did any of these help?', 'plugin-name'))
                for item in known:
                    body.append(label('· ' + item['text'], 'status', True))
        answers = {}
        fields = [('daw', 'DAW and version', False, 'Bitwig Studio 5.3')]
        if kind == 'bug':
            fields = [('what', 'What happened, and what you expected', True, ''),
                      ('steps', 'Steps to make it happen', True, '1. …\n2. …')] + fields
        else:
            fields = [('product', 'Product and exact version', False, 'Example Synth 1.2.3'),
                      ('steps', 'The smallest way to reproduce it', True, ''),
                      ('tried', 'What you tried, and what each changed', True, '')] + fields
        entries = {}
        for key, title, multiline, hint in fields:
            body.append(label(title, 'status'))
            if multiline:
                view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
                view.set_size_request(-1, 90)
                view.add_css_class('report-field')
                if hint:
                    view.get_buffer().set_text(hint)
                entries[key] = view
                body.append(view)
            else:
                entry = Gtk.Entry(placeholder_text=hint)
                entries[key] = entry
                body.append(entry)
        frequency = None
        stages = {}
        if kind == 'bug':
            body.append(label('How often', 'status'))
            frequency = Gtk.DropDown.new_from_strings(['Choose…'] + list(reporting.FREQUENCY))
            body.append(frequency)
        else:
            body.append(label('How far it got (leave a stage empty if you did not get there)', 'status'))
            grid = Gtk.Grid(column_spacing=10, row_spacing=6)
            for row_index, stage in enumerate(reporting.STAGES):
                grid.attach(label(stage, 'muted'), 0, row_index, 1, 1)
                entry = Gtk.Entry(placeholder_text='worked, failed, not tried…')
                entry.set_hexpand(True)
                stages[stage] = entry
                grid.attach(entry, 1, row_index, 1, 1)
            body.append(grid)
        body.append(label('About your setup (added for you; edit anything you would rather not share)', 'status'))
        summary_view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, monospace=True)
        summary_view.get_buffer().set_text(reporting.setup_summary(self.store, records, setups, jobs, focus))
        summary_view.set_size_request(-1, 140)
        summary_view.add_css_class('report-summary')
        body.append(summary_view)
        looked = Gtk.CheckButton(label='I read Help and tried the known fixes and Recipes & fixes.')
        body.append(looked)
        still = label('', 'status', True)
        body.append(still)
        open_form = Gtk.Button(label='Open the issue form')
        open_form.add_css_class('suggested-action')
        open_form.set_halign(Gtk.Align.END)
        body.append(open_form)

        def text_of(widget):
            if isinstance(widget, Gtk.TextView):
                buffer = widget.get_buffer()
                return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
            return widget.get_text()

        def collect():
            answers.clear()
            for key, widget in entries.items():
                value = text_of(widget)
                answers[key] = '' if value in ('1. …\n2. …',) else value
            if frequency is not None:
                chosen = frequency.get_selected()
                answers['frequency'] = reporting.FREQUENCY[chosen - 1] if chosen > 0 else ''
            if stages:
                answers['stages'] = {stage: entry.get_text().strip() for stage, entry in stages.items()
                                     if entry.get_text().strip()}
            return reporting.missing(kind, answers)

        def update(*_):
            gaps = collect()
            if not looked.get_active():
                gaps = gaps + ['a look at the known fixes first']
            still.set_text('Still needed: ' + '; '.join(gaps) + '.' if gaps else
                           'Ready. The form opens on GitHub with your answers; you check it and submit it there.')
            open_form.set_sensitive(not gaps)
        for widget in entries.values():
            (widget.get_buffer() if isinstance(widget, Gtk.TextView) else widget).connect('changed', update)
        for entry in stages.values():
            entry.connect('changed', update)
        if frequency is not None:
            frequency.connect('notify::selected', update)
        looked.connect('toggled', update)

        def submit(*_):
            if collect() or not looked.get_active():
                return
            summary = text_of(summary_view)
            Gio.AppInfo.launch_default_for_uri(reporting.issue_url(kind, reporting.fields(kind, answers, summary)),
                                               None)
            dialog.close()
        open_form.connect('clicked', submit)
        update()
        scroll.set_child(body)
        dialog.set_child(scroll)
        dialog.present()
        return dialog

    def go_to_recipes(self, *_):
        self.stack.set_visible_child_name('recipes')

    def choose_recipe(self, *_):
        chooser = Gtk.FileDialog(title="Choose a setup recipe")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        item = Gtk.FileFilter(name="TOML setup recipes")
        item.add_pattern("*.toml")
        filters.append(item)
        chooser.set_filters(filters)
        chooser.open(self.window, None, self.recipe_chosen)

    def recipe_chosen(self, chooser, result):
        try:
            selected = chooser.open_finish(result)
        except GLib.Error:
            return
        if not selected or not selected.get_path():
            return
        path = Path(selected.get_path())
        import threading
        def task():
            # Read and describe it. Adding is a second, separate decision, made
            # after seeing the description rather than before.
            from . import recipe_engine, recipe_report
            try:
                candidate = recipe_engine.load(path)
                reference = recipe_engine.reference(candidate)
                records, _ = recipe_engine.usable_catalogue(recipe_engine.default_directories())
                records = {**records, reference: candidate}
                summary = recipe_report.report(records, reference, source=path, tier='local')
                GLib.idle_add(self.preview_recipe, summary, path)
            except Exception as exc:
                GLib.idle_add(self.message, 'Could not read this recipe', str(exc))
        threading.Thread(target=task, daemon=True).start()

    def preview_recipe(self, summary, path):
        """Show what a recipe would be allowed to do, before it is added."""
        self.preview = dialog = self.recipe_window('Add this recipe?', summary, str(path))
        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancel = Gtk.Button(label='Cancel')
        cancel.connect('clicked', lambda *_: dialog.close())
        buttons.append(cancel)
        add = Gtk.Button(label='Add recipe')
        add.add_css_class('suggested-action')
        if summary['verdict'] == 'refused':
            add.set_sensitive(False)
            add.set_tooltip_text('This recipe declares more than its kind is allowed to.')
        add.connect('clicked', lambda *_: self.add_recipe(dialog, path))
        buttons.append(add)
        dialog.footer.append(buttons)
        dialog.present()
        return False

    def add_recipe(self, dialog, path):
        dialog.close()
        import threading
        def task():
            from . import recipe_engine
            try:
                added = recipe_engine.add_local(path)
                GLib.idle_add(self.recipe_added, added)
            except Exception as exc:
                GLib.idle_add(self.message, 'Could not add this recipe', str(exc))
        threading.Thread(target=task, daemon=True).start()

    def recipe_added(self, result):
        self.last = None
        self.refresh()
        self.load_recipes()
        self.message('Recipe added' if result['added'] else 'This recipe was already available',
                     result['reference'])
        return False

    def remove_recipe(self, summary):
        """Removing the file does not touch anything it already installed."""
        dialog = Gtk.AlertDialog(
            message='Remove ' + summary['name'] + '?',
            detail='This deletes the recipe file you added. Environments it already built, and the '
                   'plug-ins in them, are unaffected — a finished installation keeps its own copy '
                   'of what it was built from.',
            buttons=['Cancel', 'Remove'], cancel_button=0, default_button=0)

        def answered(source, result):
            try:
                if source.choose_finish(result) != 1:
                    return
            except GLib.Error:
                return
            import threading
            def task():
                from . import recipe_engine
                try:
                    recipe_engine.remove_local(summary['reference'])
                    GLib.idle_add(self.recipe_removed, summary['reference'])
                except Exception as exc:
                    GLib.idle_add(self.message, 'Could not remove this recipe', str(exc))
            threading.Thread(target=task, daemon=True).start()
        dialog.choose(self.window, None, answered)

    def recipe_removed(self, reference):
        self.last = None
        self.refresh()
        self.load_recipes()
        self.message('Recipe removed', reference)
        return False

    def load_recipes(self, *_):
        """Read the catalogue off the main loop; it is files on disk."""
        import threading
        def task():
            from . import recipe_engine, recipe_report
            try:
                records, issues = recipe_engine.usable_catalogue(recipe_engine.default_directories())
                mine = recipe_engine.default_directories()[-1].resolve()
                found = []
                for reference, record in sorted(records.items()):
                    if record['data']['kind'] == 'component':
                        continue
                    summary = recipe_report.report(records, reference)
                    summary['removable'] = Path(record['source']).resolve().parent == mine
                    found.append(summary)
                payload = {'recipes': found, 'components': recipe_report.component_index(records),
                           'issues': issues}
            except Exception as exc:
                payload = {'recipes': [], 'components': [], 'error': str(exc)}
            GLib.idle_add(self.recipes_loaded, payload)
        threading.Thread(target=task, daemon=True).start()

    def chip(self, text, level=None):
        widget = label(text, 'chip')
        if level:
            widget.add_css_class('chip-' + level)
        widget.set_valign(Gtk.Align.CENTER)
        return widget

    LEVEL = {'refused': 'danger', 'needs-review': 'danger', 'check-the-details': 'caution'}

    def catalogue_search_changed(self, entry):
        self.catalogue_query = entry.get_text().strip().casefold()
        if self.catalogue_payload is not None:
            self.render_recipes()

    def catalogue_scope_changed(self, *_):
        if self.catalogue_payload is not None:
            self.render_recipes()

    def recipes_loaded(self, payload):
        self.catalogue_payload = payload
        return self.render_recipes()

    def render_recipes(self):
        payload = self.catalogue_payload
        def matches(item):
            text = ' '.join(str(item.get(key) or '') for key in ('name', 'reference', 'purpose', 'notes', 'vendor'))
            text += ' ' + ' '.join(user['name'] for user in item.get('used_by', []))
            return all(word in text.casefold() for word in self.catalogue_query.split())
        all_recipes = payload.get('recipes', [])
        latest = {}
        for item in all_recipes + payload.get('components', []):
            identity, revision = item['reference'].rsplit('@', 1)
            latest[identity] = max(latest.get(identity, 0), int(revision))
        def historical(item):
            identity, revision = item['reference'].rsplit('@', 1)
            return int(revision) < latest.get(identity, int(revision))
        recipes = [item for item in all_recipes
                   if (self.catalogue_history.get_active() or not historical(item)) and matches(item)]
        components = [item for item in payload.get('components', [])
                      if (self.catalogue_history.get_active() or not historical(item)) and matches(item)]
        scope = self.catalogue_scope.get_selected()
        self.clear(self.recipes)
        if payload.get('error'):
            self.recipes.append(label(payload['error'], 'error', True))
            return False
        self.recipes_heading.set_text('Recipes & components')
        if scope != 2:
            self.recipes.append(label('Vendor setups · %d' % len(recipes), 'section-title'))
            self.recipes.append(label('Each revision is a complete setup recipe. Components are its reusable parts.', 'muted', True))
        for summary in recipes if scope != 2 else []:
            row = Gtk.Box(spacing=12)
            row.add_css_class('card')
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            text.set_hexpand(True)
            text.append(label(summary['name'], 'card-title', True))
            chips = Gtk.Box(spacing=6)
            revision = summary['reference'].rsplit('@', 1)[-1]
            if revision != '1' or historical(summary):
                chips.append(self.chip('Revision ' + revision))
            if historical(summary):
                chips.append(self.chip('Older revision'))
            from .recipe_report import catalogue_badge
            badge_text, badge_level = catalogue_badge(summary)
            chips.append(self.chip(badge_text, badge_level))
            text.append(chips)
            if summary.get('runtime'):
                text.append(label('Runtime: ' + summary['runtime']['summary'], 'muted', True))
            if summary.get('revision_note'):
                text.append(label(summary['revision_note'], None, True))
            if summary.get('components'):
                text.append(label('Components: ' + '; '.join(
                    item['name'] for item in summary['components']), 'muted', True))
            # Keep the action boundary visible alongside the complete component list.
            worst = summary['flags'][0]['message'] if summary['flags'] else \
                'Changes settings only; downloads and runs nothing.'
            if 'https://' in worst or len(worst) > 180:
                worst = '. '.join(list(summary['capability_descriptions'].values())[:2]) + '.'
            if summary.get('documentation_only'):
                worst = summary.get('notes') or 'Documents requirements only. Cannot be applied to an environment.'
            text.append(label(worst, 'muted', True))
            row.append(text)
            explain = Gtk.Button(label='What it does…')
            explain.connect('clicked', lambda _b, s=summary: self.show_recipe(s))
            buttons = [explain]
            if summary['removable']:
                remove = Gtk.Button(label='Remove')
                remove.add_css_class('dim')
                remove.connect('clicked', lambda _b, s=summary: self.remove_recipe(s))
                buttons.append(remove)
            grid = self.button_grid(buttons, columns=1)
            grid.set_valign(Gtk.Align.CENTER)
            grid.set_halign(Gtk.Align.END)
            grid.set_hexpand(False)
            row.append(grid)
            self.recipes.append(row)
        if not recipes and scope != 2:
            self.recipes.append(label('No setup recipes match your search.' if self.catalogue_query else 'No recipes yet. The ones shipped with the app appear here too.',
                                      'muted', True))
        for issue in payload.get('issues') or []:
            self.recipes.append(label((issue.get('reference') or issue.get('source', '')) + ' was ignored: '
                                      + issue['error'], 'error', True))
        if scope == 1:
            return False
        self.recipes.append(label('Reusable components · %d' % len(components), 'section-title'))
        self.recipes.append(label('Use these parts in a recipe. Adding a recipe does not apply it to your installed plug-ins.', 'muted', True))
        parts = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=False,
                            min_children_per_line=1, max_children_per_line=2,
                            row_spacing=10, column_spacing=10)
        for item in components:
            entry = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            entry.add_css_class('card')
            entry.add_css_class('component-card')
            entry.set_size_request(300, -1)
            names = {'plugg.bridge-editor-detach@1': 'Editor close fix',
                     'plugg.ole32-foreign-window-guard@1': 'Drag-and-drop editor close fix',
                     'plugg.vc2013-x64@1': 'Visual C++ 2013 runtime',
                     'plugg.vc2022-x64@1': 'Visual C++ 2015–2022 runtime',
                     'plugg.graphics-wined3d@1': 'WineD3D graphics'}
            entry.append(label(names.get(item['reference'], item['name']), 'card-title', True))
            purpose = label(item['purpose'] or item['name'], 'component-purpose', wrap=True)
            purpose.set_max_width_chars(56)
            entry.append(purpose)
            capabilities = set(item['capabilities'])
            if capabilities & {'require-bridge-patch', 'require-existing-files'}:
                action = 'Requires an existing fix. Does not install the patch.'
            elif 'download-component' in capabilities:
                action = 'Installs a Windows runtime component.'
            elif 'install-ntk-daemon' in capabilities:
                action = 'Installs the bundled service and starts it with Native Access.'
            elif 'install-powershell' in capabilities:
                action = 'Installs Microsoft PowerShell and the forwarding launcher.'
            elif 'prepare-archive-tools' in capabilities:
                action = 'Installs extraction tools during helper setup.'
            elif 'configure-graphics' in capabilities:
                action = 'Applies graphics settings.'
            else:
                action = 'See details for the actions this component declares.'
            if (item.get('report') or {}).get('documentation_only'):
                action = 'Fresh automated setup not available yet.'
            entry.append(label(action, 'muted', True))
            consumers = [user for user in item.get('used_by', [])
                         if self.catalogue_history.get_active() or not historical(user)]
            if consumers:
                entry.append(label('Required by recipes', 'muted'))
                owners = {summary['reference']: summary for summary in payload['recipes']}
                for user in consumers:
                    revision = user['reference'].rsplit('@', 1)[-1]
                    name = user['name']
                    if revision != '1' or historical(user):
                        name += ' (r' + revision + ')'
                    if user['reference'] in owners:
                        link = Gtk.Button(label=name, halign=Gtk.Align.START)
                        link.add_css_class('recipe-link')
                        link.set_tooltip_text(name)
                        link.get_child().set_ellipsize(Pango.EllipsizeMode.END)
                        link.get_child().set_max_width_chars(44)
                        link.connect('clicked', lambda _, summary=owners[user['reference']]: self.show_recipe(summary))
                        entry.append(link)
                    else:
                        entry.append(label(name, 'muted', True))
            else:
                entry.append(label('No declared recipe dependencies; existing use may differ.', 'muted', True))
            if item.get('report'):
                details = Gtk.Button(label='Component details…', halign=Gtk.Align.START)
                details.add_css_class('compact')
                details.connect('clicked', lambda _, summary=item['report']: self.show_recipe(summary))
                entry.append(details)
            parts.insert(entry, -1)
        self.recipes.append(parts)
        if not components:
            self.recipes.append(label('No components match your search.' if self.catalogue_query else 'No reusable components in this catalogue.', 'muted', True))
        return False

    def show_recipe(self, summary):
        dialog = self.recipe_window(summary['name'], summary, summary['source'])
        close = Gtk.Button(label='Close', halign=Gtk.Align.END)
        close.connect('clicked', lambda *_: dialog.close())
        dialog.footer.append(close)
        dialog.present()
        return dialog

    def recipe_window(self, title, summary, source):
        """What a recipe can do, as the report rather than as its source text.

        Printing the TOML would be honest and useless: the question is not what
        the file says, it is what the file is permitted to do to a machine that
        may hold licences. That is derived, so it can be shown as a list.
        """
        from .recipe_report import VERDICTS
        dialog = Gtk.Window(title=title, transient_for=self.window, modal=True)
        dialog.set_default_size(640, 620)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for edge in ('top', 'bottom', 'start', 'end'):
            getattr(outer, 'set_margin_' + edge)(16)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        head.append(label(summary['name'], 'plugin-name', True))
        chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,
                            min_children_per_line=1, max_children_per_line=3,
                            row_spacing=4, column_spacing=4)
        values = [(summary['reference'], None), (summary['tier'], None)]
        if summary.get('vendor'):
            values.append((summary['vendor'], None))
        values.append((VERDICTS[summary['verdict']], self.LEVEL.get(summary['verdict'])))
        for text, level in values:
            chip = self.chip(text, level)
            chip.set_wrap(True)
            chip.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            chip.set_max_width_chars(48)
            chips.insert(chip, -1)
        head.append(chips)
        if summary.get('revision_note'):
            head.append(label(summary['revision_note'], None, True))
        if summary.get('notes'):
            head.append(label(summary['notes'], 'muted', True))
        if summary.get('existing_setup'):
            head.append(label('Setup in an existing protected iLok environment is available through recipe setup-existing. Fresh PACE provisioning is not automated.', 'muted', True))
        elif summary.get('documentation_only'):
            head.append(label('Documentation only. This setup cannot be applied. Existing installations are not changed.', 'muted', True))
        body.append(head)

        def section(heading, lines, css=None):
            if not lines:
                return
            group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            group.append(label(heading, 'card-title'))
            for text, style in lines:
                item = label('• ' + text, style or css, True)
                item.set_selectable(True)
                group.append(item)
            body.append(group)

        runtime = summary.get('runtime')
        if runtime:
            section('Runtime', [(runtime['summary'], None)] +
                    [(text, 'muted') for text in runtime['details']])
            section('Pinned runtime downloads',
                    [(asset['url'] + '\nsha256 ' + asset['sha256'], 'pinned')
                     for asset in runtime['assets']])
        section('What it can do',
                [(text, None) for text in summary['capability_descriptions'].values()]
                or [('Nothing on its own — it is a building block other recipes name.', 'muted')])
        evidence = summary.get('evidence')
        if summary.get('kind') == 'component':
            section('Recorded evidence', [(evidence['summary'], None), (evidence['limitations'], 'muted')]
                    if evidence else [('No compatibility evidence is attached to this exact component revision.', 'muted')])
            if evidence:
                source_path = Path(__file__).resolve().parents[1] / evidence['source']
                if source_path.is_file():
                    link = Gtk.LinkButton(uri=source_path.as_uri(), label='Open test notes', halign=Gtk.Align.START)
                    body.append(link)
                else:
                    body.append(label('Source: ' + evidence['source'], 'pinned', True))
        section('Worth looking at',
                [(item['message'], 'flag-' + item['level'] if item['level'] != 'note' else 'muted')
                 for item in summary['flags']])
        section('Downloads, pinned to an exact file',
                [(item['url'] + '\nsha256 ' + item['sha256'], 'pinned') for item in summary['downloads']])
        section('Runs',
                [(item['what'] + '\n' + (' '.join(item['arguments']) or '(no arguments)'), 'pinned')
                 for item in summary['runs']])
        section('Recognizes by hash, but does not ship',
                [('%s %s (%s…)' % (claim['kind'], claim['name'], claim['sha256'][:12]), 'pinned')
                 for claim in summary['claims']])
        section('Built from', [(item['reference'] + (' — ' + item['purpose'] if item['purpose'] else ''), None)
                               for item in summary['components']])
        origin = label(source + '\nsha256 ' + summary['sha256'], 'pinned', True)
        origin.set_selectable(True)
        body.append(origin)
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(body)
        outer.append(scroll)
        dialog.footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.append(dialog.footer)
        dialog.set_child(outer)
        return dialog

    def native_access_sign_in(self, job_id):
        dialog = Gtk.Window(title='Complete Native Access sign-in', transient_for=self.window, modal=True)
        dialog.set_default_size(500, 180)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for edge in ('top', 'bottom', 'start', 'end'):
            getattr(box, 'set_margin_' + edge)(16)
        box.append(label('Copy the native-access:// return link from your browser and paste it here. It is sent only to this setup and is not saved.', wrap=True))
        entry = Gtk.Entry(visibility=False, placeholder_text='Browser return link')
        box.append(entry)
        submit = Gtk.Button(label='Complete sign-in')
        def send(_):
            from . import native_access, vendors
            uri = entry.get_text()
            entry.set_text('')
            try:
                directory, _ = vendors.configuration(self.store, job_id)
                native_access.complete_sign_in(directory, uri)
            except Exception:
                self.message('Sign-in link not accepted', 'Use the native-access:// return link from your browser. Do not paste passwords here.')
            else:
                dialog.close()
        submit.connect('clicked', send)
        box.append(submit)
        dialog.set_child(box)
        dialog.present()
        return dialog

    def choose(self, *_):
        chooser = Gtk.FileDialog(title="Choose a Windows installer or VST3")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        item = Gtk.FileFilter(name="Windows installers and VST3 plug-ins")
        for pattern in ("*.exe", "*.EXE", "*.msi", "*.MSI", "*.vst3", "*.VST3"):
            item.add_pattern(pattern)
        filters.append(item)
        chooser.set_filters(filters)
        chooser.open(self.window, None, self.chosen)

    def chosen(self, chooser, result):
        try:
            selected = chooser.open_finish(result)
            if selected and selected.get_path():
                self.install(Path(selected.get_path()))
        except GLib.Error:
            pass

    def drop(self, _, files, x, y):
        accepted = False
        for file in files.get_files():
            if file.get_path():
                self.install(Path(file.get_path()))
                accepted = True
        return accepted

    def install(self, path, replace=False):
        """Take the file in, and say so before anything slow begins.

        Copying an installer and preparing an environment take a while, and
        until one of them wrote something there was nothing on screen to say
        the drop had registered at all — so the natural response was to drop it
        again, and again, each one a real job. The same file arriving twice
        while the first is still being taken in is now ignored, and the work
        announces itself immediately rather than once it has something to show.
        """
        import threading
        from .core import DuplicateInstaller, SharedEnvironmentInstaller
        path = Path(path)
        key = str(path)
        if key in self.pending:
            return
        self.pending[key] = path.name
        self.last = None
        self.refresh()

        def task():
            try:
                job = self.store.ingest(path, replace=replace)
                self.store.start(job)
            except SharedEnvironmentInstaller as exc:
                GLib.idle_add(self.offer_join, path, exc)
            except DuplicateInstaller as exc:
                if exc.replaceable:
                    GLib.idle_add(self.offer_replace, path, str(exc))
                else:
                    GLib.idle_add(self.message, 'Already being added', str(exc))
            except Exception as exc:
                GLib.idle_add(self.message, "Could not start installation", str(exc))
            finally:
                GLib.idle_add(self.intake_finished, key)
        threading.Thread(target=task, daemon=False).start()

    def offer_join(self, path, shared):
        """Softube Central and UA Connect join the iLok environment; ask first."""
        ua = shared.recipe.startswith('plugg.universal-audio')
        detail = (shared.name + ' is licensed through iLok, so Plugg adds it to your iLok environment '
                  'instead of making a new one. It unpacks the reviewed installer, copies in what is '
                  'missing and never runs the bundled PACE setup. PACE and this computer\'s identity '
                  'are checked before and after.')
        if ua:
            detail += ('\n\nUA Connect then runs with --disable-gpu --no-sandbox, without which it '
                       'shows a blank window under Wine. That turns off Chromium\'s process sandbox for '
                       'UA Connect only, never for plug-ins.')
        else:
            detail += '\n\nIf the environment has no PowerShell yet, Plugg adds it first.'
        detail += '\n\nClose your DAW and any manager windows before continuing.'
        dialog = Gtk.AlertDialog(message='Add ' + shared.name + ' to your iLok environment?', detail=detail,
                                 buttons=['Cancel', 'Add ' + shared.name], cancel_button=0, default_button=0)

        def chosen(source, result):
            try:
                if source.choose_finish(result) == 1:
                    self.join_shared(path, shared)
            except GLib.Error:
                pass
        dialog.choose(self.window, None, chosen)
        return False

    def join_shared(self, path, shared):
        import threading
        from . import core
        key = 'join:' + str(path)
        self.pending[key] = 'join:' + shared.name
        self.refresh()

        def task():
            command = core.plugg_command('--data', self.store.root, 'recipe', 'setup-existing', shared.recipe,
                                         '--installer', path, '--environment', shared.environment)
            if shared.recipe.startswith('plugg.universal-audio'):
                command.append('--allow-electron-no-sandbox')
            try:
                done = subprocess.run(command, cwd=self.store.root, capture_output=True, text=True, timeout=1800)
                if done.returncode:
                    reason = [line for line in (done.stderr or done.stdout).splitlines() if line.strip()]
                    GLib.idle_add(self.message, 'Could not add ' + shared.name,
                                  reason[-1] if reason else 'Setup stopped with code ' + str(done.returncode) + '.')
                else:
                    GLib.idle_add(self.message, shared.name + ' added',
                                  'Open it from its card to install products. Closing it publishes what it installed.')
            except Exception as exc:
                GLib.idle_add(self.message, 'Could not add ' + shared.name, str(exc))
            finally:
                GLib.idle_add(self.intake_finished, key)
        threading.Thread(target=task, daemon=False).start()

    def offer_replace(self, path, detail):
        """The same file again usually means "do that one over", so offer it."""
        dialog = Gtk.AlertDialog(
            message='Install this again?',
            detail=detail + '\n\nInstalling it again archives that installation and retires the '
                            'plug-ins it published, then sets it up from scratch. Your files and '
                            'the vendor\'s own licensing are untouched, and the archived '
                            'installation keeps everything it had.',
            buttons=['Cancel', 'Install again'], cancel_button=0, default_button=0)

        def chosen(source, result):
            try:
                if source.choose_finish(result) == 1:
                    self.install(path, replace=True)
            except GLib.Error:
                pass
        dialog.choose(self.window, None, chosen)
        return False

    def cancel_job(self, job_id):
        try:
            self.store.cancel(job_id)
        except Exception as exc:
            self.message('Could not cancel', str(exc))
        self.last = None
        self.refresh()

    def intake_finished(self, key):
        self.pending.pop(key, None)
        self.last = None
        self.refresh()
        return False

    def softube_action(self, directory):
        from . import softube
        try:
            softube.start(directory)
        except Exception as exc:
            self.message('Could not open Softube Central', str(exc))

    def manager_action(self, job_id, name):
        try:
            vendors.open_manager(self.store, job_id, name)
        except Exception as exc:
            self.message('Could not open ' + name, str(exc))

    def vendor_action(self, job_id, refresh=False):
        try:
            vendors.start(self.store, job_id, refresh)
        except Exception as exc:
            self.message("Could not manage installation", str(exc))

    def show_helper(self, job_id, ilok=False):
        """Try to go back into an application that is running without a window."""
        import threading

        def task():
            try:
                result = vendors.show_helper(self.store, job_id, ilok=ilok)
            except Exception as exc:
                GLib.idle_add(self.message, 'Could not open that window', str(exc))
                return
            if not result['restored']:
                GLib.idle_add(
                    self.message, result['title'] + ' did not come back',
                    'It is still running, but it made no window. A window that was closed — '
                    'rather than minimized — is gone for good in some applications, and only '
                    'that application can decide to make another.\n\nUse Force close, then open '
                    'it again from this card.')
        threading.Thread(target=task, daemon=True).start()

    def stop_helper(self, job_id, name):
        """Offer a way out when a vendor application outlives its window.

        Closing a window does not always end the program behind it — Electron
        helpers in particular keep running with no window at all — and the card
        then waits for an exit that will not come. The interface must not guess
        that from a vanished window, so the person asking is the signal.

        What it ends is the environment, not one application: products sharing
        a prefix with a licence manager go together, because they share one Wine
        server. So the question names them rather than describing them, and the
        answer is not a surprise.
        """
        try:
            running = vendors.program_names(self.store.prefix(job_id))
        except Exception:
            running = []
        if running:
            listed = ', '.join(running[:6]) + (', and others' if len(running) > 6 else '')
            detail = ('This ends every Windows program in that environment, including any '
                      'installation still in progress:\n\n' + listed)
        else:
            detail = ('Nothing is running in that environment now. This clears the status the '
                      'card is still showing.')
        dialog = Gtk.AlertDialog(message='Force close ' + name + '?', detail=detail,
                                 buttons=['Cancel', 'Force close'],
                                 cancel_button=0, default_button=0)

        def chosen(source, result):
            try:
                if source.choose_finish(result) != 1:
                    return
            except GLib.Error:
                return
            self.force_close(job_id)
        dialog.choose(self.window, None, chosen)

    def force_close(self, job_id):
        """Stopping waits for the programs to go; keep the window answering."""
        import threading

        def task():
            try:
                result = vendors.stop_helper(self.store, job_id)
                if not result['settled']:
                    # The programs are gone; only the status could not be
                    # cleared yet. Saying so is not the same as failing.
                    GLib.idle_add(self.message, 'Programs ended',
                                  'An operation in this environment has not finished writing '
                                  'its result. The card will update when it does.')
            except Exception as exc:
                GLib.idle_add(self.message, 'Could not force close', str(exc))
            finally:
                GLib.idle_add(self.stopped)
        threading.Thread(target=task, daemon=False).start()

    def stopped(self):
        self.last = None
        self.refresh()
        return False

    def open_ilok(self, job_id):
        try:
            _, cfg = vendors.configuration(self.store, job_id)
            vendors.open_native_access(self.store.prefix(job_id), cfg['ilok_launcher'], title='iLok License Manager')
        except Exception as exc:
            self.message('Could not open iLok', str(exc))

    def discard_job(self, job_id):
        """Forget an attempt. Its environment, if it made one, is not touched."""
        try:
            self.store.discard(job_id)
        except Exception as exc:
            self.message('Could not discard this attempt', str(exc))
        self.last = None
        self.refresh()

    def archive_job(self, job_id, archived):
        try:
            self.store.archive(job_id, archived)
            self.last = None
            self.refresh()
        except Exception as exc:
            self.message("Could not archive attempt", str(exc))

    def rescan(self, job_id):
        try:
            self.store.start(job_id, rescan=True)
        except Exception as exc:
            self.message("Could not check installation", str(exc))

    def job_details(self, job):
        job = self.store.job(job['id'])
        path = self.store.root / "jobs" / job["id"]
        dialog = Gtk.Window(title="Installation details", transient_for=self.window, modal=True)
        dialog.set_default_size(540, 360)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(body, 'set_margin_' + side)(20)
        title = label(job['name'], 'plugin-name', True)
        body.append(title)
        lines = [job['message'], 'Saved file: ' + Path(job['installer']).name,
                 *licensing_summary(self.store.root, job['env_id']),
                 *setup_recipe_summary(self.store.root, job),
                 *installation_progress(self.store.root, job)]
        for text in lines:
            detail = label(text, wrap=True)
            detail.set_selectable(True)
            detail.set_max_width_chars(60)
            body.append(detail)
        files = Gtk.Button(label='Open installation files')
        files.set_halign(Gtk.Align.START)
        files.connect('clicked', lambda _: Gio.AppInfo.launch_default_for_uri(path.as_uri(), None))
        body.append(files)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(body)
        dialog.set_child(scroll)
        dialog.present()
        return dialog

    @staticmethod
    def clear(box):
        while child := box.get_first_child():
            box.remove(child)

    def measure_environments(self, force=False):
        import threading
        if self.measuring:
            return
        self.measuring = True

        def task():
            from . import environments as survey
            found = {}
            try:
                for record in survey.survey(self.store):
                    if force or record['id'] not in self.sizes:
                        found[record['id']] = survey.measure(record['path'])
            except Exception:
                found = {}
            GLib.idle_add(self.measured, found)
        threading.Thread(target=task, daemon=True).start()

    def measured(self, found):
        self.measuring = False
        if found:
            self.sizes.update(found)
            self.last = None
            self.refresh()
        return False

    def delete_environment(self, record):
        """Ask for the words, and say plainly what will not survive.

        Nothing here can be undone and no recovery point covers it — a recovery
        point holds identity files, a few kilobytes, not the gigabytes that
        made someone want the space back. So this dialog's job is to be read.
        """
        from . import environments as survey
        phrase = survey.removal_phrase(record)
        stopped = survey.blockers(self.store, record)
        linked = None
        try:
            _, linked = survey.entry(self.store, record)
        except Exception:
            pass
        dialog = Gtk.Window(title='Delete environment', transient_for=self.window, modal=True)
        dialog.set_default_size(580, 420)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(body, 'set_margin_' + side)(20)
        body.append(label('Delete ' + survey.summarize(record) + '?', 'section-title'))
        if linked is not None:
            # Not ours to delete. Say so here, where it is still a choice.
            lines = ['This entry is a link into another library. Deleting it here removes the '
                     'link and this library’s record of it; the environment itself stays where '
                     'it is:', str(linked)]
        else:
            lines = ['This deletes the environment, everything installed in it and its settings. '
                     'It cannot be undone, and no recovery point covers it.']
        if record['plugins']:
            lines.append('Installed here: ' + ', '.join(record['plugins']) + '. Your DAW stops seeing them, '
                         'and Plugg removes the adapters it built for them.')
        if record['jobs']:
            lines.append('Also forgets %d installation record%s and the installer copies kept '
                         'with them.' % (len(record['jobs']), '' if len(record['jobs']) == 1 else 's'))
        if record['protected']:
            lines.append('It was set up for '
                         + (', '.join(record['products']) or 'recorded products')
                         + '. Nothing here asks the vendor whether those are still activated — '
                         'you are the only one who knows. Deactivate them in the vendor’s own '
                         'manager if you have not already; typing the phrase below is how you '
                         'say that you have.')
        size = self.sizes.get(record['id'])
        if size and linked is None:
            lines.append('Frees about ' + survey.readable(size) + '.')
        for line in lines:
            body.append(label(line, 'muted', True))
        for reason in stopped:
            body.append(label(reason, 'error', True))
        body.append(label('Type this exactly to confirm:', 'status'))
        body.append(label(phrase, 'plugin-name', True))
        typed = Gtk.Entry(placeholder_text=phrase)
        typed.set_sensitive(not stopped)
        body.append(typed)
        actions = Gtk.Box(spacing=8)
        actions.set_halign(Gtk.Align.END)
        actions.set_vexpand(True)
        actions.set_valign(Gtk.Align.END)
        cancel = Gtk.Button(label='Cancel')
        cancel.connect('clicked', lambda *_: dialog.close())
        actions.append(cancel)
        confirm = Gtk.Button(label='Remove link' if linked is not None else 'Delete permanently')
        confirm.add_css_class('destructive')
        confirm.set_sensitive(False)
        typed.connect('changed', lambda entry: confirm.set_sensitive(
            not stopped and entry.get_text() == phrase))
        confirm.connect('clicked', lambda *_: self.run_delete(dialog, record, typed.get_text()))
        actions.append(confirm)
        body.append(actions)
        dialog.set_child(body)
        dialog.present()
        return dialog

    def run_delete(self, dialog, record, confirmation):
        from . import environments as survey
        try:
            survey.remove(self.store, record, confirmation)
        except Exception as exc:
            self.message('Could not delete this environment', str(exc))
            return
        dialog.close()
        self.sizes.pop(record['id'], None)
        self.breakdown = None
        self.measure_library()
        self.last = None
        self.refresh()

    def use_helper(self, env_id, program):
        try:
            vendors.adopt_helper(self.store, env_id, program, Path(program).stem)
        except Exception as exc:
            self.message('Could not use this as a helper', str(exc))
        self.last = None
        self.refresh()

    def adopt_helper(self, record):
        from . import environments as survey
        candidates = vendors.helper_candidates(record['path'])
        if not candidates:
            self.message('No vendor app found', 'This environment has no program outside Windows itself that '
                         'looks like a vendor app.')
            return
        dialog = Gtk.Window(title='Use as helper', transient_for=self.window, modal=True)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(body, 'set_margin_' + side)(20)
        body.append(label('Which program manages ' + survey.summarize(record) + '?', 'section-title'))
        body.append(label('It gets a card under Helpers. Opening it and closing it refreshes the library, '
                          'like any other vendor helper.', 'muted', True))
        choice = Gtk.DropDown.new_from_strings(['C:\\' + c.replace('/', '\\') for c in candidates])
        body.append(choice)
        entry = Gtk.Entry(text=Path(candidates[0]).stem)
        entry.set_max_length(60)
        choice.connect('notify::selected', lambda *_: entry.set_text(Path(candidates[choice.get_selected()]).stem))
        body.append(label('Name on the card', 'status'))
        body.append(entry)
        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancel = Gtk.Button(label='Cancel')
        cancel.connect('clicked', lambda _: dialog.close())
        save = Gtk.Button(label='Use as helper')
        save.add_css_class('suggested-action')

        def chosen(*_):
            try:
                vendors.adopt_helper(self.store, record['id'], candidates[choice.get_selected()], entry.get_text())
            except Exception as exc:
                self.message('Could not use this as a helper', str(exc))
                return
            dialog.close()
            self.last = None
            self.refresh()
        save.connect('clicked', chosen)
        buttons.append(cancel)
        buttons.append(save)
        body.append(buttons)
        dialog.set_child(body)
        dialog.present()

    def rename_environment(self, record):
        from . import environments as survey
        dialog = Gtk.Window(title='Rename environment', transient_for=self.window, modal=True)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(body, 'set_margin_' + side)(20)
        body.append(label('Name for ' + record['id'][:8], 'section-title'))
        body.append(label('Only the name shown here changes. The folder keeps its ID, because '
                          'launchers, published plug-ins and licensing records refer to it.', 'muted', True))
        entry = Gtk.Entry(text=record.get('name') or survey.summarize(record))
        entry.set_max_length(survey.NAME_LIMIT)
        body.append(entry)
        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancel = Gtk.Button(label='Cancel')
        cancel.connect('clicked', lambda _: dialog.close())
        save = Gtk.Button(label='Save')
        save.add_css_class('suggested-action')

        def saved(*_):
            try:
                survey.rename(self.store, record['id'], entry.get_text())
            except Exception as exc:
                self.message('Could not rename', str(exc))
                return
            dialog.close()
            self.last = None
            self.refresh()
        save.connect('clicked', saved)
        entry.connect('activate', saved)
        buttons.append(cancel)
        buttons.append(save)
        body.append(buttons)
        dialog.set_child(body)
        dialog.present()

    def reclaim_runtime(self, name):
        """Free a runtime nothing refers to. It comes back by download if needed."""
        from . import environments as survey
        try:
            survey.remove_runtime(self.store, name)
        except Exception as exc:
            self.message('Could not reclaim this runtime', str(exc))
        self.sizes.clear()
        self.last = None
        self.refresh()

    def helper_offers(self, record):
        """Apps an installer without a recipe left behind, cached until the environment changes."""
        if record.get('recipe') != 'installer' or record.get('dangling'):
            return []
        directory = Path(record['path'])
        key = (record['id'], max((j.get('updated') or 0) for j in self.store.jobs()
                                 if j['env_id'] == record['id']) if record['jobs'] else 0)
        if key not in self.helper_offers_cache:
            try:
                self.helper_offers_cache[key] = vendors.helper_candidates(directory)
            except Exception:
                self.helper_offers_cache[key] = []
        return self.helper_offers_cache[key]

    def plugin_facts(self, plugin):
        """What the library knows about one published plug-in, for its details popover.

        The same facts the old plug-in list showed: maker and version, the file
        a DAW sees (all a DAW names when it refuses one), where it came from,
        and the saved installer or setup recipe behind it.
        """
        jobs = self.store.jobs()
        setups = self.last[2] if self.last else []
        lines, actions = [], []
        try:
            classes = json.loads(plugin.get('metadata') or '{}').get('classes') or []
        except ValueError:
            classes = []
        info = classes[0] if classes else {}
        maker = ' · '.join(x for x in ((info.get('vendor') or '').strip(),
                                       ('version ' + info['version'].strip()) if (info.get('version') or '').strip()
                                       else '') if x)
        if maker:
            lines.append(maker)
        if plugin.get('publication'):
            lines.append('Your DAW sees: ' + Path(plugin['publication']).name)
        source, job = installation_source(plugin, jobs, setups)
        if source:
            lines.append(source)
        if job:
            if job['id'] not in {s['job'] for s in setups}:
                lines.append('Saved file: ' + Path(job['installer']).name)
                folder = Path(job['installer']).parent
                actions.append(('Open saved files',
                                lambda: Gio.AppInfo.launch_default_for_uri(folder.as_uri(), None)))
            lines.extend(setup_recipe_summary(self.store.root, job))
        problem = None if plugin.get('status') == 'ready' else (plugin.get('message') or 'This plug-in needs attention.')
        return {'lines': lines, 'actions': actions, 'problem': problem}

    def remove_dead_bundle(self, name):
        """Remove an adapter whose plug-in is gone. It holds nothing, so nothing needs typing first."""
        from . import environments as survey
        try:
            survey.remove_dead_bundle(self.store, name)
        except Exception as exc:
            self.message('Could not remove this leftover', str(exc))
        self.breakdown = None
        self.measure_library()
        self.last = None
        self.refresh()

    def delete_nested(self, nested):
        """A nested library holds environments, so it is asked for like one."""
        from . import environments as survey
        phrase = survey.nested_phrase(nested['name'])
        dialog = Gtk.Window(title='Delete separate library', transient_for=self.window, modal=True)
        dialog.set_default_size(560, 340)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(body, 'set_margin_' + side)(20)
        body.append(label('Delete the separate library "' + nested['name'] + '"?', 'section-title'))
        body.append(label('This is a complete library of its own: %d environment%s, its own '
                          'database, downloads and runtimes. Anything installed or activated in '
                          'it goes too, and it cannot be undone.'
                          % (nested['environments'], '' if nested['environments'] == 1 else 's'),
                          'muted', True))
        body.append(label(nested['path'], 'status', True))
        body.append(label('Type this exactly to confirm:', 'status'))
        body.append(label(phrase, 'plugin-name', True))
        typed = Gtk.Entry(placeholder_text=phrase)
        body.append(typed)
        actions = Gtk.Box(spacing=8)
        actions.set_halign(Gtk.Align.END)
        actions.set_vexpand(True)
        actions.set_valign(Gtk.Align.END)
        cancel = Gtk.Button(label='Cancel')
        cancel.connect('clicked', lambda *_: dialog.close())
        actions.append(cancel)
        confirm = Gtk.Button(label='Delete permanently')
        confirm.add_css_class('destructive')
        confirm.set_sensitive(False)
        typed.connect('changed', lambda entry: confirm.set_sensitive(entry.get_text() == phrase))
        confirm.connect('clicked', lambda *_: self.run_nested_delete(dialog, nested, typed.get_text()))
        actions.append(confirm)
        body.append(actions)
        dialog.set_child(body)
        dialog.present()
        return dialog

    def run_nested_delete(self, dialog, nested, confirmation):
        from . import environments as survey
        try:
            survey.remove_nested_library(self.store, nested['name'], confirmation)
        except Exception as exc:
            self.message('Could not delete this library', str(exc))
            return
        dialog.close()
        self.last = None
        self.refresh()

    def record_licensing(self, record):
        """Say how licences work here — per plug-in, because they differ.

        A vendor environment is usually one answer for everything in it. A
        directly-imported one is a grab bag: a free plug-in, a serial-based
        one and something bound to a machine can share a prefix, and making
        the person pick one class for all three means picking a wrong one.
        The record has always been per product; only this form flattened it.
        """
        from . import environments as survey
        from . import licensing
        classes = [('unlicensed', 'Free, or otherwise needed no activation'),
                   ('reactivatable', 'Its serial can be entered again as often as needed'),
                   ('deactivate-first', 'Bound to this machine; deactivate before changing it'),
                   ('limited-activations', 'A fixed number of validations, ever'),
                   ('unknown', 'Not known — treated as strictly as limited activations')]
        names = [name for name, _ in classes]
        known = {item['name']: item for item in (record.get('recorded') or [])}
        # The union, not one or the other. A directly-imported environment
        # grows: answer for four plug-ins, drag in a fifth, and listing only
        # what was recorded would hide the one plug-in nobody has ruled on.
        listed = sorted(set(record['products']) | set(record['plugins']), key=str.casefold)

        dialog = Gtk.Window(title='Licence handling · ' + survey.summarize(record),
                            transient_for=self.window, modal=True)
        dialog.set_default_size(640, 520)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(outer, 'set_margin_' + side)(20)
        outer.append(label('How licences work in this environment', 'section-title'))
        outer.append(label('Not what is activated right now — nothing here asks the vendor, and '
                           'you may have deactivated everything this morning. This is how the '
                           'licences behave, which does not change. Never record serial numbers, '
                           'credentials or account details.', 'muted', True))
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        rows = []
        if listed:
            grid = Gtk.Grid(column_spacing=12, row_spacing=8)
            for index, name in enumerate(listed):
                title = label(name)
                title.set_ellipsize(Pango.EllipsizeMode.END)
                title.set_hexpand(True)
                title.set_tooltip_text(name)
                grid.attach(title, 0, index, 1, 1)
                chooser = Gtk.DropDown.new_from_strings([text for _, text in classes])
                current = (known.get(name) or {}).get('recovery', 'unknown')
                chooser.set_selected(names.index(current) if current in names else len(names) - 1)
                grid.attach(chooser, 1, index, 1, 1)
                rows.append((name, chooser))
            body.append(grid)
        else:
            body.append(label('Nothing is published from this environment yet. Name what it '
                              'holds, separated by commas.', 'status', True))
            entry = Gtk.Entry(placeholder_text='Products, separated by commas')
            body.append(entry)
            chooser = Gtk.DropDown.new_from_strings([text for _, text in classes])
            chooser.set_selected(len(names) - 1)
            body.append(chooser)
            rows.append((entry, chooser))
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(body)
        outer.append(scroll)
        where = Gtk.Entry(placeholder_text='Where deactivation happens, if it applies '
                                           '(the vendor’s website, iLok License Manager…)')
        where.set_text(', '.join(record.get('deactivate_at') or []))
        outer.append(where)
        remaining = Gtk.Entry(placeholder_text='Activations remaining, if a fixed number '
                                               '(optional, whole number)')
        outer.append(remaining)
        note = Gtk.Entry(placeholder_text='A short reminder for yourself (optional)')
        outer.append(note)
        actions = Gtk.Box(spacing=8)
        actions.set_halign(Gtk.Align.END)
        cancel = Gtk.Button(label='Cancel')
        cancel.connect('clicked', lambda *_: dialog.close())
        actions.append(cancel)
        save = Gtk.Button(label='Record')
        save.add_css_class('suggested-action')
        save.connect('clicked', lambda *_: self.save_licensing(
            dialog, record, rows, classes, where.get_text(), remaining.get_text(), note.get_text()))
        actions.append(save)
        outer.append(actions)
        dialog.set_child(outer)
        dialog.present()
        return dialog

    def save_licensing(self, dialog, record, rows, classes, where, remaining, note):
        from . import licensing
        items = []
        for name, chooser in rows:
            recovery = classes[chooser.get_selected()][0]
            found = ([name] if isinstance(name, str)
                     else [part.strip() for part in name.get_text().split(',') if part.strip()])
            for product in found:
                item = {'name': product, 'recovery': recovery}
                if where.strip() and recovery == 'deactivate-first':
                    item['deactivate_at'] = where.strip()
                if remaining.strip() and recovery == 'limited-activations':
                    if not remaining.strip().isdigit():
                        self.message('Activations remaining must be a whole number', remaining)
                        return
                    item['activations_remaining'] = int(remaining.strip())
                items.append(item)
        if not items:
            self.message('Name at least one product', 'Which products does this environment hold?')
            return
        try:
            licensing.protect(Path(record['path']), items, note=note.strip() or None)
        except Exception as exc:
            self.message('Could not record licence handling', str(exc))
            return
        dialog.close()
        self.last = None
        self.refresh()

    def troubleshoot_job(self, job):
        """Troubleshoot an installation that did not finish, searched for its installer's maker."""
        from . import known_fixes
        self.troubleshoot(vendor=known_fixes.vendor_of(job.get('installer')))

    def known_about(self, job, known):
        """What is already known about an installer, once per installer."""
        from . import known_fixes
        key = job.get('hash')
        if key not in self.known_cache:
            try:
                self.known_cache[key] = known_fixes.lookup(job.get('installer'), key, known_modules=known)
            except Exception:
                self.known_cache[key] = []
        return self.known_cache[key]

    def busy_row(self, title, detail, known=()):
        """One line of "this is happening", with a spinner that is actually spinning."""
        row = Gtk.Box(spacing=12)
        row.add_css_class('card')
        spinner = Gtk.Spinner(spinning=True)
        spinner.set_valign(Gtk.Align.CENTER)
        row.append(spinner)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        name = label(title)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(name)
        message = label(detail or 'Working…', 'status')
        message.set_ellipsize(Pango.EllipsizeMode.END)
        message.set_tooltip_text(detail or '')
        text.append(message)
        for line in known:
            # What is already known about this installer, while it installs.
            said = label(line, 'running-note', True)
            text.append(said)
        row.append(text)
        return row

    def button_grid(self, buttons, columns=2):
        """Lay a card's controls out on a grid rather than letting them flow.

        Buttons carry labels of different lengths, so a row of them is ragged
        and a wrapping box is worse — the break moves as the window resizes.
        Equal columns give every card the same shape, whether it has two
        controls or four.
        """
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        for index, button in enumerate(buttons):
            button.add_css_class('compact')
            button.set_hexpand(True)
            grid.attach(button, index % columns, index // columns, 1, 1)
        return grid

    def listing(self, summary, names):
        """A count that opens into the names, instead of a paragraph of them.

        One helper manages two dozen products. Spelling them out on the card
        set the height of every card in the row, so five managers filled a
        screen and the list itself was still unreadable.
        """
        button = Gtk.MenuButton(label=summary)
        button.add_css_class('count')
        button.set_halign(Gtk.Align.START)
        button.set_tooltip_text('\n'.join(names))
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(body, 'set_margin_' + side)(12)
        for name in names:
            body.append(label(name))
        scroll = Gtk.ScrolledWindow(propagate_natural_height=True, propagate_natural_width=True,
                                    max_content_height=360)
        scroll.set_child(body)
        popover = Gtk.Popover()
        popover.set_child(scroll)
        button.set_popover(popover)
        return button

    def refresh(self):
        try:
            standalone.reconcile_interrupted(self.store)
            from . import helper_recipes
            helper_recipes.reconcile_interrupted(self.store)
            try:
                # Unusable recipes are reported, not fatal: one bad shared file
                # must not stop the user from working with everything else.
                issues = []
                known = standalone.catalogue(issues)['modules']
                recipe_error = '\n'.join(
                    (item.get('reference') or item.get('source', '')) + ': ' + item['error']
                    for item in issues) or None
            except (OSError, ValueError, RuntimeError) as exc:
                known = {}
                recipe_error = str(exc)
            # A retired plug-in is gone from the DAW; it is history, not library.
            live = [p for p in self.store.plugins() if p['status'] != 'removed']
            data = (self.store.jobs(), live, vendors.cards(self.store), known, recipe_error,
                    tuple(sorted(self.pending.values())))
            if data == self.last:
                return True
            self.last = data
            jobs, plugins, setups, known, recipe_error, arriving = data
            self.recipe_problem = recipe_error
            self.recipe_notice_row.set_visible(bool(recipe_error))
            self.recipe_notice.set_visible(bool(recipe_error))
            self.recipe_notice.set_text("A setup recipe could not be used and was ignored. Everything else remains available." if recipe_error else "")
            self.recipe_notice.set_tooltip_text(recipe_error)
            job_by_id = {j['id']: j for j in jobs}
            from . import softube
            softube_setups = [(setup, self.store.root / 'environments' / job_by_id[setup['job']]['env_id'])
                              for setup in setups if setup['job'] in job_by_id]
            softube_setups = [(setup, directory) for setup, directory in softube_setups
                              if softube.configured(directory)]
            self.clear(self.activity)
            working = 0
            for name in arriving:
                if name.startswith('join:'):
                    self.activity.append(self.busy_row('Adding ' + name[5:], 'Joining the iLok environment. This takes a few minutes.'))
                else:
                    self.activity.append(self.busy_row('Adding ' + name, 'Copying the file into your library…'))
                working += 1
            for job in jobs:
                if job['status'] in TERMINAL or job['archived']:
                    continue
                from . import known_fixes
                stage = installation_progress(self.store.root, job)
                row = self.busy_row(job['name'], stage[0] if stage else job['message'],
                                    known_fixes.summary(self.known_about(job, known)))
                cancel = Gtk.Button(label='Cancel')
                cancel.add_css_class('compact')
                cancel.set_valign(Gtk.Align.CENTER)
                cancel.connect('clicked', lambda _, j=job['id']: self.cancel_job(j))
                row.append(cancel)
                self.activity.append(row)
                working += 1
            for job in jobs:
                if job['status'] not in ('failed', 'cancelled', 'needs_attention') or job['archived']:
                    continue
                # Everything that did not work, in the one place that is
                # always visible. There is no list of past attempts to visit
                # instead: an attempt is either something you are still
                # dealing with, which is here, or something you are not, which
                # is gone. What it left on disk is listed under cleanup.
                row = Gtk.Box(spacing=12)
                row.add_css_class('card')
                text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                text.set_hexpand(True)
                name = label(job['name'], 'error')
                name.set_ellipsize(Pango.EllipsizeMode.END)
                text.append(name)
                why = label(job['message'] or 'This installation did not finish.', 'status')
                why.set_ellipsize(Pango.EllipsizeMode.END)
                why.set_tooltip_text(job['message'] or '')
                text.append(why)
                from . import known_fixes
                for line in known_fixes.summary(self.known_about(job, known), limit=3):
                    text.append(label(line, 'status', True))
                row.append(text)
                controls = []
                if self.store.prefix(job['id']).is_dir():
                    controls.append(('Check again', 'Look at the environment again, in case the '
                                     'installation finished after all',
                                     lambda _, j=job['id']: self.rescan(j)))
                controls.append(('Details', 'What was recorded about this attempt',
                                 lambda _, j=job: self.job_details(j)))
                controls.append(('Troubleshoot…', 'Reusable fixes for installers and plug-ins that do not '
                                 'work at first', lambda *_, j=job: self.troubleshoot_job(j)))
                controls.append(('Dismiss', 'Forget this attempt and the installer copy it kept. '
                                 'Anything it left on disk is listed under cleanup.',
                                 lambda _, j=job['id']: self.discard_job(j)))
                for title, tip, handler in controls:
                    button = Gtk.Button(label=title)
                    button.add_css_class('compact')
                    button.set_valign(Gtk.Align.CENTER)
                    button.set_tooltip_text(tip)
                    button.connect('clicked', handler)
                    row.append(button)
                self.activity.append(row)
            self.drop_note.set_text('' if not working else
                                    ('%d installation in progress' % working if working == 1
                                     else '%d installations in progress' % working)
                                    + ' below. You can add another.')
            self.drop_note.set_visible(bool(working))
            from . import environments as survey
            settled = bool(jobs)
            self.hero.set_visible(not settled)
            self.subtitle.set_visible(not settled)
            self.drop_title.set_visible(not settled)
            self.drop_hint.set_visible(not settled)
            self.drop_line.set_text('Drop an installer or VST3 anywhere here to add it. Keep any .bin files beside the .exe.'
                                    if settled else 'Drop an installer or VST3 here, or choose a file to get started.')
            (self.drop_area.add_css_class if settled else self.drop_area.remove_css_class)('drop-compact')
            if self.tab == 'library':
                self.library_view.update(survey.survey(self.store), setups, jobs, self.sizes, self.breakdown,
                                         survey.unused_runtimes(self.store), survey.nested_libraries(self.store),
                                         plugins=plugins, softube={d.name for _, d in softube_setups},
                                         known_modules=[p.get('module') for p in self.store.plugins()],
                                         dead_bundles=survey.dead_bundles(self.store))
        except Exception as exc:
            self.last = None
            print('Refresh failed:', exc, file=sys.stderr)
        return True


def run(store):
    return Manager(store).run(["plugg"])
