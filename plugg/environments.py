"""What environments exist, what is in them, and what they are worth.

The manager hides environments on purpose: choosing which prefix a plug-in
lands in is how people break their own installations, and nothing here offers
that choice. But hiding them also hid the answers to fair questions — how many
are there, which is the twelve gigabytes, which one holds the licences, which
ones still look like a machine of their own — and left the person with a
directory listing and a guess.

So this reports. It reads; it never creates, moves, repairs or deletes an
environment, and the survey is assembled from records that already exist.

SPDX-License-Identifier: GPL-3.0-or-later
"""
import json
import os
from pathlib import Path

from . import core


def measure(path):
    """Bytes on disk, following no symlink and counting no file twice.

    A prefix holds hard links and symlinks into shared runtimes. Counting what
    they point at would report a number far larger than what freeing this
    environment would actually give back, which is the only reason anyone is
    asking.
    """
    total = 0
    seen = set()
    stack = [Path(path)]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                info = entry.stat()
            except OSError:
                continue
            if entry.is_dir():
                stack.append(entry)
            elif info.st_ino not in seen:
                seen.add(info.st_ino)
                total += info.st_size
    return total


#: Names people give environments. Kept in the library, not in the
#: environment: renaming never writes inside a prefix, and never moves one.
#: The directory keeps its ID, because launchers, published plug-ins and the
#: licensing record all refer to that path.
NAMES = 'environment-names.json'
NAME_LIMIT = 60


def names(store):
    try:
        data = json.loads((Path(store.root) / NAMES).read_text())
    except (OSError, ValueError):
        return {}
    return {key: value for key, value in data.get('names', {}).items() if isinstance(value, str)}


def rename(store, env_id, name):
    """Give an environment a name, or clear it with an empty name."""
    if not (Path(store.root) / 'environments' / env_id).exists():
        raise core.HostError('No environment ' + env_id + ' in this library.')
    name = ' '.join(str(name).split())
    if len(name) > NAME_LIMIT:
        raise core.HostError('Keep the name to %d characters.' % NAME_LIMIT)
    known = names(store)
    if name:
        known[env_id] = name
    else:
        known.pop(env_id, None)
    core.atomic_json(Path(store.root) / NAMES, {'schema': 1, 'names': known})
    return name or None


def describe(store, directory, jobs, plugins):
    """One environment, from the records that already describe it."""
    env_id = directory.name
    try:
        config = json.loads((directory / 'environment.json').read_text())
    except (OSError, ValueError):
        config = {}
    owned = [job for job in jobs if job['env_id'] == env_id]
    published = [p for p in plugins if p['env_id'] == env_id and p['status'] != 'removed']
    retired = [p for p in plugins if p['env_id'] == env_id and p['status'] == 'removed']
    makers = sorted({(item.get('vendor') or '').strip()
                     for p in published for item in json.loads(p['metadata']).get('classes', [])} - {''},
                    key=str.casefold)
    record = {
        'id': env_id,
        'name': names(store).get(env_id),
        'licensing_group': config.get('licensing_group'),
        'plugin_vendors': makers,
        'dangling': directory.is_symlink() and not directory.exists(),
        'recipe': config.get('recipe'),
        'vendor': config.get('vendor') or config.get('display_name'),
        'runtime': config.get('runtime'),
        'path': str(directory),
        'jobs': [{'id': job['id'], 'name': job['name'], 'status': job['status'],
                  'archived': bool(job['archived'])} for job in owned],
        'plugins': sorted(p['name'] for p in published),
        'retired': sorted(p['name'] for p in retired),
        # An environment every job of which is archived is still on disk, and
        # is usually the one someone is looking for when they ask about space.
        'in_use': any(not job['archived'] for job in owned),
        'orphaned': not owned,
    }
    from . import licensing
    try:
        state = licensing.status(directory)
        record['protected'] = state['protected']
        record['severity'] = state['severity']
        record['products'] = [item['name'] for item in state['products']]
        # The full entries, so a form can show what was said about each one.
        # A directly-imported environment is a grab bag: one plug-in free, the
        # next serial-based, the next bound to a machine.
        record['recorded'] = state['products']
        record['deactivate_at'] = sorted({item['deactivate_at'] for item in state['products']
                                          if item.get('deactivate_at')})
        record['identity_is_this_computer'] = state['machine_identity_is_this_computer']
        record['matches_recorded_identity'] = state['matches_recorded_identity']
    except (OSError, ValueError, core.HostError):
        record['protected'] = None
        record['severity'] = None
        record['products'] = []
        record['recorded'] = []
        record['deactivate_at'] = []
        record['identity_is_this_computer'] = None
        record['matches_recorded_identity'] = None
    return record


