"""The library as one list: what needs you, then each vendor, then the whole disk.

The window used to show the library through four tabs, one per kind of thing
the code keeps: plug-ins, helpers, recipes, environments. Nobody thinks in
those. They think "my Kilohearts things" or "my iLok things", and one vendor's
facts were spread over three tabs.

Here every environment is one row, named after the vendor it is for, with its
plug-ins, its helper and its cost on disk together. Anything that is taking
room without being used sits above the vendors, where it cannot be missed, and
the last line adds up the whole library folder so that space nothing accounts
for shows up as well. There is no third place for an environment to be.

SPDX-License-Identifier: GPL-3.0-or-later
"""
import json
import os
from pathlib import Path

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import environments as survey  # noqa: E402
from .vendors import vendor_name  # noqa: E402,F401

#: The library folder's own parts, by what they hold. Anything else there is
#: counted as unaccounted for and, past a threshold, shown as needing a look.
PARTS = {'environments': 'environments', 'runtimes': 'runtimes', 'downloads': 'downloads',
         'runtime-cache': 'runtimes', 'bridge-releases': 'bridge', 'bundles': 'bridge',
         'jobs': 'installers', 'managed-libraries': 'other libraries'}
UNACCOUNTED_THRESHOLD = 256 * 1024 ** 2

#: The helper's own name, where the recipe name is all a card carries.
HELPER_TITLES = {'klevgrand': 'Klevgrand Helper', 'native-instruments-experiment': 'Native Access',
                 'pace-service-experiment': 'UA Connect', 'plugin-alliance-experiment': 'PA Manager'}



def text(value, *classes, wrap=False, xalign=0.0, ellipsize=False, selectable=False):
    widget = Gtk.Label(label=value, xalign=xalign)
    widget.set_wrap(wrap)
    if wrap:
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if ellipsize:
        widget.set_ellipsize(Pango.EllipsizeMode.END)
    widget.set_selectable(selectable)
    for name in classes:
        widget.add_css_class(name)
    return widget


def speak(widget, label=None, description=None):
    """What a screen reader says for a widget whose look alone does not say it."""
    props, values = [], []
    if label:
        # A button is otherwise named by its own text, which wins over this.
        widget.reset_relation(Gtk.AccessibleRelation.LABELLED_BY)
        props.append(Gtk.AccessibleProperty.LABEL)
        values.append(label)
    if description:
        props.append(Gtk.AccessibleProperty.DESCRIPTION)
        values.append(description)
    if props:
        widget.update_property(props, values)
    return widget


def button(title, handler, *classes, tooltip=None, sensitive=True):
    widget = Gtk.Button(label=title)
    widget.set_valign(Gtk.Align.CENTER)
    for name in classes:
        widget.add_css_class(name)
    if tooltip:
        widget.set_tooltip_text(tooltip)
    widget.set_sensitive(sensitive)
    widget.connect('clicked', lambda *_: handler())
    return widget


def unlisted(breakdown):
    """Entries of the library folder that none of its parts explains, and that are big enough to matter."""
    return sorted(((name, size) for name, size in (breakdown or {}).items()
                   if name not in PARTS and size >= UNACCOUNTED_THRESHOLD), key=lambda item: -item[1])


def display_names(records):
    """What to call each row. Direct imports are named after what they hold,
    and two rows that would read the same get their first plug-in added."""
    names = {}
    for record in records:
        name = survey.summarize(record)
        if record.get('recipe') == 'standalone-vst3' and not record.get('name') and record.get('plugin_vendors'):
            name = ', '.join(record['plugin_vendors'][:2])
        names[record['id']] = name
    seen = {}
    for name in names.values():
        seen[name] = seen.get(name, 0) + 1
    for record in records:
        if seen[names[record['id']]] > 1 and record['plugins']:
            names[record['id']] += ' · ' + record['plugins'][0]
    return names


#: Vendor apps that live in a shared environment, and whose plug-ins they manage.
APP_VENDOR = {'UA Connect': 'universal audio', 'Softube Central': 'softube'}


def plugins_by_vendor(plugins, spelled=None):
    """{environment id: {vendor: [plug-in names]}}, from each plug-in's metadata.

    `spelled` maps a casefolded vendor to the spelling first seen, so that
    "SoundToys" and "Soundtoys" from two sources end up on one row.
    """
    import json
    found = {}
    spelled = {} if spelled is None else spelled
    for plugin in plugins:
        try:
            classes = json.loads(plugin.get('metadata') or '{}').get('classes') or []
        except ValueError:
            classes = []
        for info in classes or [{'name': plugin['name']}]:
            vendor = vendor_name(info.get('vendor'))
            vendor = spelled.setdefault(vendor.casefold(), vendor)
            names = found.setdefault(plugin['env_id'], {}).setdefault(vendor, [])
            name = info.get('name') or plugin['name']
            if name not in names:
                names.append(name)
    return found


def is_setup_program(record, setup):
    """Whether a vendor app is a setup program kept for reinstalling, not a manager.

    Some installers leave only a cached copy of themselves behind, and that
    copy gets adopted as the vendor's app. Its version resource says what it
    is: an InstallShield or InstallScript launcher, or a plain "Setup".
    """
    import json
    try:
        entry = json.loads((Path(record['path']) / 'helper-entry.json').read_text())['helper']['executable']
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if 'installshield installation information' in entry.casefold() or 'package cache' in entry.casefold():
        return True
    info = module_version(Path(record['path']) / 'prefix' / 'drive_c' / entry)
    described = (info.get('FileDescription') or '').casefold()
    return any(word in described for word in ('setup launcher', 'installscript', 'installshield')) \
        or described in ('setup', 'installer')


def app_title(name):
    """A helper adopted from its file name, without the version it happened to carry."""
    import re
    return re.sub(r'[\s._-]*v?\d+(?:\.\d+)+$', '', name).strip() or name


#: Where Windows VST3 plug-ins install, inside an environment.
VST3_FOLDER = ('prefix', 'drive_c', 'Program Files', 'Common Files', 'VST3')
UNIDENTIFIED = 'Not identified yet'
_versions = {}


def installed_modules(environment):
    """[(module path, bundle-or-file path)] for every VST3 installed in an environment.

    Walks only the standard VST3 folder, follows no symlink, and does not
    descend into bundles. Cheap enough to run whenever the library changes.
    """
    import os
    from . import pe_version
    root = Path(environment).joinpath(*VST3_FOLDER)
    found = []
    for parent, dirs, files in os.walk(root, followlinks=False):
        here = Path(parent)
        for name in list(dirs):
            if name.lower().endswith('.vst3'):
                dirs.remove(name)
                module = pe_version.module_of(here / name)
                if module is not None and not module.is_symlink():
                    found.append((module, here / name))
        for name in files:
            path = here / name
            if name.lower().endswith('.vst3') and not path.is_symlink():
                found.append((path, path))
    return found


def module_version(path):
    """Version info for a file, cached until the file changes."""
    from . import pe_version
    try:
        stat = Path(path).stat()
    except OSError:
        return {}
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key not in _versions:
        _versions[key] = pe_version.version_info(path)
    return _versions[key]


