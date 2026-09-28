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
from pathlib import Path

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from . import environments as survey  # noqa: E402

#: The library folder's own parts, by what they hold. Anything else there is
#: counted as unaccounted for and, past a threshold, shown as needing a look.
PARTS = {'environments': 'environments', 'runtimes': 'runtimes', 'downloads': 'downloads',
         'runtime-cache': 'runtimes', 'bridge-releases': 'bridge', 'bundles': 'bridge',
         'jobs': 'installers', 'managed-libraries': 'other libraries'}
UNACCOUNTED_THRESHOLD = 256 * 1024 ** 2

#: The helper's own name, where the recipe name is all a card carries.
HELPER_TITLES = {'klevgrand': 'Klevgrand Helper', 'native-instruments-experiment': 'Native Access',
                 'pace-service-experiment': 'UA Connect', 'plugin-alliance-experiment': 'PA Manager'}

SEVERITY_CHIP = {'deactivate-first': 'deactivate first', 'limited-activations': 'limited activations',
                 'unknown': 'licence unclassified', 'reactivatable': 'serial', 'unlicensed': None}


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
        self.append(text(title, 'lib-section-title'))
        rule = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        rule.set_hexpand(True)
        rule.set_valign(Gtk.Align.CENTER)
        self.append(rule)
        self.trailing = text(trailing, 'lib-figure', 'lib-dim')
        self.append(self.trailing)