def survey(store):
    """Every environment this library knows of, newest records first.

    Sizes are not included. Walking a Proton prefix takes long enough to be
    felt, and this runs behind an interface that refreshes continuously; the
    caller measures what it decides to show, when it decides to show it.
    """
    root = store.root / 'environments'
    try:
        # A symlink whose target is gone is still this library's entry, and it
        # is precisely when you most want to be rid of it. Listing only what
        # resolves made a dangling link invisible, and so undeletable.
        directories = sorted(x for x in root.iterdir() if x.is_dir() or x.is_symlink())
    except OSError:
        return []
    jobs = store.jobs()
    plugins = store.plugins()
    return [describe(store, directory, jobs, plugins) for directory in directories]


#: How far a setup got before it failed. Up to and including the last of
#: these, nothing of the vendor's has run: no product is installed, no serial
#: has been entered, no machine has been registered with anybody. What is on
#: disk is a Wine prefix and some Microsoft redistributables, which the next
#: attempt builds again from scratch in the same few minutes.
NOTHING_INSTALLED_YET = ('preparing-runtime', 'preparing-environment', 'preparing-vc-runtime')


def worthless(store, job_id):
    """Whether a failed attempt left an environment worth keeping.

    Keeping every failure's prefix was the cautious-looking choice and it is
    the one that made this a chore. A setup that died while unpacking Proton
    has nothing in it anybody could want, and there is no argument for making
    someone find it later and decide that themselves.

    Everything is a reason to keep it: a vendor installer that started, a
    licensing record, a published plug-in, an unreadable journal. This says
    yes only when the record positively shows the attempt never got that far.
    """
    job = store.job(job_id)
    if job['status'] not in ('failed', 'cancelled'):
        return False
    directory = store.root / 'environments' / job['env_id']
    if job['env_id'] != job_id or not directory.is_dir() or directory.is_symlink():
        return False
    if (directory / 'licensing.json').exists() or (directory / '.licensing-key').exists():
        return False
    if any(p['env_id'] == job['env_id'] for p in store.plugins()):
        return False
    from . import formats
    names = (('import-state.json',) if formats.is_import(job)
             else ('helper-setup.json', core.SETUP_STAGE))
    journal = next((store.root / 'jobs' / job_id / name for name in names
                    if (store.root / 'jobs' / job_id / name).exists()), None)
    try:
        stage = json.loads(journal.read_text()).get('stage')
    except (OSError, ValueError, AttributeError):
        return False
    return stage in NOTHING_INSTALLED_YET


def tidy_after_failure(store, job_id):
    """Remove what a failed setup left, when it left nothing of value.

    Called where the failure happens, so the disk is as it was before the
    attempt rather than a few gigabytes heavier for nothing.
    """
    import shutil
    try:
        if not worthless(store, job_id):
            return None
        directory = store.root / 'environments' / store.job(job_id)['env_id']
        freed = measure(directory)
        shutil.rmtree(directory)
        return {'environment': directory.name, 'freed': freed}
    except (OSError, core.HostError):
        return None