def unpublished(records, known_modules):
    """{environment id: {vendor: [names]}} for plug-ins installed but never published.

    The vendor comes from each file's version resource. A plug-in that was
    published once and then retired is not "not published yet", so every
    module the library has a record of is left out.
    """
    known = {str(Path(m)) for m in known_modules if m}
    found = {}
    for record in records:
        if record.get('dangling'):
            continue
        for module, shown in installed_modules(record['path']):
            if str(module) in known:
                continue
            info = module_version(module)
            vendor = vendor_name(info['CompanyName']) if info.get('CompanyName') else UNIDENTIFIED
            name = info.get('ProductName') or shown.stem
            names = found.setdefault(record['id'], {}).setdefault(vendor, [])
            if name not in names:
                names.append(name)
    return found


def plural(count, word):
    return '%d %s%s' % (count, word, '' if count == 1 else 's')


def size_text(size):
    return survey.readable(size) if size is not None else '…'


def short_runtime(record):
    runtime = record.get('runtime') or ''
    return runtime.replace('UMU-Proton-', 'proton ') or 'runtime not recorded'


class Section(Gtk.Box):
    """A quiet rule with a name in it: ── needs attention ─────────── 3.1 GB"""

    def __init__(self, title, trailing=''):
        super().__init__(spacing=10)
        self.add_css_class('lib-section')
        heading = Gtk.Label(label=title, xalign=0.0, accessible_role=Gtk.AccessibleRole.HEADING)
        heading.add_css_class('lib-section-title')
        heading.update_property([Gtk.AccessibleProperty.LEVEL, Gtk.AccessibleProperty.LABEL],
                                [2, title + (', ' + trailing if trailing else '')])
        self.append(heading)
        rule = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        rule.set_hexpand(True)
        rule.set_valign(Gtk.Align.CENTER)
        self.append(rule)
        self.trailing = text(trailing, 'lib-figure', 'lib-dim')
        self.append(self.trailing)


def group():
    """One panel per section, rows divided by hairlines: a list, not a pile of cards.

    A ListBox, so the keyboard works the way it does in any list: Up and Down
    move between rows, Enter or Space activates one, Tab goes into its buttons.
    """
    box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    box.add_css_class('lib-list')
    box.set_overflow(Gtk.Overflow.HIDDEN)
    return box


def bar(fraction, *classes):
    """ncdu's bar: how much of the largest this one is, and nothing else."""
    # Decoration: the size is said in words on the same row, and a screen
    # reader announcing "22 percent" would only add noise.
    widget = Gtk.ProgressBar(accessible_role=Gtk.AccessibleRole.PRESENTATION)
    widget.set_fraction(max(0.0, min(1.0, fraction)))
    widget.add_css_class('lib-bar')
    for name in classes:
        widget.add_css_class(name)
    widget.set_valign(Gtk.Align.CENTER)
    return widget