def group():
    """One panel per section, rows divided by hairlines: a list, not a pile of cards."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.add_css_class('lib-list')
    box.set_overflow(Gtk.Overflow.HIDDEN)
    return box


def bar(fraction, *classes):
    """ncdu's bar: how much of the largest this one is, and nothing else."""
    widget = Gtk.ProgressBar()
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
        self.expanded = set()
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.widget.add_css_class('library')
        top = Gtk.Box(spacing=12)
        self.search = Gtk.SearchEntry(placeholder_text='Find a plug-in or vendor')
        self.search.set_hexpand(True)
        self.search.connect('search-changed', self.search_changed)
        top.append(self.search)
        top.append(button('Recipes & fixes', lambda: self.host.open_recipes(), 'compact', 'lib-quiet',
                          tooltip='Setups for vendors, and reusable fixes for plug-ins that do not work at first'))
        self.totals = text('', 'lib-figure', 'lib-dim')
        self.totals.set_valign(Gtk.Align.CENTER)
        top.append(self.totals)
        self.widget.append(top)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.widget.append(self.body)
        self.last = None

    def search_changed(self, entry):
        self.query = entry.get_text().strip().casefold()
        if self.last:
            self.render(*self.last)

    # ------------------------------------------------------------ the model

    def update(self, records, setups, jobs, sizes, breakdown, spare_runtimes, nested):
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
    def needs_attention(record, helpers):
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

    # ------------------------------------------------------------ drawing

    def render(self, records, setups, jobs, sizes, breakdown, spare_runtimes, nested):
        clear(self.body)
        helpers = self.helpers_by_environment(setups, jobs)
        self.names = display_names(records)
        attention, vendors = [], []
        for record in records:
            reason = self.needs_attention(record, helpers.get(record['id']))
            (attention if reason else vendors).append((record, reason))
        unaccounted = unlisted(breakdown)
        measured = [sizes.get(r['id']) for r, _ in attention + vendors]
        largest = max([s for s in measured if s] or [1])

        freeable = sum(sizes.get(r['id']) or 0 for r, _ in attention)
        if attention or spare_runtimes or nested or unaccounted:
            self.body.append(Section('needs attention', size_text(freeable) + ' reclaimable' if freeable else ''))
            listing = group()
            self.body.append(listing)
            for record, reason in attention:
                listing.append(self.attention_row(record, reason, sizes.get(record['id']), largest))
            for name in spare_runtimes:
                listing.append(self.simple_attention(
                    'Unused runtime ' + name, 'No environment uses it. It is downloaded again if one ever does.',
                    None, button('Reclaim', lambda n=name: self.host.reclaim_runtime(n), 'compact')))
            for library in nested:
                action = button('Delete…', lambda n=library: self.host.delete_nested(n), 'compact',
                                sensitive=not library.get('required_by'),
                                tooltip=('Needed by ' + ', '.join(library['required_by']))
                                if library.get('required_by') else None)
                listing.append(self.simple_attention(
                    'Separate library ' + library['name'],
                    plural(library['environments'], 'environment') + ' with its own downloads and runtimes',
                    None, action))
            for name, size in unaccounted:
                listing.append(self.simple_attention(
                    name, 'In the library folder, and nothing here lists it.', size,
                    button('Show folder', lambda n=name: self.host.show_folder(n), 'compact')))

        shown = [(r, self.matches(r)) for r, _ in vendors]
        shown = [(r, m) for r, m in shown if m is not None]
        count = sum(len(r['plugins']) for r, _ in vendors)
        self.body.append(Section('vendors', plural(count, 'plug-in')))
        if not vendors:
            self.body.append(text('Nothing installed yet. Drop an installer or a VST3 above.', 'lib-dim'))
        elif not shown:
            self.body.append(text('Nothing matches “%s”.' % self.query, 'lib-dim'))
        order = sorted(shown, key=lambda item: (-(sizes.get(item[0]['id']) or 0), self.names.get(item[0]['id'], '').casefold()))
        listing = group()
        if order:
            self.body.append(listing)
        for record, hits in order:
            listing.append(self.vendor_row(record, hits, helpers.get(record['id'], []),
                                             sizes.get(record['id']), largest))

        self.body.append(self.footer(breakdown, sizes, records))
        total = sum((breakdown or {}).values()) if breakdown else None
        self.totals.set_text(plural(len(vendors), 'vendor') + ' · ' + size_text(total))

    def matches(self, record):
        """None when the search excludes this row, else the plug-ins it matched."""
        if not self.query:
            return []
        if self.query in self.names.get(record['id'], survey.summarize(record)).casefold():
            return []
        hits = [name for name in record['plugins'] if self.query in name.casefold()]
        return hits or None

    def vendor_row(self, record, hits, helpers, size, largest):
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        row.add_css_class('lib-item')
        head = Gtk.Box(spacing=12)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        titles.set_hexpand(True)
        name_line = Gtk.Box(spacing=8)
        name_line.append(text(self.names.get(record['id'], survey.summarize(record)), 'lib-name', ellipsize=True))
        chip = SEVERITY_CHIP.get(record.get('severity')) if record.get('protected') else None
        if record.get('protected') is None:
            chip = 'licence note unreadable'
        if chip:
            badge = text(chip, 'lib-chip', 'lib-chip-caution' if record.get('severity') != 'reactivatable' else 'lib-chip')
            badge.set_valign(Gtk.Align.CENTER)
            badge.set_tooltip_text(survey.licensing_line(record) or '')
            name_line.append(badge)
        titles.append(name_line)
        meta = [plural(len(record['plugins']), 'plug-in'), short_runtime(record), record['id'][:8]]
        if record.get('retired'):
            meta.insert(1, '%d retired' % len(record['retired']))
        titles.append(text('  ·  '.join(meta), 'lib-meta', ellipsize=True))
        head.append(titles)
        for control in self.helper_buttons(record, helpers)[:1]:
            head.append(control)
        figure = text(size_text(size), 'lib-figure')
        figure.set_width_chars(9)
        figure.set_xalign(1.0)
        figure.set_valign(Gtk.Align.CENTER)
        head.append(figure)
        opened = record['id'] in self.expanded or bool(hits)
        toggle = Gtk.Button(icon_name='pan-down-symbolic' if opened else 'pan-end-symbolic')
        toggle.add_css_class('lib-toggle')
        toggle.set_valign(Gtk.Align.CENTER)
        toggle.set_tooltip_text('Plug-ins, licence handling and removal')
        head.append(toggle)
        row.append(head)
        row.append(bar((size or 0) / largest))
        revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=140)
        revealer.set_reveal_child(opened)
        revealer.set_child(self.details(record, hits, helpers))
        row.append(revealer)

        def flip(*_):
            now = not revealer.get_reveal_child()
            revealer.set_reveal_child(now)
            toggle.set_icon_name('pan-down-symbolic' if now else 'pan-end-symbolic')
            (self.expanded.add if now else self.expanded.discard)(record['id'])
        toggle.connect('clicked', flip)
        click = Gtk.GestureClick()
        click.connect('released', lambda gesture, n, x, y: flip() if gesture.get_current_button() == 1 else None)
        titles.add_controller(click)
        return row

    def details(self, record, hits, helpers):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.add_css_class('lib-details')
        if record['plugins']:
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=6, row_spacing=6,
                               max_children_per_line=30, homogeneous=False)
            for name in record['plugins']:
                chip = text(name, 'lib-plugin', *(('lib-plugin-hit',) if name in hits else ()))
                chip.set_halign(Gtk.Align.START)
                flow.append(chip)
            box.append(flow)
        else:
            box.append(text('No plug-ins published from here yet.', 'lib-dim'))
        line = survey.licensing_line(record)
        if line:
            box.append(text(line, 'lib-note', wrap=True))
        actions = Gtk.Box(spacing=8)
        for control in self.helper_buttons(record, helpers)[1:]:
            actions.append(control)
        actions.append(button('Licence handling…', lambda: self.host.record_licensing(record), 'compact',
                              tooltip='How licences work for what is installed here; protects the environment'))
        actions.append(button('Rename…', lambda: self.host.rename_environment(record), 'compact'))
        actions.append(button('Troubleshoot…', lambda: self.host.troubleshoot(record), 'compact',
                              tooltip='Reusable fixes for plug-ins that load badly, draw wrongly or crash'))
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        actions.append(spacer)
        actions.append(button('Show folder', lambda: self.host.show_path(record['path']), 'compact', 'lib-quiet'))
        actions.append(button('Delete…', lambda: self.host.delete_environment(record), 'compact', 'lib-danger'))
        box.append(actions)
        return box

    def helper_buttons(self, record, helpers):
        """The vendor's own app first: that is what a row is opened for most often."""
        controls = []
        for setup in helpers:
            job, running, busy = setup['job'], setup.get('running') or [], setup.get('busy')
            managers = setup.get('managers') or []
            if setup.get('has_ilok'):
                named = [('Open iLok', 'iLok License Manager')] + [
                    ('Open ' + m, m) for m in managers if m not in ('iLok License Manager',)]
                for title, manager in named:
                    live = any(manager.split()[0].casefold() in n.casefold() for n in running)
                    if live:
                        controls.append(button(title, lambda j=job: self.host.show_helper(j), 'compact', 'running',
                                               tooltip='Running. Bring its window back.'))
                    elif manager in managers:
                        controls.append(button(title, lambda j=job, m=manager: self.host.manager_action(j, m),
                                               'compact', sensitive=not busy))
                    elif manager == 'iLok License Manager':
                        controls.append(button(title, lambda j=job: self.host.open_ilok(j), 'compact',
                                               sensitive=not busy))
            else:
                title = 'Open ' + HELPER_TITLES.get(setup['recipe'], setup.get('name') or 'helper')
                if running:
                    controls.append(button(title, lambda j=job: self.host.show_helper(j), 'compact', 'running',
                                           tooltip='Running. Bring its window back.'))
                else:
                    controls.append(button(title, lambda j=job: self.host.vendor_action(j, False), 'compact',
                                           sensitive=not busy))
            if busy or setup.get('needs_attention') or running:
                controls.append(button('Force close', lambda j=job: self.host.stop_helper(j, 'this environment'),
                                       'compact', tooltip='End the Windows programs still running here'))
        return controls

    def attention_row(self, record, reason, size, largest):
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        row.add_css_class('lib-item')
        row.add_css_class('lib-attention')
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
        head.append(button('Delete…', lambda: self.host.delete_environment(record), 'compact', 'lib-danger'))
        row.append(head)
        row.append(bar((size or 0) / largest, 'lib-bar-attention'))
        return row

    def simple_attention(self, title, reason, size, action):
        row = Gtk.Box(spacing=12)
        row.add_css_class('lib-item')
        row.add_css_class('lib-attention')
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