def partition(records):
    """Split what is carrying plug-ins from what is only taking up room.

    These are read with opposite intentions. One list is checked — is my
    licensed environment still here, is it still this machine — and the other
    is emptied. Mixed together, every deletion means first working out which
    kind each row is, and the row you must not touch sits next to the row you
    came to delete.

    The test is what this library positively knows: that an environment
    publishes a plug-in a DAW would lose, or that it was recorded as holding
    activations. Either is a reason not to delete it casually.

    The other list is not "inactive", and must never be labelled as though it
    were. It is "nothing was published from these, and nothing was recorded
    about them" — which is also what an environment looks like when a vendor
    counts it as a machine and nobody ever wrote that down. The grouping is
    there to stop the row you must not touch sitting beside the row you came
    to delete; it is not a safety verdict, and the caller should not present
    it as one.
    """
    def known_to_matter(record):
        return bool(record['plugins']) or bool(record['protected'])
    return ([r for r in records if known_to_matter(r)],
            [r for r in records if not known_to_matter(r)])


def by_size(records, sizes):
    """Largest first, because that is the order the question is asked in."""
    return sorted(records, key=lambda r: (-(sizes.get(r['id']) or 0), r['id']))


def removal_phrase(record):
    """The exact words that must be typed to delete this environment.

    An environment holding activations already has a phrase: the one the guard
    demands, which names what is actually at stake rather than a folder. For
    anything else the vendor's name will do. The point is not to make deletion
    hard — it is to make it impossible to do while thinking about something
    else, because nothing here can be undone.
    """
    from . import licensing
    # An environment recorded as holding nothing licensed is in the same
    # position as one never recorded at all: there is nothing to assert.
    if record['protected'] and record['severity'] != 'unlicensed':
        return licensing.CONFIRMATION[record['severity'] or 'unknown']
    return 'DELETE ' + (record['vendor'] or record['id'][:8]).upper()


def entry(store, record):
    """This library's own entry for an environment, symlink and all.

    Some entries are links into another library's directory — an older root
    that was adopted rather than copied. The link is the whole of this
    library's claim on it; the directory at the far end belongs to someone
    else and is not ours to delete.
    """
    name = record['id']
    if '/' in name or name in ('.', '..'):
        raise core.HostError('Not an environment name: ' + name)
    path = store.root / 'environments' / name
    if path.is_symlink():
        return path, path.resolve()
    if path.resolve() != Path(record['path']).resolve():
        raise core.HostError('Not an environment of this library: ' + record['path'])
    return path, None


def blockers(store, record):
    """Why this environment cannot be deleted yet, in words, before anyone types.

    Asking for a confirmation phrase and only then refusing wastes the one
    moment the person was paying full attention.
    """
    from . import vendors
    reasons = []
    busy = [job for job in record['jobs'] if job['status'] not in core.TERMINAL]
    if busy:
        reasons.append('Still working on ' + ', '.join(j['name'] for j in busy)
                       + '. Cancel it first.')
    try:
        path, _ = entry(store, record)
        # Windows programs, not Wine's own services: an idle plug-in session
        # stays up for minutes after the last plug-in closes, and remove()
        # stops it itself.
        running = vendors.program_names(path / 'prefix')
        if running:
            reasons.append('Windows programs are still running in this environment ('
                           + ', '.join(running) + '). Close them, or close the DAW that '
                           'uses its plug-ins, then try again.')
    except core.HostError as exc:
        reasons.append(str(exc))
    return reasons


def _stop_idle_session(path):
    """Stop what is left running in an environment that runs no Windows program.

    That is the managed plug-in session, idle until its timeout, and Wine's
    services with it. stop_idle_session checks again under the session lock
    that nothing but those is running before it ends anything.
    """
    from . import proton_session
    prefix = path / 'prefix'
    if not proton_session.foreign_prefix_processes(prefix):
        return
    try:
        if not (path / 'session.json').is_file():
            raise RuntimeError('This environment has no managed session to stop.')
        proton_session.stop_idle_session(path / 'session.json')
    except (OSError, ValueError, RuntimeError) as exc:
        raise core.HostError('Something is still running in this environment and could not be '
                             'stopped safely: ' + str(exc) + ' Wait a minute and try again.') from exc