class LibraryView:
    """Builds the library page and redraws it from what the manager knows.

    `host` is the application. The view calls its existing actions, so every
    guard, confirmation and background job stays where it already is: nothing
    here deletes, stops or opens anything by itself.
    """

    def __init__(self, host):
        self.host = host
        self.query = ''
        self.vendor_plugins = {}
        self.plugin_index = {}
        self.dead_bundles = []
        self.waiting = {}
        self.softube = set()
        self.expanded = set()
        self.menus = {}
        self.row_actions = {}
        self.chip_fillers = {}
        self.vendor_list = None
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.widget.add_css_class('library')
        pointer = Gtk.EventControllerMotion()
        pointer.connect('motion', self.pointer_moved)
        self.widget.add_controller(pointer)
        top = Gtk.Box(spacing=12)
        self.search = Gtk.SearchEntry(placeholder_text='Find a plug-in or vendor')
        speak(self.search, 'Find a plug-in or vendor',
              'Type anywhere to search. Down goes to the results, Escape clears the search.')
        self.search.set_hexpand(True)
        self.search.connect('search-changed', self.search_changed)
        self.search.connect('stop-search', self.search_stopped)
        down = Gtk.EventControllerKey()
        down.connect('key-pressed', self.search_key)
        self.search.add_controller(down)
        top.append(self.search)
        top.append(button('Recipes & fixes', lambda: self.host.open_recipes(), 'compact', 'lib-quiet',
                          tooltip='Setups for vendors, and reusable fixes for plug-ins that do not work at first'))
        self.widget.append(top)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.widget.append(self.body)
        self.last = None

    def search_changed(self, entry):
        self.query = entry.get_text().strip().casefold()
        if self.last:
            self.render(*self.last)
            # After layout, so the position is the new one.
            GLib.idle_add(self.scroll_to_results, priority=GLib.PRIORITY_LOW)

    def scroll_to_results(self):
        """Put the search box at the top after a search changes the list.

        Searching shortens the list, and a scrolled window keeps its position by
        clamping it to what is left, which lands at the end of the results or
        past them. Showing the box you typed into, with the results under it,
        answers that and the question behind it: whether anything happened.
        """
        scrolled = self.widget.get_ancestor(Gtk.ScrolledWindow)
        if scrolled is None or scrolled.get_child() is None:
            return False
        point = self.search.translate_coordinates(scrolled.get_child(), 0, 0)
        adjustment = scrolled.get_vadjustment()
        if point is not None and adjustment is not None:
            top = max(0.0, point[1] - 8)
            reachable = max(0.0, adjustment.get_upper() - adjustment.get_page_size())
            adjustment.set_value(min(top, reachable))
        return False

    # ------------------------------------------------------------ keyboard

    def attach(self, window):
        """Keys that work anywhere in the window: typing searches, Ctrl+F goes to search."""
        self.search.set_key_capture_widget(window)
        shortcuts = Gtk.ShortcutController(scope=Gtk.ShortcutScope.GLOBAL)
        shortcuts.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string('<Control>f'),
                                            action=Gtk.CallbackAction.new(lambda *_: self.search.grab_focus() or True)))
        window.add_controller(shortcuts)

    def search_stopped(self, entry):
        """Escape clears the search and goes back to the list."""
        entry.set_text('')
        self.focus_first_row()

    def search_key(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Down:
            return self.focus_first_row()
        return False

    def focus_first_row(self):
        row = self.vendor_list.get_row_at_index(0) if self.vendor_list is not None else None
        if row is not None:
            row.grab_focus()
            self.show_focus(row)
            return True
        return False

    def show_focus(self, widget=None):
        """Mark the list as keyboard-driven, so the focused row gets its ring.

        GTK's own focus-visible state is not reliably set when focus moves
        between list rows, so the view keeps track itself: keys turn the ring
        on, moving the pointer turns it off again.
        """
        self.widget.add_css_class('keyboard')

    def pointer_moved(self, *_):
        if self.widget.has_css_class('keyboard'):
            self.widget.remove_css_class('keyboard')

    def add_row(self, listing, widget, activate=None, menu=None, classes=(), label=None, expanded=None):
        """Put a row in a list. Enter on it runs `activate`; the Menu key opens `menu`.

        `label` is what a screen reader says for the row. When `expanded` is
        given the row can open, and says whether it is open; `activate` then
        returns the new state.
        """
        row = Gtk.ListBoxRow()
        row.set_child(widget)
        if label:
            speak(row, label, 'Enter shows its plug-ins. The Menu key opens its settings.'
                  if expanded is not None and menu is not None else
                  'Enter shows its plug-ins.' if expanded is not None else None)
        if expanded is not None:
            # GTK keeps this state as an int (true, false or undefined), not a bool.
            row.update_state([Gtk.AccessibleState.EXPANDED], [int(bool(expanded))])
            flip = activate

            def activate():
                row.update_state([Gtk.AccessibleState.EXPANDED], [int(bool(flip()))])
        row.add_css_class('lib-item')
        for name in classes:
            row.add_css_class(name)
        row.set_activatable(activate is not None)
        self.row_actions[row] = (activate, menu)
        listing.append(row)
        return row

    def listing(self):
        box = group()
        box.connect('row-activated', lambda _, row: (self.row_actions.get(row, (None, None))[0] or (lambda: None))())
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self.list_key, box)
        box.add_controller(keys)
        return box

    def list_key(self, controller, keyval, keycode, state, box):
        """The Menu key, or Shift+F10, opens the focused row's settings."""
        if keyval in (Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_Home, Gdk.KEY_End, Gdk.KEY_Page_Up, Gdk.KEY_Page_Down):
            self.show_focus(box)
            return False
        wants_menu = keyval == Gdk.KEY_Menu or (keyval == Gdk.KEY_F10 and state & Gdk.ModifierType.SHIFT_MASK)
        if not wants_menu:
            return False
        row = box.get_focus_child()
        menu = self.row_actions.get(row, (None, None))[1] if row is not None else None
        if menu is None:
            return False
        menu.popup()
        return True

    # ------------------------------------------------------------ the model

    def update(self, records, setups, jobs, sizes, breakdown, spare_runtimes, nested, plugins=(), softube=(),
               known_modules=None, dead_bundles=()):
        self.dead_bundles = list(dead_bundles)
        spelled = {}
        self.vendor_plugins = plugins_by_vendor(plugins, spelled)
        # Each published plug-in's record, by the names rows show it under, so a
        # chip can say what the DAW sees and where the plug-in came from.
        self.plugin_index = {}
        for plugin in plugins:
            keys = [plugin['name']]
            try:
                keys += [c.get('name') for c in json.loads(plugin.get('metadata') or '{}').get('classes') or []]
            except ValueError:
                pass
            for key in keys:
                if key:
                    self.plugin_index.setdefault((plugin['env_id'], key), plugin)
        known = known_modules if known_modules is not None else [p.get('module') for p in plugins]
        self.waiting = {}
        for env_id, groups in unpublished(records, known).items():
            for vendor, names in groups.items():
                vendor = spelled.setdefault(vendor.casefold(), vendor)
                self.waiting.setdefault(env_id, {}).setdefault(vendor, []).extend(names)
        self.softube = set(softube)
        self.last = (records, setups, jobs, sizes, breakdown, spare_runtimes, nested)
        self.render(*self.last)

    @staticmethod
    def helpers_by_environment(setups, jobs):
        env_of = {job['id']: job['env_id'] for job in jobs}
        found = {}
        for setup in setups:
            env_id = env_of.get(setup['job'])
            if env_id:
                found.setdefault(env_id, []).append(setup)
        return found

    @staticmethod
    def leftover(record, helpers):
        """Taking room without anything to show for it, as far as this library knows.

        An environment with a helper and no plug-ins yet is a vendor you are
        still setting up, so it stays a vendor. Protected ones are never
        called leftovers, whatever else is true of them, and neither is one
        whose licensing note cannot be read: that is treated as holding
        activations everywhere else, so it is here too.
        """
        if record.get('dangling'):
            return 'The environment this link pointed to is gone.'
        if record.get('protected') or record.get('protected') is None:
            return None
        if record.get('orphaned'):
            return 'No installation refers to this environment.'
        if not record.get('in_use'):
            return 'Every installation here is archived. It is still on disk.'
        if not record['plugins'] and not helpers:
            return 'Nothing in your DAW comes from this environment.'
        return None

    @staticmethod
    def urgent(record, helpers):
        """What blocks you or puts an activation at risk now, and so goes above everything.

        Leftovers are not in this list. Cleaning up is housekeeping, and
        opening a vendor's installer is what the window is for.
        """
        if record.get('protected') and record.get('matches_recorded_identity') is False:
            return ('This environment no longer matches the machine identity recorded for it. '
                    'Look before installing or activating anything here.')
        return None

    # ------------------------------------------------------------ drawing

    def render(self, records, setups, jobs, sizes, breakdown, spare_runtimes, nested):
        clear(self.body)
        helpers = self.helpers_by_environment(setups, jobs)
        self.names = display_names(records)
        leftovers, vendors, urgent = [], [], []
        for record in records:
            mine = helpers.get(record['id'])
            reason = self.leftover(record, mine)
            (leftovers if reason else vendors).append((record, reason))
            problem = self.urgent(record, mine)
            if problem:
                urgent.append((record, problem))
        unaccounted = unlisted(breakdown)
        measured = [sizes.get(r['id']) for r, _ in leftovers + vendors]
        largest = max([s for s in measured if s] or [1])

        self.row_actions = {}
        if urgent:
            self.body.append(Section('needs you'))
            listing = self.listing()
            self.body.append(listing)
            for record, problem in urgent:
                self.add_row(listing, self.urgent_row(record, problem, helpers.get(record['id'], [])),
                             classes=('lib-urgent',))

        rows = []
        for record, _ in vendors:
            rows.extend(self.vendor_entries(record, helpers.get(record['id'], []), sizes.get(record['id'])))
        shown = [(row, self.row_matches(row)) for row in rows]
        shown = [(row, hits) for row, hits in shown if hits is not None]
        count = sum(len(r['plugins']) for r, _ in vendors)
        self.body.append(Section('vendors', '%d in your DAW' % count))
        if not rows:
            self.body.append(text('Nothing installed yet. Drop an installer or a VST3 above.', 'lib-dim'))
        elif not shown:
            self.body.append(text('Nothing matches “%s”.' % self.query, 'lib-dim'))
        listing = self.listing()
        self.vendor_list = listing
        if shown:
            self.body.append(listing)
        # By name, with what could not be identified at the end.
        for row, hits in sorted(shown, key=lambda item: (item[0]['title'] == UNIDENTIFIED,
                                                         item[0]['title'].casefold())):
            widget, flip, menu, opened, spoken = self.vendor_row(row, hits, largest)
            self.add_row(listing, widget, activate=flip, menu=menu, label=spoken,
                         expanded=opened if flip else None)

        items = len(leftovers) + len(spare_runtimes) + len(nested) + len(unaccounted) + len(self.dead_bundles)
        if items:
            freeable = sum(sizes.get(r['id']) or 0 for r, _ in leftovers) + sum(s for _, s in unaccounted)
            self.body.append(self.cleanup(leftovers, spare_runtimes, nested, unaccounted, sizes, largest,
                                          items, freeable))

        self.body.append(self.footer(breakdown, sizes, records))

    def cleanup(self, leftovers, spare_runtimes, nested, unaccounted, sizes, largest, items, freeable):
        """Housekeeping, folded away below the vendors, with what it would give back."""
        expander = Gtk.Expander()
        expander.add_css_class('lib-cleanup')
        expander.set_expanded('cleanup' in self.expanded)
        expander.connect('notify::expanded', lambda e, _: (self.expanded.add if e.get_expanded()
                                                            else self.expanded.discard)('cleanup'))
        title = Gtk.Box(spacing=10)
        title.append(text('cleanup', 'lib-section-title'))
        title.append(text(plural(items, 'item') + (' · ' + size_text(freeable) + ' reclaimable' if freeable else ''),
                          'lib-figure', 'lib-dim'))
        expander.set_label_widget(title)
        speak(expander, 'Cleanup, ' + plural(items, 'item') + (', ' + size_text(freeable) + ' reclaimable'
                                                               if freeable else ''))
        listing = self.listing()
        listing.set_margin_top(8)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        if leftovers:
            # Not the same as knowing they are inactive. This library knows what
            # it published and what it was told to protect; a vendor may count a
            # machine it was never told about.
            box.append(text('Nothing in your DAW comes from these environments. That is not proof they hold '
                            'nothing: a vendor may still count one as a machine if its licensing was never '
                            'recorded here.', 'lib-note', wrap=True))
        box.append(listing)
        for record, reason in leftovers:
            self.add_row(listing, self.leftover_row(record, reason, sizes.get(record['id']), largest))
        for name in spare_runtimes:
            self.add_row(listing, self.simple_row(
                'Unused runtime ' + name, 'No environment uses it. It is downloaded again if one ever does.',
                None, button('Reclaim', lambda n=name: self.host.reclaim_runtime(n), 'compact', 'lib-quiet')))
        for library in nested:
            action = button('Delete…', lambda n=library: self.host.delete_nested(n), 'compact', 'lib-quiet',
                            sensitive=not library.get('required_by'),
                            tooltip=('Needed by ' + ', '.join(library['required_by']))
                            if library.get('required_by') else None)
            self.add_row(listing, self.simple_row(
                'Separate library ' + library['name'],
                plural(library['environments'], 'environment') + ' with its own downloads and runtimes',
                None, action))
        for name, size in unaccounted:
            self.add_row(listing, self.simple_row(
                name, 'In the library folder, and nothing here lists it.', size,
                button('Show folder', lambda n=name: self.host.show_folder(n), 'compact', 'lib-quiet')))
        for bundle in self.dead_bundles:
            self.add_row(listing, self.simple_row(
                'Leftover adapter ' + bundle['name'],
                'The Windows plug-in it loaded is gone, and your DAW does not see it.', None,
                button('Remove', lambda n=bundle['name']: self.host.remove_dead_bundle(n), 'compact', 'lib-quiet')))
        expander.set_child(box)
        return expander

    def vendor_entries(self, record, helpers, size):
        """The rows one environment contributes: usually one, several when it is shared.

        A shared environment (iLok) holds several vendors. Each gets its own
        row with its own app and plug-ins, because that is how people look for
        them. The environment itself is the iLok row, and only that row
        carries the size and the settings, since deleting or measuring
        happens to the environment, not to one vendor in it.
        """
        apps = self.helper_apps(record, helpers)
        note = next((s.get('message') for s in helpers if s.get('needs_attention') and s.get('message')), None)
        by_vendor = self.vendor_plugins.get(record['id'], {})
        waiting = self.waiting.get(record['id'], {})
        if record.get('licensing_group') != 'ilok':
            name = self.names.get(record['id'], survey.summarize(record))
            return [{'key': record['id'], 'title': name, 'record': record, 'owner': True, 'size': size,
                     'plugins': record['plugins'], 'waiting': [n for names in waiting.values() for n in names],
                     'recheck': next((j['id'] for j in record['jobs'] if not j.get('archived')), None),
                     'apps': [widget for _, widget in apps], 'helpers': helpers,
                     'extra': ['Last check: ' + note] if note else []}]
        # What activating needs: the iLok helper's job, and whether it can
        # open the License Manager directly.
        ilok = next(({'job': s['job'], 'direct': 'iLok License Manager' in (s.get('managers') or [])}
                     for s in helpers if s.get('has_ilok')), None)
        members = {}
        for vendor in list(by_vendor) + [v for v in waiting if v not in by_vendor]:
            members[vendor] = {'key': record['id'] + ':' + vendor, 'title': vendor, 'record': record,
                               'owner': False, 'size': None, 'plugins': by_vendor.get(vendor, []),
                               'waiting': waiting.get(vendor, []), 'apps': [], 'ilok': ilok}
        own = []
        for app, widget in apps:
            wanted = APP_VENDOR.get(app)
            member = next((m for v, m in members.items() if wanted and v.casefold().startswith(wanted)), None)
            if wanted and member is None:
                # The app is installed, but none of its plug-ins are yet.
                title = app.replace(' Connect', '').replace(' Central', '')
                title = {'UA': 'Universal Audio'}.get(title, title)
                member = members.setdefault(title, {'key': record['id'] + ':' + title, 'title': title,
                                                    'record': record, 'owner': False, 'size': None,
                                                    'plugins': [], 'waiting': [], 'apps': []})
            (member['apps'] if member else own).append(widget)
        vendors = sorted((v for v in members if v != UNIDENTIFIED), key=str.casefold)
        waiting_total = sum(len(m['waiting']) for m in members.values())
        meta = 'licences for ' + plural(len(vendors), 'vendor')
        if waiting_total:
            meta += '  ·  %d waiting for activation' % waiting_total
        extra = ['Shared by ' + (', '.join(vendors) if vendors else 'no vendor yet') + '.']
        if note:
            extra.append('Last check: ' + note)
        head = {'key': record['id'], 'title': record.get('name') or 'iLok', 'record': record, 'owner': True,
                'size': size, 'plugins': [], 'waiting': [], 'apps': own, 'meta': meta, 'extra': extra,
                'waiting_total': waiting_total, 'helpers': helpers}
        return [head] + list(members.values())

    def row_matches(self, row):
        """None when the search excludes this row, else the plug-ins it matched."""
        if not self.query:
            return []
        if self.query in row['title'].casefold():
            return []
        env = row['record']['id']

        def found(name):
            # A DAW that refuses a plug-in names only its file, so the search
            # finds a plug-in by that file name too.
            plugin = self.plugin_index.get((env, name))
            shown = Path(plugin['publication']).stem if plugin and plugin.get('publication') else ''
            return self.query in name.casefold() or self.query in shown.casefold()
        hits = [name for name in row['plugins'] + row.get('waiting', []) if found(name)]
        return hits or None

    def vendor_row(self, row, hits, largest):
        record = row['record']
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        head = Gtk.Box(spacing=12)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        titles.set_hexpand(True)
        name = text(row['title'], 'lib-name', ellipsize=True)
        # The status dot: all in the DAW (green), something waiting for you
        # (amber), or its app running (blue). The words on the row say the same.
        running = any(c.has_css_class('running') for c in row['apps'])
        state = ('running' if running else 'waiting' if row.get('waiting')
                 else 'ok' if row['plugins'] else 'idle')
        if row.get('meta'):
            # The licence manager has no state of its own; it sums up the
            # vendors that share it.
            state = 'waiting' if row.get('waiting_total') else None
        line = Gtk.Box(spacing=8)
        dot = Gtk.Box(accessible_role=Gtk.AccessibleRole.PRESENTATION)
        dot.add_css_class('lib-dot')
        dot.add_css_class('lib-dot-' + (state or 'none'))
        dot.set_tooltip_text({'running': 'Its app is running', 'ok': 'Its plug-ins are in your DAW',
                              'waiting': 'Something is waiting for you: see the button on this row',
                              'idle': 'Nothing in your DAW yet'}.get(state))
        dot.set_valign(Gtk.Align.CENTER)
        line.append(dot)
        line.append(name)
        titles.append(line)
        waiting = row.get('waiting') or []
        activation = row.get('ilok') is not None
        if row.get('meta'):
            meta = row['meta']
        else:
            parts = [plural(len(row['plugins']), 'plug-in')] if row['plugins'] else []
            if waiting:
                parts.append(('%d waiting for iLok activation' if activation else '%d not in your DAW yet')
                             % len(waiting))
            meta = '  ·  '.join(parts) or 'nothing in your DAW yet'
        if row['owner'] and record.get('retired') and not row.get('meta'):
            meta += '  ·  %d retired' % len(record['retired'])
        if not row['owner']:
            meta += '  ·  in the shared iLok environment'
        titles.append(text(meta, 'lib-meta', ellipsize=True))
        head.append(titles)
        todo = None
        offers = [] if row['apps'] or not row['owner'] else (self.host.helper_offers(record) or [])
        if len(offers) == 1:
            program = offers[0]
            todo = button('Use ' + Path(program).stem, lambda: self.host.use_helper(record['id'], program), 'compact',
                          tooltip='The installer left this app here. Use it to add or update products; '
                                  'closing it checks for new plug-ins.')
        elif offers:
            todo = button('Choose app…', lambda: self.host.adopt_helper(record), 'compact',
                          tooltip='The installer left apps here. Choose the one that adds or updates products.')
        if waiting and activation:
            job, direct = row['ilok']['job'], row['ilok']['direct']
            todo = button('Activate in iLok', (lambda: self.host.manager_action(job, 'iLok License Manager'))
                          if direct else (lambda: self.host.open_ilok(job)), 'compact',
                          tooltip='Opens iLok License Manager. Activate your licences there and close it: '
                                  'Plugg then checks these plug-ins again and adds the ones that load.')
            hint = text('Activate in iLok License Manager, then close it. Plugg checks again and adds '
                        'what loads to your DAW.', 'lib-note', wrap=True)
            titles.append(hint)
        elif waiting and row.get('recheck'):
            todo = button('Check again', lambda j=row['recheck']: self.host.rescan(j), 'compact',
                          tooltip='Look for plug-ins in this environment again, for example after '
                                  'authorising them in the vendor\'s app.')
        if todo is not None:
            speak(todo, '%s for %s' % (todo.get_label(), row['title']), todo.get_tooltip_text())
            head.append(todo)
        for control in row['apps']:
            # "Open manager" five times over says nothing to someone who hears it.
            speak(control, '%s for %s' % (control.get_label(), row['title']), control.get_tooltip_text())
            head.append(control)
        # Every row keeps the size and settings columns, so the app buttons line
        # up down the list; a vendor sharing an environment leaves them empty.
        figure = text(size_text(row['size']) if row['owner'] else '', 'lib-figure')
        figure.set_width_chars(9)
        figure.set_xalign(1.0)
        figure.set_valign(Gtk.Align.CENTER)
        head.append(figure)
        menu = None
        if row['owner']:
            menu = self.settings(record, row.get('helpers') or [])
            speak(menu, 'Settings for ' + row['title'],
                  'Show folder, rename, troubleshoot, licence handling and delete')
            head.append(menu)
        else:
            slot = Gtk.Box()
            slot.set_size_request(26, -1)
            head.append(slot)
        opened = row['key'] in self.expanded or bool(hits)
        toggle = Gtk.Button(icon_name='pan-down-symbolic' if opened else 'pan-end-symbolic')
        toggle.add_css_class('lib-toggle')
        toggle.set_valign(Gtk.Align.CENTER)
        toggle.set_tooltip_text('Show its plug-ins')
        speak(toggle, 'Show the plug-ins of ' + row['title'])
        listed = row['plugins'] + row.get('waiting', []) + row.get('extra', [])
        if row.get('extra') and not row['plugins'] + row.get('waiting', []):
            toggle.set_tooltip_text('Show details')
            speak(toggle, 'Show details of ' + row['title'])
        toggle.set_sensitive(bool(listed))
        toggle.set_opacity(1.0 if listed else 0.0)
        head.append(toggle)
        box.append(head)
        if row['owner']:
            box.append(bar((row['size'] or 0) / largest))
        revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=140)
        revealer.set_reveal_child(opened and bool(listed))
        revealer.set_child(self.details(row['plugins'], hits, waiting, activation, row.get('extra', []),
                                        env=record['id']))
        box.append(revealer)

        def flip(*_):
            if not listed:
                return
            now = not revealer.get_reveal_child()
            revealer.set_reveal_child(now)
            toggle.set_icon_name('pan-down-symbolic' if now else 'pan-end-symbolic')
            (self.expanded.add if now else self.expanded.discard)(row['key'])
            return now
        toggle.connect('clicked', lambda *_: flip())
        toggle.set_focusable(False)
        spoken = ', '.join(x for x in (row['title'], meta.replace('  ·  ', ', '),
                                        size_text(row['size']) if row['owner'] else None) if x)
        return box, (flip if listed else None), menu, opened and bool(listed), spoken

    def details(self, plugins, hits, waiting=(), activation=False, extra=(), env=None):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.add_css_class('lib-details')
        for line in extra:
            box.append(text(line, 'lib-note', wrap=True, selectable=True))

        def chips(names, *classes, tooltip=None):
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=6, row_spacing=6,
                               max_children_per_line=30, homogeneous=False)
            for name in names:
                chip = text(name, 'lib-plugin', *classes, *(('lib-plugin-hit',) if name in hits else ()))
                chip.set_halign(Gtk.Align.START)
                plugin = self.plugin_index.get((env, name)) if not classes else None
                if plugin is not None:
                    flow.append(self.plugin_chip(chip, name, plugin))
                    continue
                if tooltip:
                    chip.set_tooltip_text(tooltip)
                flow.append(chip)
            return flow
        if plugins:
            box.append(chips(plugins))
        if waiting:
            box.append(text('Waiting for iLok activation' if activation else 'Installed, not in your DAW yet',
                            'lib-meta'))
            box.append(chips(waiting, 'lib-plugin-waiting',
                             tooltip='Installed but not in your DAW yet. iLok and other copy-protected plug-ins '
                                     'are added once they are activated.'))
        if not plugins and not waiting and not extra:
            box.append(text('Nothing from here is in your DAW yet.', 'lib-dim'))
        return box

    def plugin_chip(self, chip, name, plugin):
        """A plug-in you can ask about: what the DAW sees, where it came from, its version."""
        menu = Gtk.MenuButton()
        menu.add_css_class('lib-chip-button')
        menu.set_child(chip)
        menu.set_halign(Gtk.Align.START)
        problem = plugin.get('status') not in (None, 'ready')
        if problem:
            chip.add_css_class('lib-plugin-problem')
        speak(menu, name + (', needs attention' if problem else ''), 'Details about this plug-in')
        popover = Gtk.Popover()
        popover.add_css_class('lib-menu')
        menu.set_popover(popover)

        def fill(*_):
            facts = self.host.plugin_facts(plugin) or {}
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            for side in ('top', 'bottom', 'start', 'end'):
                getattr(box, 'set_margin_' + side)(8)
            box.append(text(name, 'lib-name', wrap=True))
            for line in facts.get('lines', []):
                shown = text(line, 'lib-meta', wrap=True, selectable=True)
                shown.set_max_width_chars(52)
                box.append(shown)
            if facts.get('problem'):
                box.append(text(facts['problem'], 'lib-note', wrap=True))
            for title, handler in facts.get('actions', []):
                box.append(button(title, lambda h=handler: (popover.popdown(), h()), 'lib-menu-item'))
            popover.set_child(box)
        popover.connect('show', fill)
        # Built when it opens, since it reads the library; kept so a test can
        # build it without opening a popup.
        self.chip_fillers[menu] = fill
        return menu

    def settings(self, record, helpers=()):
        """Everything done to an environment rather than with it, behind one cogwheel.

        Deleting is the rarest of these and comes last. What deleting would
        cost in licences is said right above it, which is the only place that
        is a warning rather than a call to action.
        """
        menu = Gtk.MenuButton(icon_name='emblem-system-symbolic', tooltip_text='Settings for this environment')
        menu.add_css_class('lib-toggle')
        menu.set_valign(Gtk.Align.CENTER)
        popover = Gtk.Popover()
        popover.add_css_class('lib-menu')
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(box, 'set_margin_' + side)(6)
        about = '  ·  '.join([short_runtime(record), record['id'][:12]])
        box.append(text(about, 'lib-meta'))
        where = text(record['path'], 'lib-meta', 'lib-dim', ellipsize=True)
        where.set_tooltip_text(record['path'])
        box.append(where)
        box.append(Gtk.Separator())

        def item(title, handler, *classes, tooltip=None):
            entry = button(title, lambda: (popover.popdown(), handler()), 'lib-menu-item', *classes, tooltip=tooltip)
            entry.get_child().set_xalign(0.0)
            box.append(entry)
        item('Show folder', lambda: self.host.show_path(record['path']))
        item('Rename…', lambda: self.host.rename_environment(record))
        item('Troubleshoot…', lambda: self.host.troubleshoot(record),
             tooltip='Reusable fixes for plug-ins that load badly, draw wrongly or crash')
        item('Report a bug or finding…', lambda: self.host.report('compatibility', record),
             tooltip='Plugg has no helpdesk, but good reports and findings get read')
        # Recorded or not, it can be looked at and changed again: a wrong
        # answer, once given, must not become permanent.
        item('Licence handling ✓' if record.get('protected') else 'Licence handling…',
             lambda: self.host.record_licensing(record),
             tooltip=survey.recorded_detail(record) or 'How licences work for what is installed here')
        for setup in helpers:
            if setup.get('can_refresh'):
                item('Refresh library', lambda j=setup['job']: self.host.vendor_action(j, True),
                     tooltip='Check again for plug-ins, after installing them some other way')
            if setup.get('helper_profile') == 'native-access':
                item('Complete sign-in…', lambda j=setup['job']: self.host.native_access_sign_in(j),
                     tooltip='Finish a Native Access sign-in that opened in your browser')
            if setup.get('installer'):
                item('Installer files', lambda i=setup['installer']: self.host.show_path(str(Path(i).parent)),
                     tooltip='The installer Plugg kept for this vendor')
        if not helpers and record.get('recipe') in ('installer', 'standalone-vst3') \
                and (Path(record['path']) / 'launch-full-proton').is_file():
            item('Use as helper…', lambda: self.host.adopt_helper(record),
                 tooltip='Choose the vendor app the installer left here, so it gets a button like other vendors')
        live = [s for s in helpers if s.get('running') or s.get('busy') or s.get('needs_attention')]
        if live:
            item('Force close its apps', lambda j=live[0]['job']: self.host.stop_helper(j, 'this environment'),
                 tooltip='End the Windows programs still running in this environment')
        box.append(Gtk.Separator())
        note = survey.licensing_line(record)
        if note:
            warning = text(note, 'lib-note', wrap=True)
            warning.set_max_width_chars(44)
            box.append(warning)
        item('Delete…', lambda: self.host.delete_environment(record), 'lib-menu-danger')
        arrows = Gtk.EventControllerKey()
        arrows.connect('key-pressed', lambda c, key, code, state: popover.child_focus(
            Gtk.DirectionType.TAB_FORWARD if key == Gdk.KEY_Down else Gtk.DirectionType.TAB_BACKWARD)
            if key in (Gdk.KEY_Down, Gdk.KEY_Up) else False)
        box.add_controller(arrows)
        popover.set_child(box)
        menu.set_popover(popover)
        self.menus[record['id']] = menu
        return menu

    def helper_apps(self, record, helpers):
        """[(app name, button)]: the vendor apps an environment holds, ready to open.

        A running app gets an outlined button that brings its window back.
        Force close is not offered for a running app, only for a stuck one;
        otherwise it sits in the settings menu.
        """
        apps = []

        def add(app, title, opener, running, busy, job, tooltip=None):
            if running:
                apps.append((app, button(title, lambda: self.host.show_helper(job), 'compact', 'running',
                                         tooltip=(tooltip or app) + '. Running: bring its window back.')))
            else:
                apps.append((app, button(title, opener, 'compact', sensitive=not busy, tooltip=tooltip)))
        for setup in helpers:
            job, running, busy = setup['job'], setup.get('running') or [], setup.get('busy')
            managers = setup.get('managers') or []
            if setup.get('has_ilok'):
                live = any('ilok' in n.casefold() for n in running)
                if 'iLok License Manager' in managers:
                    add('iLok License Manager', 'Open iLok',
                        lambda j=job: self.host.manager_action(j, 'iLok License Manager'), live, busy, job)
                else:
                    add('iLok License Manager', 'Open iLok', lambda j=job: self.host.open_ilok(j), live, busy, job)
                for manager in managers:
                    if manager == 'iLok License Manager':
                        continue
                    live = any(manager.split()[0].casefold() in n.casefold() for n in running)
                    add(manager, 'Open manager', lambda j=job, m=manager: self.host.manager_action(j, m),
                        live, busy, job, tooltip='Opens ' + manager)
            else:
                title = HELPER_TITLES.get(setup['recipe']) or app_title(setup.get('name') or 'helper')
                label = 'Run installer' if is_setup_program(record, setup) else 'Open manager'
                add(title, label, lambda j=job: self.host.vendor_action(j, False), bool(running), busy, job,
                    tooltip='Opens ' + title)
        if record['id'] in self.softube and not any(app == 'Softube Central' for app, _ in apps):
            directory = Path(record['path'])
            apps.append(('Softube Central', button('Open manager', lambda d=directory: self.host.softube_action(d),
                                                   'compact', tooltip='Opens Softube Central')))
        return apps

    def urgent_row(self, record, problem, helpers):
        row = Gtk.Box(spacing=12)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        titles.set_hexpand(True)
        titles.append(text(self.names.get(record['id'], survey.summarize(record)), 'lib-name', ellipsize=True))
        titles.append(text(problem, 'lib-note', wrap=True))
        row.append(titles)
        row.append(button('Licence handling…', lambda: self.host.record_licensing(record), 'compact'))
        return row

    def leftover_row(self, record, reason, size, largest):
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        head = Gtk.Box(spacing=12)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        titles.set_hexpand(True)
        titles.append(text(self.names.get(record['id'], survey.summarize(record)), 'lib-name', ellipsize=True))
        titles.append(text(reason, 'lib-meta', ellipsize=True))
        head.append(titles)
        figure = text(size_text(size), 'lib-figure')
        figure.set_width_chars(9)
        figure.set_xalign(1.0)
        figure.set_valign(Gtk.Align.CENTER)
        head.append(figure)
        head.append(button('Show folder', lambda: self.host.show_path(record['path']), 'compact', 'lib-quiet'))
        head.append(button('Delete…', lambda: self.host.delete_environment(record), 'compact', 'lib-quiet'))
        row.append(head)
        row.append(bar((size or 0) / largest))
        return row

    def simple_row(self, title, reason, size, action):
        row = Gtk.Box(spacing=12)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        titles.set_hexpand(True)
        titles.append(text(title, 'lib-name', ellipsize=True))
        titles.append(text(reason, 'lib-meta', ellipsize=True))
        row.append(titles)
        if size is not None:
            figure = text(size_text(size), 'lib-figure')
            figure.set_width_chars(9)
            figure.set_xalign(1.0)
            figure.set_valign(Gtk.Align.CENTER)
            row.append(figure)
        row.append(action)
        return row

    def footer(self, breakdown, sizes, records):
        """The whole folder, added up, so that nothing can take room unseen."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.add_css_class('lib-footer')
        identity = survey.identity_summary(records)
        if identity:
            box.append(text(identity, 'lib-note', wrap=True))
        if not breakdown:
            box.append(text('Measuring the library folder…', 'lib-meta'))
            return box
        groups = {}
        for name, size in breakdown.items():
            groups[PARTS.get(name, 'other')] = groups.get(PARTS.get(name, 'other'), 0) + size
        order = ['environments', 'runtimes', 'downloads', 'installers', 'bridge', 'other libraries', 'other']
        parts = ['%s %s' % (key, size_text(groups[key])) for key in order if groups.get(key)]
        total = sum(breakdown.values())
        box.append(text('  ·  '.join(parts), 'lib-meta', wrap=True))
        box.append(text('%s in %s' % (size_text(total), self.host.store.root), 'lib-meta', 'lib-dim',
                        selectable=True, ellipsize=True))
        return box


def clear(box):
    while child := box.get_first_child():
        box.remove(child)


def save_snapshot(window, path):
    """Write what the window shows to a PNG, for looking at a layout without a screen."""
    paintable = Gtk.WidgetPaintable.new(window)
    picture = Gtk.Snapshot()
    paintable.snapshot(picture, window.get_width(), window.get_height())
    texture = window.get_native().get_renderer().render_texture(picture.to_node(), None)
    texture.save_to_png(str(path))


def measure_breakdown(root):
    """Bytes for each top-level entry of the library folder."""
    found = {}
    try:
        entries = list(Path(root).iterdir())
    except OSError:
        return found
    for entry in entries:
        try:
            if entry.is_symlink():
                continue
            found[entry.name] = survey.measure(entry) if entry.is_dir() else entry.stat().st_size
        except OSError:
            continue
    return found


# ---------------------------------------------------------------- demo

class ReadOnlyLibrary:
    """Just enough of a Store to survey a library without writing to it.

    Opening a real Store creates tables and settings when they are missing
    and prepares module runners. Looking at someone's library must do none
    of that. Even SQLite's read-only mode is not enough: on a database in
    WAL mode it still creates the -wal and -shm files beside it. So this
    reads a copy of the database, made in a temporary folder.
    """

    def __init__(self, root):
        import shutil
        import tempfile
        self.root = Path(root).expanduser().resolve()
        database = self.root / 'library.sqlite3'
        if not database.is_file():
            raise SystemExit(f'No library at {self.root}')
        self.scratch = tempfile.TemporaryDirectory(prefix='plugg-preview-')
        copy = Path(self.scratch.name) / 'library.sqlite3'
        for suffix in ('', '-wal'):
            if Path(str(database) + suffix).is_file():
                shutil.copy2(str(database) + suffix, str(copy) + suffix)
        self.uri = copy.as_uri()

    def query(self, sql):
        import sqlite3
        db = sqlite3.connect(self.uri, uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            return [dict(x) for x in db.execute(sql)]
        finally:
            db.close()

    def jobs(self):
        return self.query('SELECT jobs.*, EXISTS(SELECT 1 FROM archived_jobs WHERE job_id=jobs.id) AS archived '
                          'FROM jobs ORDER BY created DESC')

    def plugins(self):
        return self.query('SELECT * FROM plugins ORDER BY name')

    def job(self, job_id):
        for job in self.jobs():
            if job['id'] == job_id:
                return job
        raise KeyError(job_id)

    def prefix(self, job_id):
        return self.root / 'environments' / self.job(job_id)['env_id'] / 'prefix'


def library_data(root):
    """Everything the view shows, read from a real library without changing it."""
    from . import softube, vendors
    store = ReadOnlyLibrary(root)
    records = survey.survey(store)
    setups = vendors.cards(store)
    jobs = store.jobs()
    every = store.plugins()
    plugins = [p for p in every if p['status'] != 'removed']
    sizes = {r['id']: survey.measure(r['path']) for r in records if not r.get('dangling')}
    breakdown = {k: v for k, v in measure_breakdown(store.root).items() if k != 'environments'}
    breakdown['environments'] = sum(sizes.values())
    soft = {r['id'] for r in records if not r.get('dangling') and softube.configured(Path(r['path']))}
    store.publication = Path(json.loads((store.root / 'settings.json').read_text()).get('publication', ''))
    return (records, setups, jobs, sizes, breakdown, survey.unused_runtimes(store),
            survey.nested_libraries(store)), plugins, soft, store.root, [p.get('module') for p in every], \
        survey.dead_bundles(store)


SAMPLE = {
    # environment id: (vendor as its plug-ins report it, [plug-ins])
    '8c1f02aa77e14c0b': [('Universal Audio, Inc.', ['UADx LA-2A']), ('Softube', ['Dirty Tape', 'Harmonics', 'Tape']),
                         ('oeksound', ['soothe'])],
    '3a9d11b2c0e94f21': [('Kilohearts', ['kHs %s' % n for n in (
        '3-Band EQ', 'Bitcrush', 'Channel Mixer', 'Chorus', 'Clipper', 'Comb Filter', 'Compactor', 'Delay',
        'Distortion', 'Filter', 'Flanger', 'Gain', 'Gate', 'Haas', 'Ladder Filter', 'Limiter', 'Phaser',
        'Resonator', 'Reverb')])],
    '71be42d09a3c4e88': [('XLN Audio', ['Addictive Drums 2', 'Addictive Keys'])],
    'c2f4e6a8b0d24c61': [('Klevgrand', ['Skaka', 'Slammer', 'DAW Cassette', 'Brusfri'])],
    'b7a6c5d4e3f21098': [('Plugin Alliance', ['bx_masterdesk', 'bx_opto', 'Shadow Hills Mastering Compressor'])],
    'e5d3c1b9a7f54e33': [],
}


def demo_plugins():
    import json
    return [{'env_id': env_id, 'name': name, 'status': 'ready',
             'metadata': json.dumps({'classes': [{'name': name, 'vendor': vendor}]})}
            for env_id, groups in SAMPLE.items() for vendor, names in groups for name in names]


def demo_data():
    """Sample data for working on the layout. Invented, not anyone's library:
    use --library to look at a real one."""
    gb = 1024 ** 3

    def record(env_id, vendor, size, runtime='UMU-Proton-10.0-4', **extra):
        plugins = [n for _, names in SAMPLE.get(env_id, []) for n in names]
        base = {'id': env_id, 'name': None, 'vendor': vendor, 'recipe': 'installer', 'plugins': plugins,
                'retired': [], 'runtime': runtime, 'path': '/sample/environments/' + env_id, 'jobs': [{'id': 'j'}],
                'in_use': True, 'orphaned': False, 'dangling': False, 'protected': False, 'severity': None,
                'products': [], 'licensing_group': None, 'plugin_vendors': [vendor] if vendor else []}
        base.update(extra)
        return base, size

    rows = [
        record('8c1f02aa77e14c0b', None, 9.8 * gb, runtime='UMU-Proton-10.0-4 (pace-ab)', protected=True,
               severity='deactivate-first', products=['UADx LA-2A'], licensing_group='ilok',
               deactivate_at=['iLok License Manager'], matches_recorded_identity=True),
        record('3a9d11b2c0e94f21', 'Kilohearts', 1.1 * gb, runtime='UMU-Proton-10.0-4 (plugg-1)'),
        record('71be42d09a3c4e88', 'XLN Audio', 4.2 * gb, protected=True, severity='reactivatable',
               products=['Addictive Keys']),
        record('c2f4e6a8b0d24c61', 'Klevgrand', 0.9 * gb, protected=True, severity='deactivate-first',
               products=['Skaka'], deactivate_at=['Klevgrand Helper']),
        record('b7a6c5d4e3f21098', 'Plugin Alliance', 1.4 * gb),
        record('e5d3c1b9a7f54e33', 'Native Instruments', 1.6 * gb),
        record('0f9e8d7c6b5a4938', None, 2.4 * gb, orphaned=True, in_use=False, jobs=[], recipe='softube-v2'),
        record('9a8b7c6d5e4f3a21', None, 0.3 * gb, in_use=False, jobs=[{'id': 'x', 'name': 'Setup.exe'}]),
    ]
    records = [r for r, _ in rows]
    sizes = {r['id']: int(s) for r, s in rows}
    setups = [
        {'job': 'ilok-job', 'recipe': 'pace', 'name': 'iLok', 'has_ilok': True,
         'managers': ['iLok License Manager', 'UA Connect'], 'running': [], 'busy': False},
        {'job': 'ni-job', 'recipe': 'native-instruments-experiment', 'name': 'Native Access',
         'running': ['Native Access'], 'busy': False},
        {'job': 'kg-job', 'recipe': 'klevgrand', 'name': 'Klevgrand Helper', 'running': [], 'busy': False},
        {'job': 'pa-job', 'recipe': 'plugin-alliance-experiment', 'name': 'PA Manager', 'running': [], 'busy': False},
    ]
    jobs = [{'id': 'ilok-job', 'env_id': '8c1f02aa77e14c0b'}, {'id': 'ni-job', 'env_id': 'e5d3c1b9a7f54e33'},
            {'id': 'kg-job', 'env_id': 'c2f4e6a8b0d24c61'}, {'id': 'pa-job', 'env_id': 'b7a6c5d4e3f21098'}]
    breakdown = {'environments': int(21.7 * gb), 'runtimes': int(2.1 * gb), 'downloads': int(0.6 * gb),
                 'jobs': int(1.2 * gb), 'bridge-releases': int(0.05 * gb), 'old-experiment': int(0.7 * gb)}
    return records, setups, jobs, sizes, breakdown, ['proton-10.0-4-pace-ab-old'], []


PREVIEW_ACTIONS = {
    'reclaim_runtime': 'reclaim the unused runtime', 'delete_environment': 'ask to delete the environment',
    'delete_nested': 'ask to delete the separate library', 'show_path': 'open the folder',
    'show_folder': 'open the folder', 'rename_environment': 'rename the environment',
    'record_licensing': 'open licence handling for', 'report': 'open the report form', 'remove_dead_bundle': 'remove the leftover adapter', 'rescan': 'check again for plug-ins from the installation', 'troubleshoot': 'open the fixes for',
    'open_recipes': 'open recipes and fixes', 'stop_helper': 'force close the apps of',
    'show_helper': 'bring back the window of', 'vendor_action': 'open the helper of',
    'manager_action': 'open', 'open_ilok': 'open iLok License Manager in', 'softube_action': 'open Softube Central in',
}


def demo(snapshot=None, mode='dark', width=1120, height=900, expand=(), search='', menu=None, library=None):
    import json
    import sys
    from gi.repository import Gdk
    from . import theme

    if library:
        data, plugins, soft, root, known, dead = library_data(library)
    else:
        data, plugins, soft, root = demo_data(), demo_plugins(), {'8c1f02aa77e14c0b'}, Path.home() / '.local/share/plugg'
        known, dead = None, []

    notice = text('Read-only preview. Buttons show what they would do and change nothing.', 'lib-preview', wrap=True)

    class Host:
        # Every action only says what it would have done. Nothing here opens,
        # stops or deletes anything.
        store = type('Store', (), {'root': root})()

        def helper_offers(self, record):
            return []

        def plugin_facts(self, plugin):
            lines = []
            if plugin.get('publication'):
                lines.append('Your DAW sees: ' + Path(plugin['publication']).name)
            return {'lines': lines}

        def __getattr__(self, name):
            def said(*args):
                what = ' '.join(str(a.get('path') or a.get('id') or a.get('name')) if isinstance(a, dict) else str(a)
                                for a in args if a is not None and not isinstance(a, bool))
                line = 'Would ' + PREVIEW_ACTIONS.get(name, name.replace('_', ' ')) + (': ' + what if what else '')
                notice.set_text(line + '. This preview changes nothing.')
                print('preview:', line, file=sys.stderr)
            return said

    from gi.repository import Gio
    # Not unique: a second preview, or a headless one taking a snapshot, must
    # get its own window instead of handing itself to one already open.
    app = Gtk.Application(application_id='com.oikoaudio.PluggLibraryDemo', flags=Gio.ApplicationFlags.NON_UNIQUE)

    def activate(_):
        # For checking the layout the way people with low vision see it:
        # the desktop's text scale (as Large Text sets it) and high contrast.
        settings = Gtk.Settings.get_default()
        if os.environ.get('PLUGG_TEXT_SCALE'):
            settings.set_property('gtk-xft-dpi', int(96 * 1024 * float(os.environ['PLUGG_TEXT_SCALE'])))
        if os.environ.get('PLUGG_HIGH_CONTRAST'):
            settings.set_property('gtk-interface-contrast', Gtk.InterfaceContrast.MORE)
        window = Gtk.ApplicationWindow(application=app, title='Plugg')
        window.set_default_size(width, height)
        theme.install_font()
        provider = Gtk.CssProvider()
        provider.load_from_data(theme.css(mode))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        view = LibraryView(Host())
        view.expanded.update(expand)
        view.update(*data, plugins=plugins, softube=soft, known_modules=known, dead_bundles=dead)
        if search:
            view.search.set_text(search)
        scroll = Gtk.ScrolledWindow()
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(page, 'set_margin_' + side)(28)
        notice.set_margin_bottom(14)
        page.append(notice)
        page.append(view.widget)
        scroll.set_child(page)
        window.set_child(scroll)
        view.attach(window)
        window.present()
        if snapshot:
            if menu:
                GLib.timeout_add(800, lambda: view.menus[menu].popup() or False)

            def shoot():
                save_snapshot(window, snapshot)
                if menu:
                    save_snapshot(view.menus[menu].get_popover(), snapshot.replace('.png', '-menu.png'))
                print(json.dumps({'snapshot': snapshot}), flush=True)
                app.quit()
                return False
            GLib.timeout_add(int(os.environ.get('PLUGG_SNAPSHOT_DELAY', '1500')), shoot)

    app.connect('activate', activate)
    app.run([])


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Show the library view with sample data')
    ap.add_argument('--demo', action='store_true', required=True)
    ap.add_argument('--snapshot', help='save a PNG of the window here and quit')
    ap.add_argument('--light', action='store_true')
    ap.add_argument('--expand', action='append', default=[], help='environment id to show opened')
    ap.add_argument('--search', default='')
    ap.add_argument('--height', type=int, default=900)
    ap.add_argument('--menu', help='environment id whose settings menu to open')
    ap.add_argument('--library', help='show this library, read-only, instead of sample data')
    a = ap.parse_args()
    demo(a.snapshot, 'light' if a.light else 'dark', height=a.height, expand=a.expand, search=a.search,
         menu=a.menu, library=a.library)