def demo_data():
    """A library that looks like a real one, for working on the layout."""
    gb = 1024 ** 3

    def record(env_id, vendor, plugins, size, runtime='UMU-Proton-10.0-4', **extra):
        base = {'id': env_id, 'name': None, 'vendor': vendor, 'recipe': 'installer', 'plugins': plugins,
                'retired': [], 'runtime': runtime, 'path': '/demo/environments/' + env_id, 'jobs': [{'id': 'j'}],
                'in_use': True, 'orphaned': False, 'dangling': False, 'protected': False, 'severity': None,
                'products': [], 'licensing_group': None, 'plugin_vendors': [vendor]}
        base.update(extra)
        return base, size

    kh = ['kHs %s' % n for n in ('3-Band EQ', 'Bitcrush', 'Channel Mixer', 'Chorus', 'Clipper', 'Comb Filter',
                                 'Compactor', 'Delay', 'Distortion', 'Filter', 'Flanger', 'Gain', 'Gate',
                                 'Haas', 'Ladder Filter', 'Limiter', 'Phaser', 'Resonator', 'Reverb')]
    rows = [
        record('8c1f02aa77e14c0b', 'iLok (shared by iLok-licensed vendors)',
               ['bx_masterdesk', 'bx_opto', 'Shadow Hills Mastering Compressor', 'UADx LA-2A', 'Dirty Tape',
                'Harmonics', 'Tape', 'Weiss DS1-MK3'], 9.8 * gb,
               runtime='UMU-Proton-10.0-4 (pace-ab)', protected=True, severity='deactivate-first',
               products=['bx_masterdesk', 'UADx LA-2A'], licensing_group='ilok', deactivate_at=['iLok License Manager']),
        record('3a9d11b2c0e94f21', 'Kilohearts', kh, 1.1 * gb, runtime='UMU-Proton-10.0-4 (plugg-1)'),
        record('71be42d09a3c4e88', 'XLN Audio', ['Addictive Drums 2', 'Addictive Keys'], 4.2 * gb,
               protected=True, severity='reactivatable', products=['Addictive Keys']),
        record('c2f4e6a8b0d24c61', 'Klevgrand', ['Skaka', 'Slammer', 'DAW Cassette', 'Brusfri'], 0.9 * gb,
               protected=True, severity='deactivate-first', products=['Skaka'], deactivate_at=['Klevgrand Helper']),
        record('e5d3c1b9a7f54e33', 'Native Instruments', [], 1.6 * gb),
        record('0f9e8d7c6b5a4938', None, [], 2.4 * gb, orphaned=True, in_use=False, jobs=[],
               plugin_vendors=[], recipe='softube-v2'),
        record('9a8b7c6d5e4f3a21', None, [], 0.3 * gb, in_use=False, jobs=[{'id': 'x', 'name': 'Setup.exe'}],
               plugin_vendors=[]),
    ]
    records = [r for r, _ in rows]
    sizes = {r['id']: int(s) for r, s in rows}
    setups = [
        {'job': 'ilok-job', 'recipe': 'pace', 'name': 'iLok', 'has_ilok': True,
         'managers': ['iLok License Manager', 'UA Connect'], 'running': [], 'busy': False},
        {'job': 'ni-job', 'recipe': 'native-instruments-experiment', 'name': 'Native Access',
         'running': ['Native Access'], 'busy': False},
        {'job': 'kg-job', 'recipe': 'klevgrand', 'name': 'Klevgrand Helper', 'running': [], 'busy': False},
    ]
    jobs = [{'id': 'ilok-job', 'env_id': '8c1f02aa77e14c0b'}, {'id': 'ni-job', 'env_id': 'e5d3c1b9a7f54e33'},
            {'id': 'kg-job', 'env_id': 'c2f4e6a8b0d24c61'}]
    breakdown = {'environments': int(20.3 * gb), 'runtimes': int(2.1 * gb), 'downloads': int(0.6 * gb),
                 'jobs': int(1.2 * gb), 'bridge-releases': int(0.05 * gb), 'old-experiment': int(0.7 * gb)}
    return records, setups, jobs, sizes, breakdown, ['proton-10.0-4-pace-ab-old'], []