def remove(store, record, confirmation):
    """Delete one environment and everything inside it. There is no way back.

    The prefix is the installed products, their settings and, for some vendors,
    the activation itself. No recovery point covers this — a recovery point
    holds the identity files, which is a few kilobytes, not the gigabytes that
    made someone want the space back.

    What is deliberately *not* a reason to refuse: an installation record that
    refers to this environment. Those records describe what lived here, so they
    go with it; asking someone to archive them first was asking them to perform
    a ritual on the way to the same place.
    """
    import shutil
    from . import licensing
    path, foreign = entry(store, record)
    expected = removal_phrase(record)
    if confirmation != expected:
        raise core.HostError('Type the confirmation exactly to delete this environment:\n  '
                             + expected)
    for reason in blockers(store, record):
        raise core.HostError(reason)
    if foreign is None:
        # Before the acknowledgement, which the guard uses up: a session that
        # will not stop should not cost the person their typed phrase.
        _stop_idle_session(path)
    if record['protected']:
        # The phrase has already been typed; this records the acknowledgement
        # the guard consumes, so removal follows exactly the path every other
        # identity-changing operation follows. An environment recorded as
        # holding nothing licensed was confirmed with DELETE <VENDOR>, which
        # the guard does not know, so its own phrase for that case stands in.
        licensing.acknowledge(path, 'remove_environment',
                              licensing.CONFIRMATION['unlicensed']
                              if record['severity'] == 'unlicensed' else confirmation)
    licensing.guard(path, 'remove_environment')
    # Found before anything changes: once the environment is gone, its
    # bundles point at nothing and their manifests are all that tie them to it.
    bundles = environment_bundles(store, record['id']) if foreign is None else []
    retired = 0
    for plugin in store.plugins():
        if plugin['env_id'] == record['id'] and plugin['status'] != 'removed':
            core.forget_plugin(store, plugin['id'])
            retired += 1
    for job in record['jobs']:
        store.discard(job['id'])
    if foreign is not None:
        # Remove this library's link to it and say where the real one is. It
        # belongs to another library, and deleting other people's data because
        # a link pointed at it is exactly the accident worth refusing.
        path.unlink()
        return {'environment': record['id'], 'retired': retired, 'unlinked': str(foreign),
                'freed': 0}
    shutil.rmtree(path)
    # A bundle is kept when a plug-in is only unpublished, so it can be
    # published again. With the environment gone there is nothing left for it
    # to load, so it goes too.
    removed = sum(1 for bundle in bundles if _remove_bundle(store, bundle))
    return {'environment': record['id'], 'retired': retired, 'unlinked': None,
            'freed': None, 'bundles_removed': removed}


def _bundles_dir(store):
    return Path(store.root) / 'bundles'


def _all_bundles(store):
    """[(bundle, format)] for every bundle directory the library holds, VST3 first."""
    from . import formats
    found = []
    for kind in formats.FORMATS:
        directory = formats.bundles(store, kind)
        try:
            entries = sorted(directory.glob('*.vst3') if kind == 'vst3' else directory.iterdir())
        except OSError:
            continue
        found.extend((entry, kind) for entry in entries
                     if not entry.name.startswith('.') and entry.is_dir() and not entry.is_symlink())
    return found


def _bundle_name(store, bundle):
    """How a bundle is named to the person and to remove_dead_bundle: relative to bundles/."""
    return str(Path(bundle).relative_to(_bundles_dir(store)))


def _manifest(bundle):
    try:
        return json.loads((bundle / 'plugg.json').read_text())
    except (OSError, ValueError):
        return {}


def _managed(bundle, kind='vst3'):
    """A bundle this library built: its Linux side carries the marker make_bundle writes."""
    from . import formats
    return (formats.native_directory(bundle, kind) / '.plugg-managed').is_file() and not bundle.is_symlink()


def _published(store):
    """The bundles a DAW can see right now: the targets of the links in the publication folders."""
    from . import formats
    seen = set()
    for kind in formats.FORMATS:
        try:
            entries = list(Path(formats.folder(store, kind)).iterdir())
        except (OSError, AttributeError, TypeError, ValueError):
            continue
        for entry in entries:
            if entry.is_symlink():
                seen.add(os.path.realpath(entry))
    return seen


def environment_bundles(store, env_id):
    """The bundles built for one environment, by what their own manifest says."""
    return [b for b, kind in _all_bundles(store) if _managed(b, kind) and _manifest(b).get('environment') == env_id]