def demo(snapshot=None, mode='dark', width=1120, height=900, expand=(), search=''):
    import json
    import sys
    from gi.repository import Gdk
    from . import theme

    class Host:
        store = type('Store', (), {'root': Path.home() / '.local/share/plugg'})()

        def __getattr__(self, name):
            return lambda *args: print('demo:', name, *[getattr(a, 'get', lambda k: a)('id') if isinstance(a, dict)
                                                       else a for a in args], file=sys.stderr)

    app = Gtk.Application(application_id='com.oikoaudio.PluggLibraryDemo')

    def activate(_):
        window = Gtk.ApplicationWindow(application=app, title='Plugg')
        window.set_default_size(width, height)
        theme.install_font()
        provider = Gtk.CssProvider()
        provider.load_from_data(theme.css(mode))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        view = LibraryView(Host())
        view.expanded.update(expand)
        view.update(*demo_data())
        if search:
            view.search.set_text(search)
        scroll = Gtk.ScrolledWindow()
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(page, 'set_margin_' + side)(28)
        page.append(view.widget)
        scroll.set_child(page)
        window.set_child(scroll)
        window.present()
        if snapshot:
            def shoot():
                save_snapshot(window, snapshot)
                print(json.dumps({'snapshot': snapshot}), flush=True)
                app.quit()
                return False
            GLib.timeout_add(1500, shoot)

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
    a = ap.parse_args()
    demo(a.snapshot, 'light' if a.light else 'dark', height=a.height, expand=a.expand, search=a.search)