def _windows_module_gone(bundle, kind='vst3'):
    from . import formats
    link = formats.windows_link(bundle, kind)
    return link.is_symlink() and not link.exists()


def dead_bundles(store):
    """Bundles whose Windows plug-in no longer exists and that nothing publishes.

    Deleting an environment now takes its bundles with it; these are the ones
    left behind before it did, or by an environment removed some other way.
    Each is a small folder the DAW never sees, so they are listed under
    cleanup rather than anywhere that asks for attention.
    """
    published = _published(store)
    found = []
    for bundle, kind in _all_bundles(store):
        if _managed(bundle, kind) and _windows_module_gone(bundle, kind) and os.path.realpath(bundle) not in published:
            found.append({'name': _bundle_name(store, bundle), 'path': str(bundle), 'format': kind,
                          'environment': _manifest(bundle).get('environment')})
    return found


def _remove_bundle(store, bundle):
    """Delete one bundle if it is ours and no DAW-visible link still leads to it."""
    import shutil
    from . import formats
    bundle = Path(bundle)
    kind = next((k for k in formats.FORMATS if bundle.parent == formats.bundles(store, k)), None)
    if kind is None or not _managed(bundle, kind):
        return False
    if os.path.realpath(bundle) in _published(store):
        return False
    shutil.rmtree(bundle)
    return True


def remove_dead_bundle(store, name):
    """Delete a bundle dead_bundles() lists. Checked again here, under the publication lock."""
    # VST2 and CLAP bundles are named with their folder, as in "clap/Name".
    parts = str(name or '').split('/')
    if (not name or len(parts) > 2 or any(part in ('', '.', '..') for part in parts)
            or (len(parts) == 2 and parts[0] not in ('vst2', 'clap'))):
        raise core.HostError('Not a bundle of this library: ' + str(name))
    with core.lock(Path(store.root) / 'publication.lock'):
        bundle = _bundles_dir(store) / name
        if not any(item['path'] == str(bundle) for item in dead_bundles(store)):
            raise core.HostError(name + ' is still in use, or is not a leftover bundle.')
        _remove_bundle(store, bundle)
    return {'removed': name}


def runtime_users(store):
    """Which environments depend on each provisioned runtime.

    An environment names its runtime in its session record and in the launcher
    scripts beside it, so the directory name is looked for in both rather than
    parsed out of one. Being wrong in the direction of "still used" costs disk;
    being wrong the other way deletes something a working environment needs.
    """
    runtimes = store.root / 'runtimes'
    try:
        names = [x.name for x in runtimes.iterdir() if x.is_dir() or x.is_symlink()]
    except OSError:
        return {}
    users = {name: [] for name in names}
    environments = store.root / 'environments'
    try:
        directories = [x for x in environments.iterdir() if x.is_dir()]
    except OSError:
        directories = []
    for directory in directories:
        text = ''
        for item in ('session.json', 'environment.json', 'launch-full-proton', 'launch-plugin',
                     'launch-helper', 'launch-wine'):
            try:
                text += (directory / item).read_text(errors='ignore')
            except OSError:
                pass
        for name in names:
            if name in text:
                users[name].append(directory.name)
    return users


def unused_runtimes(store):
    """Runtimes no environment refers to any more.

    A runtime outlives the last environment that used it, silently: nothing
    ever looks. It is the one kind of leftover here that is genuinely safe to
    delete, because it is provisioned by download and comes back on demand.
    """
    return sorted(name for name, users in runtime_users(store).items() if not users)


def remove_runtime(store, name):
    """Delete a provisioned runtime that nothing refers to."""
    import shutil
    if '/' in name or name in ('.', '..'):
        raise core.HostError('Not a runtime name: ' + name)
    if name not in unused_runtimes(store):
        raise core.HostError('This runtime is still used by an environment: ' + name)
    path = store.root / 'runtimes' / name
    if path.is_symlink():
        # A link to a runtime in another library, or to one that is gone. The
        # link is ours; whatever it points at is not.
        target = str(path.resolve())
        path.unlink()
        return {'runtime': name, 'freed': 0, 'unlinked': target}
    if not path.is_dir():
        raise core.HostError('No such runtime: ' + name)
    freed = measure(path)
    shutil.rmtree(path)
    return {'runtime': name, 'freed': freed, 'unlinked': None}


def nested_dependents(store, target):
    """Known parent-library runtime/launcher references into a nested library."""
    target = Path(target).resolve()
    found = set()
    roots = [store.root / 'runtimes', store.root / 'environments']
    for root in roots:
        if not root.exists():
            continue
        for entry in root.iterdir():
            candidates = [entry]
            if root.name == 'environments' and entry.is_dir() and not entry.is_symlink():
                candidates += list(entry.iterdir())
                adapter = entry / 'proton-desktop'
                if adapter.is_dir() and not adapter.is_symlink():
                    candidates += list(adapter.iterdir())
            for candidate in candidates:
                if candidate.is_symlink() and candidate.resolve().is_relative_to(target):
                    found.add(str(candidate.relative_to(store.root)))
                if candidate.name == 'session.json' and candidate.is_file():
                    try:
                        config = json.loads(candidate.read_text())
                        for key in ('proton', 'runtime_entry', 'prefix'):
                            value = config.get(key)
                            if value and Path(value).is_absolute() and Path(value).resolve().is_relative_to(target):
                                found.add(str(candidate.relative_to(store.root)) + ':' + key)
                    except (OSError, ValueError):
                        pass
    return sorted(found)


def nested_libraries(store):
    """Whole libraries kept inside this one, which no view otherwise reaches.

    Setting one up for a vendor produces a complete library — its own database,
    downloads and runtimes — nested under this one. Nothing lists them, so they
    are found by looking at the disk and wondering what that directory is,
    which is not a feature.
    """
    root = store.root / 'managed-libraries'
    found = []
    try:
        directories = sorted(x for x in root.iterdir() if x.is_dir())
    except OSError:
        return found
    for directory in directories:
        try:
            count = sum(1 for x in (directory / 'environments').iterdir() if x.is_dir())
        except OSError:
            count = 0
        found.append({'name': directory.name, 'path': str(directory), 'environments': count,
                      'required_by': nested_dependents(store, directory)})
    return found


def remove_nested_library(store, name, confirmation):
    """Delete a nested library and everything in it, on the same terms as any other.

    It holds environments, so it can hold activations, so it is not a tidier's
    decision. The phrase is the library's own name.
    """
    import shutil
    if '/' in name or name in ('.', '..'):
        raise core.HostError('Not a library name: ' + name)
    if confirmation != nested_phrase(name):
        raise core.HostError('Type the confirmation exactly to delete this library:\n  '
                             + nested_phrase(name))
    path = store.root / 'managed-libraries' / name
    if not path.is_dir():
        raise core.HostError('No such library: ' + name)
    dependents = nested_dependents(store, path)
    if dependents:
        raise core.HostError('This library is still required by: ' + ', '.join(dependents))
    freed = measure(path)
    shutil.rmtree(path)
    return {'library': name, 'freed': freed}


def nested_phrase(name):
    return 'DELETE LIBRARY ' + name.upper()


def readable(size):
    """A size a person can compare at a glance, not an exact byte count."""
    if size is None:
        return 'Not measured'
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return ('%.1f %s' % (size, unit)) if unit not in ('B', 'KB') else ('%d %s' % (size, unit))
        size /= 1024.0
    return '%d B' % size


def summarize(record):
    """The one line that says what this environment is for."""
    if record.get('dangling'):
        return 'Link to an environment that is gone'
    if record.get('name'):
        return record['name']
    if record.get('licensing_group') == 'ilok':
        return 'iLok (shared by iLok-licensed vendors)'
    if record['vendor']:
        return record['vendor']
    if record['recipe'] == 'standalone-vst3':
        return 'Directly imported plug-ins'
    if record['recipe'] and record['recipe'] != 'installer':
        return record['recipe']
    # Installed from an installer Plugg has no recipe for. What it holds says
    # what it is better than the absence of a recipe does.
    if record.get('plugin_vendors'):
        return ', '.join(record['plugin_vendors'][:3]) + (' and others' if len(record['plugin_vendors']) > 3 else '')
    if record['jobs']:
        return 'Installed from ' + record['jobs'][0]['name']
    return 'Unrecognized environment'


def licensing_line(record):
    """What this environment was set up holding, and what that implies.

    Deliberately not a claim about what is activated right now. Nothing here
    asks a vendor, and nothing should: reading PACE or a vendor's account to
    find out what is currently licensed means inspecting a licensing system,
    which this project does not do. So the note says what the environment was
    built for and leaves the present tense to the person, who may well have
    deactivated everything this morning.

    Which is what the confirmation phrase is: typing "I HAVE DEACTIVATED THIS
    ENVIRONMENT" is how you tell it, because you are the only one who knows.

    Returns None when nothing was recorded — the absence of a note is not a
    status and does not belong on a row.
    """
    if record['protected'] is None:
        return 'Licensing note unreadable — treat this as holding activations'
    if not record['protected']:
        return None
    products = ', '.join(record['products']) or 'recorded products'
    # Where matters as much as whether. One vendor means its website, another
    # the iLok manager, another uninstalling through its own helper, and
    # "deactivate first" is not advice anyone can act on without it.
    venues = record.get('deactivate_at') or []
    where = ' or '.join(venues) if venues else 'wherever they were activated'
    # An environment that gained a plug-in after it was recorded has an answer
    # for some of what is in it and none for the rest, which is worth saying
    # rather than reporting the strictest of an incomplete list as if it were
    # the whole picture.
    unanswered = [name for name in record['plugins'] if name not in set(record['products'])]
    trailer = ('' if not unanswered else
               ' · %d not yet recorded: %s' % (len(unanswered), ', '.join(unanswered[:3])))
    return {
        'unlicensed': 'Nothing here needs activating — ' + products + trailer,
        'reactivatable': 'Set up for ' + products + '; their serials can be entered again' + trailer,
        'deactivate-first': 'Set up for ' + products + '; deactivate ' + where
                            + ' before rebuilding, if you have not already' + trailer,
        'limited-activations': 'Set up for ' + products + '; each rebuild can spend one of a '
                               'limited number of activations' + trailer,
        'unknown': 'Set up for ' + products + '; unclassified, so treated as unrepeatable' + trailer,
    }.get(record['severity'], products)


def recorded_detail(record):
    """Each product and how its licence behaves, for the row's tooltip.

    The single line says the strictest case, which is what a decision turns
    on. It is not what was recorded, and in a grab-bag environment those are
    not the same thing at all.
    """
    entries = record.get('recorded') or []
    if not entries:
        return None
    lines = []
    for item in entries:
        described = {'unlicensed': 'needs no activation',
                     'reactivatable': 'serial can be entered again',
                     'deactivate-first': 'deactivate before rebuilding',
                     'limited-activations': 'a fixed number of activations',
                     'unknown': 'not known, treated as unrepeatable'}.get(item.get('recovery'),
                                                                         item.get('recovery'))
        line = '%s — %s' % (item.get('name'), described)
        if item.get('activations_remaining') is not None:
            line += ' (%d left)' % item['activations_remaining']
        if item.get('deactivate_at'):
            line += '; at ' + item['deactivate_at']
        lines.append(line)
    return '\n'.join(lines)


def identity_summary(records):
    """Say once, for the library, what per-row would be noise on every row.

    An environment built before this app gave every prefix this computer's
    identity presents one of its own. That is a real thing to know — it is why
    a vendor may think you own several machines — but it is not a warning and
    it is not actionable: those environments are left exactly as they are on
    purpose, because their licences were issued to the identity they have.

    Per row, in a warning colour, on nearly every row, it taught the reader to
    ignore the colour. It belongs here, once, as a fact about the library.
    """
    distinct = [r for r in records if r.get('identity_is_this_computer') is False]
    if not distinct:
        return None
    return ('%d of these were built before environments were given this computer\'s identity, so '
            'each presents one of its own and a vendor may count it as a separate machine. They '
            'are left that way deliberately: their licences were issued to the identity they '
            'have, and rewriting it now is what would lose them. Anything built from now on '
            'shares one identity.' % len(distinct))
