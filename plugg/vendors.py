"""Vendor Helper lifecycle and installed-product discovery.
SPDX-License-Identifier: GPL-3.0-or-later
"""
import json
import contextlib
import fcntl
import os
from pathlib import Path
import subprocess
import shutil
import re
import sys
import time

from . import core
from .proton_session import foreign_prefix_processes

ROOTS = ('Program Files/Common Files/VST3',)
#: Where vendors' own apps put each format. VST2 has no standard folder, so
#: these are the ones installers and managers commonly default to.
FORMAT_ROOTS = {
    'vst3': ROOTS,
    'clap': ('Program Files/Common Files/CLAP',),
    'vst2': ('Program Files/Common Files/VST2', 'Program Files/Common Files/Steinberg/VST2',
             'Program Files/VSTPlugins', 'Program Files/Steinberg/VSTPlugins',
             'Program Files/Native Instruments/VSTPlugins 64 bit'),
}
# Wine's and Proton's own background programs. tabtip.exe (the on-screen
# keyboard helper) and xalia.exe (Proton's accessibility helper) start on
# their own and linger; treating them as open applications blocked every
# vendor-manager handoff, so nothing was scanned after a manager closed.
SERVICES = {'services.exe', 'explorer.exe', 'winedevice.exe', 'plugplay.exe', 'rpcss.exe', 'svchost.exe', 'conhost.exe',
            'tabtip.exe', 'xalia.exe'}



SUFFIXES = (', inc.', ', inc', ' inc.', ' inc', ' gmbh', ' ltd.', ' ltd', ' llc', ' ab', ' oy', ' s.r.l.', ' bv')

def vendor_name(raw):
    """The vendor as a person would write it, from a plug-in's own metadata.

    Plug-ins name their maker inconsistently ("Universal Audio, Inc.",
    "Native Instruments GmbH"). Dropping the company form is enough to put
    one vendor's plug-ins on one row, without a table someone has to keep.
    """
    name = ' '.join((raw or '').split())
    lowered = name.casefold()
    for suffix in SUFFIXES:
        if lowered.endswith(suffix):
            name = name[:-len(suffix)].rstrip(' ,')
            break
    return name or 'Unknown vendor'

def configuration(store, job_id):
    job = store.job(job_id)
    directory = store.root / 'environments' / job['env_id']
    path = directory / 'environment.json'
    cfg = json.loads(path.read_text()) if path.exists() else {}
    if cfg.get('recipe') not in ('klevgrand', 'native-instruments-experiment', 'pace-service-experiment', 'plugin-alliance-experiment', 'managed-helper') or not cfg.get('helper_launcher'):
        raise core.HostError('No supported vendor Helper is configured for this installation.')
    return directory, cfg


def cards(store):
    """Vendor cards for the installations this library is still offering.

    An archived installation is retired: its card is gone from the library, and
    it no longer holds the vendor's slot. Without that, archiving a finished
    attempt hid it from view while still refusing a fresh install of the same
    vendor, with an error pointing at a card the user could no longer see.

    But retired has to mean retired. An archived installation whose environment
    is still publishing plug-ins keeps its card, because those plug-ins are in
    somebody's DAW right now and the manager they came from is the only way to
    deactivate or uninstall them.
    """
    from .proton_session import prefix_processes
    result = []
    try:
        scan = prefix_processes()
    except OSError:
        scan = {}
    # Archiving means "this installation is finished with". An environment
    # still serving plug-ins to a DAW is not finished with, and hiding its
    # helper leaves no way to open the manager those plug-ins came from.
    publishing = {p['env_id'] for p in store.plugins() if p['status'] != 'removed'}
    for job in store.jobs():
        if job.get('archived') and job['env_id'] not in publishing:
            continue
        try:
            directory, cfg = configuration(store, job['id'])
        except (core.HostError, OSError, ValueError):
            continue
        if cfg.get('helper_job') and cfg['helper_job'] != job['id']:
            continue
        path = directory / 'helper-state.json'
        try:
            prefix = (directory / 'prefix').resolve()
        except OSError:
            prefix = directory / 'prefix'
        running = program_names(prefix, scan.get(prefix, []))
        unreadable = False
        try:
            with path.open('rb') as source:
                raw = source.read(64 * 1024 + 1)
            if len(raw) > 64 * 1024:
                raise ValueError('Helper status exceeds its size limit')
            state = json.loads(raw)
            if not isinstance(state, dict) or any(
                    key in state and not isinstance(state[key], str) for key in ('status', 'message')):
                raise ValueError('Invalid helper status fields')
        except FileNotFoundError:
            state = {}
        except (OSError, ValueError):
            unreadable = True
            state = {'status': 'needs_attention', 'message': 'Helper status could not be read. Close any remaining helper window, then refresh the library.'}
        busy = unreadable or state.get('status') in ('opening', 'running', 'settling', 'scanning')
        if busy:
            busy = False
            try:
                # Read an existing lock only. Rendering cards must not create
                # operation files or trust a PID that another process can reuse.
                with (directory / 'helper.lock').open('r') as held:
                    try:
                        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        busy = True
            except OSError:
                pass
            if not busy and not unreadable:
                # Say what is true and what can be done about it. Some vendor
                # cards have no refresh button, so "refresh the library" would
                # be advice the interface cannot carry out.
                state = {'status': 'needs_attention',
                         'message': ('This status was left behind by an operation that did not '
                                     'finish, but the programs below are still running. Open the '
                                     'application to finish there, or use Force close.') if running
                                    else ('This status was left behind by an operation that did '
                                          'not finish. Nothing is running now. Use Force close on '
                                          'this card, or run "plugg helper-reset '
                                          + job['id'] + '".')}
        result.append({'job': job['id'], 'name': cfg.get('display_name', 'Klevgrand'),
                       'vendor': cfg.get('vendor'), 'busy': busy, 'running': running,
                       'needs_attention': state.get('status') == 'needs_attention' or (not state.get('status') and job.get('status') in ('failed', 'needs_attention')),
                       'message': state.get('message') or (job.get('message') if job.get('status') in ('failed', 'needs_attention') else None) or 'Install products through Helper, then close it to refresh your library.',
                       'installer': job['installer'], 'recipe': cfg['recipe'], 'helper_profile': cfg.get('helper_profile'),
                       'can_refresh': cfg['recipe'] in ('klevgrand', 'plugin-alliance-experiment', 'managed-helper'), 'has_ilok': bool(cfg.get('ilok_launcher')),
                       'managers': list(managers(directory)) if cfg.get('licensing_group') == 'ilok' else [],
                       'licensing_group': cfg.get('licensing_group')})
    return result


def stop_helper(store, job_id, settle=25.0):
    """End every Windows program running in one environment.

    Closing a window is not closing a program. Electron helpers and several
    installers keep running with no window at all, so the library waits for an
    exit that never comes and the card offers nothing that can end it. Acting on
    "the window went away" would be guessing — an installer with no window may
    still be working — so this is deliberate: the person asking is the signal.

    The unit here is the environment, not the application. Products that share a
    prefix with a licence manager are ended together, because they share one
    Wine server and there is no way to end one and leave the other.

    Refuses while a DAW is open, because ending the environment ends any plug-in
    it is hosting, and never stops a server belonging to another runtime.
    """
    from .ua_connect import require_idle_desktop
    from .proton_session import foreign_prefix_processes, stop_idle_session
    directory, _ = configuration(store, job_id)
    prefix = directory / 'prefix'
    stopped = program_names(prefix)
    if stopped:
        require_idle_desktop()
        session = json.loads((directory / 'session.json').read_text())
        expected = (Path(session['proton']).parent / 'files/bin/wineserver').resolve()
        servers = []
        for pid in foreign_prefix_processes(prefix):
            try:
                executable = (Path('/proc') / str(pid) / 'exe').resolve(strict=True)
            except OSError:
                continue
            if executable.name.startswith('wineserver'):
                if executable != expected:
                    raise core.HostError('A different Wine runtime is using this environment; '
                                         'stop it where it was started.')
                servers.append(pid)
        if servers:
            environment = dict(os.environ, WINEPREFIX=str(prefix))
            subprocess.run([str(expected), '-k'], env=environment, check=True, timeout=30,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(150):
            if not applications(prefix):
                break
            time.sleep(0.1)
        else:
            raise core.HostError('Some Windows programs are still running in this environment: '
                                 + ', '.join(program_names(prefix)[:3]))
        stop_idle_session(directory / 'session.json')
    settled = settle_helper_state(directory, settle)
    return {'job': job_id, 'stopped': stopped, 'settled': settled is not None,
            'state': (settled or {}).get('cleared')}


#: The title each vendor application actually gives its window. Focusing an
#: existing window matches on this, so a friendly card heading will not do.
WINDOW_TITLES = {'pace-service-experiment': 'UA Connect',
                 'plugin-alliance-experiment': 'Plugin Alliance Installation Manager V1.4.0',
                 'native-instruments-experiment': 'Native Access',
                 'klevgrand': 'Klevgrand Helper'}


def show_helper(store, job_id, *, ilok=False, wait=8.0):
    """Try to bring back the window of an application that is already running.

    A window that was only hidden or minimized comes back: the compositor still
    has it, and focusing it is certain. A window that was *closed* may be gone
    for good — closing an Electron window destroys it, and whether the program
    can make another one is the vendor's decision, not ours. So this asks, then
    checks whether a window actually appeared, and says which happened. The one
    thing it must not do is claim success and leave someone staring at a desktop
    where nothing opened.

    It starts nothing new: an application that is not running is a job for the
    card's own Open button, which sets the environment up first.
    """
    directory, cfg = configuration(store, job_id)
    prefix = directory / 'prefix'
    if not applications(prefix):
        raise core.HostError('Nothing is running in this environment now. Use the card\'s '
                             'Open button to start it.')
    launcher = cfg.get('ilok_launcher') if ilok else cfg.get('helper_launcher')
    if not launcher:
        raise core.HostError('This environment has no application to open.')
    title = ('iLok License Manager' if ilok
             else WINDOW_TITLES.get(cfg['recipe']) or cfg.get('display_name') or 'Helper')
    if visible_window(prefix, title):
        return {'job': job_id, 'title': title, 'restored': True, 'focused': True}
    open_native_access(prefix, launcher, title=title)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if visible_window(prefix, title):
            return {'job': job_id, 'title': title, 'restored': True, 'focused': False}
        time.sleep(0.5)
    return {'job': job_id, 'title': title, 'restored': False, 'focused': False}


def settle_helper_state(directory, timeout=25.0):
    """Clear the leftover status once whatever held the lock has let go.

    A lock still held at this point is not a helper to close — the programs
    have just been ended — it is the worker that was watching them, on its way
    out. It needs a moment, and it writes its own final status on the way, so
    waiting briefly and then leaving it alone is the honest answer.

    What must not happen is what happened before: the kill succeeds, the status
    file cannot be cleared in the same instant, and the whole operation reports
    failure for work it had already done. That teaches people to press the
    button again, which is the one thing this must never need.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            return clear_helper_state(directory)
        except BlockingIOError:
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.5)


def clear_helper_state(directory):
    """Remove the status file while holding the lock, or raise BlockingIOError.

    Holding the lock across the removal means no owner is part-way through
    writing the file it is being removed from.
    """
    path = directory / 'helper-state.json'
    try:
        handle = (directory / 'helper.lock').open('r')
    except OSError:
        handle = None
    try:
        if handle is not None:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            previous = json.loads(path.read_text())
        except (OSError, ValueError):
            previous = {}
        path.unlink(missing_ok=True)
        return {'cleared': previous.get('status'), 'message': previous.get('message')}
    finally:
        if handle is not None:
            handle.close()


def reset_helper_state(store, job_id):
    """Clear a helper status that outlived the process which wrote it.

    The status file says a vendor application is open; the process that would
    have cleared it is gone. Until it is cleared the card claims the helper is
    open, its buttons stay disabled, and for a vendor whose card has no refresh
    there is no way out from the interface at all.

    This refuses while the environment's helper lock is actually held, so a
    genuinely running helper is never declared finished from underneath itself.
    """
    directory, _ = configuration(store, job_id)
    try:
        return {'job': job_id, **clear_helper_state(directory)}
    except BlockingIOError:
        raise core.HostError('An operation in this environment has not finished. Wait for it, '
                             'or use Force close on the card to end the programs running '
                             'there.') from None


def running_programs(prefix, pids=None):
    """(pid, name) for the Windows programs in a prefix, ignoring Wine's own services."""
    found = []
    for pid in (foreign_prefix_processes(prefix) if pids is None else pids):
        try:
            args = (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0')
            name = os.fsdecode(args[0]).replace('\\', '/').rsplit('/', 1)[-1]
            if name.lower().endswith(('.exe', '.exe.so')) and name.lower() not in SERVICES:
                found.append((pid, name))
        except OSError:
            pass
    return found


def program_names(prefix, pids=None):
    """What a person would recognise in a list of what is about to be ended."""
    return sorted({name for _, name in running_programs(prefix, pids)})


def applications(prefix):
    """Ignore Wine infrastructure; conservatively wait for other Windows apps."""
    return [pid for pid, _ in running_programs(prefix)]


@contextlib.contextmanager
def helper_placement(title="Klevgrand Helper"):
    """Install a temporary initial-placement rule before Wine creates the UI."""
    if not os.environ.get('HYPRLAND_INSTANCE_SIGNATURE') or not shutil.which('hyprctl'):
        yield
        return
    if title not in ('Klevgrand Helper', 'UA Connect', 'Native Access', 'Softube Central'):
        raise core.HostError('Unsupported helper window title')
    key = {'UA Connect':'ua_connect','Klevgrand Helper':'klevgrand','Native Access':'native_access','Softube Central':'softube_central'}[title]
    handle = 'plugg_' + key + '_rule'
    enable = (f'if {handle} then {handle}:set_enabled(true) else '
              f'{handle}=hl.window_rule({{name="plugg-{key}-helper",'
              f'match={{class="^steam_proton$",title="^{title}$"}},'
              'float=true,persistent_size=false,fullscreen_state=0}) end')
    disable = f'if {handle} then {handle}:set_enabled(false) end'
    try:
        result = subprocess.run(['hyprctl', 'eval', enable], capture_output=True, text=True, timeout=3, check=True)
        if result.stdout.strip() != 'ok':
            raise core.HostError('Could not prepare the Helper window placement on this Hyprland version.')
        yield
    finally:
        # Best effort on compositor shutdown/reload. No config files are edited.
        try:
            subprocess.run(['hyprctl', 'eval', disable], capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.SubprocessError):
            pass


def float_helper(prefix, handled):
    """Apply the tested Lua Hyprland workaround once per managed Helper window.

    Preserve its natural size; do not alter persistent compositor rules or keep
    overriding window placement chosen by the user after initial presentation.
    """
    if not os.environ.get('HYPRLAND_INSTANCE_SIGNATURE') or not shutil.which('hyprctl'):
        return
    try:
        result = subprocess.run(['hyprctl', '-j', 'clients'], capture_output=True, text=True, timeout=2, check=True)
        windows = json.loads(result.stdout)
        pids = None
        for window in windows:
            identity = (window.get('address'), window.get('pid'))
            if identity in handled or window.get('title') != 'Klevgrand Helper' or window.get('class') != 'steam_proton':
                continue
            address = window.get('address', '')
            if not re.fullmatch(r'0x[0-9a-fA-F]+', address):
                continue
            if pids is None:
                pids = set(foreign_prefix_processes(prefix))
            if window.get('pid') not in pids:
                continue
            if not window.get('floating'):
                expression = 'hl.dsp.window.float({action="enable",window="address:' + address + '"})'
                response = subprocess.run(['hyprctl', 'dispatch', expression], capture_output=True, text=True, timeout=2, check=True)
                if response.stdout.strip() != 'ok':
                    return 'Float the Helper window if its controls are stretched or unresponsive.'
            handled.add(identity)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 'Float the Helper window if its controls are stretched or unresponsive.'


def installed(prefix, kinds=None):
    """Plug-ins in the standard install folders, never the Helper download cache.

    kinds limits the formats; by default every format is listed, which is what
    a before-and-after snapshot wants. 32-bit CLAP files are left out, as
    discover() does; 32-bit VST2 files are listed, and core.hostable() decides.
    """
    from . import formats
    kinds = formats.FORMATS if kinds is None else kinds
    drive = (prefix / 'drive_c').resolve()
    result = []
    seen = set()
    for kind in kinds:
        for relative in FORMAT_ROOTS[kind]:
            root = drive / relative
            if not root.exists():
                continue
            if root.is_symlink() or not root.resolve().is_relative_to(drive):
                raise core.HostError('The installed ' + formats.LABELS[kind] + ' directory is outside this environment.')
            # discover expects a drive_c child; use its bounded walker directly here.
            for parent, dirs, files in os.walk(root, followlinks=False):
                dirs[:] = [d for d in dirs if not (Path(parent) / d).is_symlink()]
                for name in files:
                    path = Path(parent) / name
                    if path.is_symlink() or path in seen or formats.module_format(path) != kind:
                        continue
                    try:
                        arch = core.pe_machine(path)
                    except core.HostError:
                        continue
                    if kind == 'clap' and arch != 0x8664 or kind == 'vst2' and arch not in (0x8664, 0x14C):
                        continue
                    seen.add(path)
                    result.append({'path': path, 'name': path.stem, 'machine': arch, 'hash': core.digest(path),
                                   'format': kind})
    return sorted(result, key=lambda x: str(x['path']))


def refresh_library(store, job_id, *, probe_only=None):
    """Publish what is installed and not yet published.

    probe_only, when given, is the set of module paths an installation just
    added or changed. Only those are loaded; anything else still unpublished
    is reported as waiting rather than loaded again. Loading an unactivated
    licensed plug-in makes it ask for activation, so retrying every waiting
    plug-in after each install would stack one activation window per product.
    """
    from . import formats
    configuration(store, job_id)
    items = core.hostable(store, installed(store.prefix(job_id), formats.enabled(store.root)))
    existing = {}
    for plugin in store.plugins():
        if plugin['status'] == 'removed' or not plugin['publication']:
            continue
        kind = formats.of(plugin['metadata'])
        module = formats.windows_link(Path(plugin['publication']), kind)
        existing[(module.resolve(), kind)] = plugin
    added = 0
    unchanged = 0
    # Updated by the vendor's own app. The DAW's adapter links to the module
    # file, so it already loads the new version; Plugg does not re-check it yet.
    updated = []
    failures = []
    waiting = []
    skipped = core.kept_out(store)
    for item in items:
        if core.plugin_identity(job_id, item['path']) in skipped:
            # Taken out of the DAW on purpose: not loaded, not counted.
            continue
        previous = existing.get((item['path'].resolve(), item['format']))
        if previous:
            if previous['hash'] == item['hash']:
                unchanged += 1
            else:
                updated.append(item['name'])
            continue
        if probe_only is not None and str(item['path']) not in probe_only:
            waiting.append(item['name'])
            continue
        try:
            if item['machine'] != 0x8664 and item['format'] != 'vst2':
                raise core.HostError('32-bit VST3 plug-ins are not supported.')
            metadata = core.probe(store, item['path'], job_id, item['format'])
            if core.digest(item['path']) != item['hash']:
                raise core.HostError('Installation is still changing. Close the Helper and refresh again.')
            if core.duplicate_32_bit(store, item, metadata):
                continue
            core.publish(store, item, job_id, metadata)
            added += 1
        except (core.HostError, OSError, ValueError) as exc:
            failures.append(item['name'] + ': ' + str(exc))
    removed = retire_uninstalled(store, job_id)
    result = {'added': added, 'unchanged': unchanged, 'updated': updated, 'removed': removed, 'failures': failures,
              'waiting': waiting}
    core.atomic_json(store.root / 'jobs' / job_id / 'vendor-scan-result.json', result)
    return result


def retire_uninstalled(store, job_id):
    """Stop offering plug-ins the vendor's own uninstaller has removed.

    A refresh that only ever adds leaves the library asserting that a product
    the user deliberately uninstalled is still available: it stays in the list,
    its publication dangles, and it goes on blocking a later reinstall. A
    product is retired only when its module is genuinely gone from a prefix we
    can read, so an unreadable environment never mass-retires a vendor.
    """
    prefix = store.prefix(job_id)
    if not prefix.is_dir():
        return []
    gone = []
    for plugin in store.plugins():
        if plugin['env_id'] != job_id or plugin['status'] == 'removed':
            continue
        module = Path(plugin['module'])
        if module.exists():
            continue
        try:
            core.forget_plugin(store, plugin['id'])
            gone.append(plugin['name'])
        except (core.HostError, OSError):
            # A publication we do not own is left alone; it is reported, not forced.
            continue
    return gone


def finish_installation(store, job_id, *, busy=None, before_scan=None, after_scan=None, probe_only=None):
    """Shared installer completion: settle, discover, validate and publish.

    Call after the installer/helper has exited. Runtime-specific adapters may
    supply an idle check and cleanup around probing; this function never picks
    a runtime, installs dependencies, or replaces existing publications.
    The caller owns the environment's helper/job locks.
    """
    from . import formats
    directory, _ = configuration(store, job_id)
    busy = busy or applications
    def report(status, message):
        core.atomic_json(directory / 'helper-state.json', {
            'status': status, 'message': message, 'pid': os.getpid(), 'updated': time.time()})
    report('settling', 'Waiting for installation to finish…')
    last = None
    quiet_since = None
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        signature = [(str(x['path']), x['hash']) for x in installed(store.prefix(job_id), formats.enabled(store.root))]
        if busy(store.prefix(job_id)) or signature != last:
            quiet_since = time.monotonic()
        elif quiet_since is not None and time.monotonic() - quiet_since >= 5:
            break
        last = signature
        time.sleep(1)
    else:
        raise core.HostError('Installation has not settled. Close installer windows, then refresh the library.')
    report('scanning', 'Checking installed plug-ins…')
    # probe() checks the job cancellation flag; old cancelled runs must not
    # prevent this explicitly requested vendor operation.
    with store.db() as db:
        db.execute('UPDATE jobs SET cancel=0 WHERE id=?', (job_id,))
    if before_scan:
        before_scan()
    try:
        result = refresh_library(store, job_id, probe_only=probe_only)
    finally:
        if after_scan:
            after_scan()
    message = f"{result['added']} added to your DAW · {result['unchanged']} already there."
    if result.get('updated'):
        message += f" {len(result['updated'])} updated by the vendor's app; your DAW loads the new version."
    if result['removed']:
        message += f" {len(result['removed'])} removed."
    unchecked = len(result['failures']) + len(result['waiting'])
    if unchecked and _cfg_group(directory) == 'ilok':
        # In the iLok environment an unpublished plug-in almost always means an
        # unactivated one, and the remedy is the same for all of them at once.
        report('needs_attention', message + f" {unchecked} plug-in{'s' if unchecked != 1 else ''} not in your "
               "DAW yet, most likely because they are not activated. Activate them in iLok License Manager "
               "and close it: Plugg then checks them again and adds the ones that load.")
    elif result['failures']:
        report('needs_attention', message + ' ' + result['failures'][0])
    else:
        report('ready', message + ' Your DAW may need a rescan.')
    return result


def _cfg_group(directory):
    try:
        return json.loads((Path(directory) / 'environment.json').read_text()).get('licensing_group')
    except (OSError, ValueError):
        return None


#: Vendor managers that can be set up inside the shared iLok environment, by
#: the launcher their setup writes. Each launcher opens its manager, waits for
#: it to close and then refreshes the library itself.
ILOK_MANAGERS = (('UA Connect', 'launch-ua-connect', 'ua-connect-launch.json'),
                 ('Softube Central', 'launch-softube-central', 'softube-launch.json'))


def changed_since(prefix, before):
    """Module paths added or changed since a snapshot of installed()."""
    return {str(item['path']) for item in installed(prefix) if before.get(str(item['path'])) != item['hash']}


def snapshot(prefix):
    return {str(item['path']): item['hash'] for item in installed(prefix)}


def probe_scope(directory, before):
    """What a vendor manager's close should load.

    In the iLok environment only what that session installed or changed:
    plug-ins from other vendors still waiting for activation would otherwise
    each open an activation window. Everywhere else, everything unpublished.
    """
    if _cfg_group(directory) != 'ilok':
        return None
    return changed_since(Path(directory) / 'prefix', before)


def managers(directory):
    """The applications that can be opened in an environment, by name."""
    directory = Path(directory)
    cfg = json.loads((directory / 'environment.json').read_text())
    found = {}
    if cfg.get('ilok_launcher'):
        found['iLok License Manager'] = cfg['ilok_launcher']
    if cfg.get('licensing_group') == 'ilok':
        for name, launcher, record in ILOK_MANAGERS:
            if (directory / launcher).is_file() and (directory / record).is_file():
                found[name] = str(directory / launcher)
    return found


def open_manager(store, job_id, name):
    """Open one manager; closing it refreshes the library."""
    directory, cfg = configuration(store, job_id)
    available = managers(directory)
    if name not in available:
        raise core.HostError(name + ' is not set up in this environment. Available: ' + ', '.join(available))
    if name == 'iLok License Manager' and cfg.get('helper_launcher') == available[name]:
        return start(store, job_id)
    if applications(store.prefix(job_id)):
        raise core.HostError('Close the programs running in this environment first, including plug-ins in your DAW.')
    return subprocess.Popen([available[name]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True).pid


def start(store, job_id, refresh=False):
    directory, cfg = configuration(store, job_id)
    if cfg['recipe'] == 'plugin-alliance-experiment' and not refresh:
        from .ua_connect import require_idle_desktop
        require_idle_desktop()
        return open_native_access(store.prefix(job_id), cfg['helper_launcher'], title='Plugin Alliance Installation Manager V1.4.0')
    if cfg['recipe'] == 'pace-service-experiment':
        if refresh:
            raise core.HostError('Open UA Connect and close it after installation to refresh this library automatically.')
        from .ua_connect import require_idle_desktop
        require_idle_desktop()
        return open_native_access(store.prefix(job_id), cfg['helper_launcher'], title='UA Connect')
    if cfg['recipe'] == 'native-instruments-experiment':
        if refresh:
            raise core.HostError('Native Access discovery is not configured yet.')
        from . import native_access_routing, ntk_component
        ntk_component.require_available(directory)
        pid = open_native_access(store.prefix(job_id), cfg['helper_launcher'])
        native_access_routing.claim(directory / 'native-access-protocol.json', pid)
        return pid
    if applications(store.prefix(job_id)):
        raise core.HostError('Close this vendor’s plug-ins and Helper before managing installations.')
    args = core.plugg_command('--data', store.root, 'vendor-worker', job_id)
    if refresh:
        args.append('--refresh-only')
    # Helper output may contain authenticated download URLs. Do not persist it.
    return subprocess.Popen(args, cwd=store.root, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True).pid


def work(store, job_id, refresh=False):
    directory, cfg = configuration(store, job_id)
    if cfg.get('helper_profile') == 'native-access':
        from . import native_access
        return native_access.work(store, job_id, refresh)
    with core.lock(directory / 'helper.lock', blocking=False), core.lock(store.root / 'jobs' / job_id / 'job.lock', blocking=False):
        def report(status, message):
            core.atomic_json(directory / 'helper-state.json', {'status': status, 'message': message,
                             'pid': os.getpid(), 'updated': time.time()})
        try:
            if applications(store.prefix(job_id)):
                raise core.HostError('Close this vendor’s plug-ins and Helper before managing installations.')
            if not refresh:
                if cfg.get('helper_owns_runtime'):
                    from .proton_session import stop_idle_session
                    stop_idle_session(directory / 'session.json')
                report('opening', 'Opening Helper…')
                with helper_placement(), subprocess.Popen([cfg['helper_launcher']], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL) as child:
                    report('running', 'Helper is open. Close it when installation is finished; the library will refresh automatically.')
                    handled = set()
                    while True:
                        warning = float_helper(store.prefix(job_id), handled)
                        if warning:
                            report('running', 'Helper is open. ' + warning + ' Close Helper after installation to refresh the library.')
                        try:
                            rc = child.wait(timeout=1)
                            break
                        except subprocess.TimeoutExpired:
                            continue
                if rc:
                    raise core.HostError('Helper exited unexpectedly. Close any remaining installer windows, then refresh the library.')
            return finish_installation(store, job_id, busy=(foreign_prefix_processes
                                       if cfg.get('helper_owns_runtime') and not refresh else applications))
        except Exception as exc:
            report('needs_attention', str(exc))
            raise


def visible_window(prefix, title, pids=None):
    """The compositor's record of one application's window, if it has one."""
    if not (shutil.which('hyprctl') and os.environ.get('HYPRLAND_INSTANCE_SIGNATURE')):
        return None
    pids = set(foreign_prefix_processes(prefix) if pids is None else pids)
    try:
        result = subprocess.run(['hyprctl', '-j', 'clients'], capture_output=True, text=True, timeout=3)
        if result.returncode:
            return None
        for window in json.loads(result.stdout):
            address = window.get('address', '')
            if (window.get('pid') in pids and window.get('title') == title
                    and re.fullmatch(r'0x[0-9a-fA-F]+', address)):
                return window
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return None


def open_native_access(prefix, launcher, title="Native Access"):
    """Focus the existing NI window or request normal single-instance startup."""
    pids = set(foreign_prefix_processes(prefix))
    for pid in pids:
        try:
            first = (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0')[0]
            if b'yabridge-host' in first.lower():
                raise core.HostError('Close plug-ins in this environment before opening ' + title + '.')
        except OSError:
            pass
    window = visible_window(prefix, title, pids)
    if window:
        subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.focus({window="address:' + window['address'] + '"})'],
                       capture_output=True, timeout=3, check=True)
        return window['pid']
    return subprocess.Popen([launcher], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True).pid


def manager_products(recipe, plugins):
    """A shared licensing prefix does not make its manager own every product."""
    names = set()
    for plugin in plugins:
        metadata = json.loads(plugin['metadata'])
        for info in metadata.get('classes') or [{'name': plugin['name']}]:
            if recipe == 'pace-service-experiment':
                vendor = info.get('vendor', '').strip().casefold()
                if vendor not in {'universal audio', 'universal audio, inc.', 'universal audio (uadx)'}:
                    continue
            names.add(info.get('name') or plugin['name'])
    return sorted(names, key=str.casefold)


#: Where an installer leaves an application someone would open again.
HELPER_ROOTS = ('Program Files', 'Program Files (x86)', 'ProgramData')
#: File names that are never the vendor's manager.
NOT_HELPERS = ('unins', 'uninstall', 'crashpad', 'vcredist', 'vc_redist', 'setup-helper',
               'squirrel', 'elevate', 'dotnet', 'installerservice', 'update.exe')
#: Folders where Windows installers keep a copy of themselves for repair and
#: removal. Melodyne's setup leaves one under InstallShield, named exactly like
#: the installer, and it opened the setup again instead of any app.
NOT_HELPER_FOLDERS = ('installshield installation information', 'package cache')
#: Words a vendor's manager app uses for itself and a product's own
#: standalone app does not: Melodyne.exe matches its installer's name, but it
#: is the product, not the way to install products.
MANAGER_WORDS = frozenset(('installer', 'installation', 'manager', 'helper', 'central', 'access', 'connect',
                           'hub', 'portal', 'center', 'centre', 'downloader', 'assistant'))


def helper_candidates(directory, limit=40):
    """Programs in an environment that could be its vendor's manager, as paths under C:.

    For an installer Plugg has no recipe for: the vendor's app (Kilohearts
    Installer, for one) stays behind in the environment, and nothing knew to
    offer a way to open it again.
    """
    drive = (Path(directory) / 'prefix' / 'drive_c').resolve()
    found = []
    for root in HELPER_ROOTS:
        base = drive / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob('*.exe')):
            relative = path.relative_to(drive)
            parts = [part.lower() for part in relative.parts]
            if len(parts) > 5 or 'common files' in parts or NOT_HELPER_FOLDERS[0] in parts \
                    or NOT_HELPER_FOLDERS[1] in parts or parts[1:2] in (['internet explorer'], ['windows media player'],
                                                                              ['windows nt'], ['microsoft'], ['powershell']):
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(drive):
                continue
            if any(word in path.name.lower() for word in NOT_HELPERS):
                continue
            found.append(relative.as_posix())
            if len(found) >= limit:
                return found
    return found


def program_key(name):
    """A program's name without its version, tags or punctuation.

    The installer's file name is rarely the app's: PA-InstallationManager-v1.4.0
    installs PA-InstallationManager.exe, and Kilohearts Installer [BC_token]
    installs Kilohearts Installer.exe.
    """
    name = re.sub(r'\s*[\[(].*$', '', name or '')
    name = re.sub(r'[\s._-]*v?\d+(?:[._]\d+)+\w*$', '', name, flags=re.IGNORECASE)
    return re.sub(r'[\W_]+', '', name).casefold()


def _words(text):
    """Words in a name, splitting InstallationManager as well as Installation Manager."""
    return {w.casefold() for w in re.findall(r'[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+', text or '')}


def uninstall_entries(directory):
    """What installers registered under Windows' Uninstall key, as dictionaries of its values."""
    from . import licensing
    registry = Path(directory) / 'prefix' / 'system.reg'
    if not registry.is_file() or registry.stat().st_size > licensing.MAX_REGISTRY_BYTES:
        return []
    entries, current = [], None
    wanted = {'displayname', 'displayicon', 'installlocation', 'installsource'}
    with registry.open('r', encoding='utf-8', errors='replace') as stream:
        for line in stream:
            if line.startswith('['):
                section = line[1:line.find(']')].replace('\\\\', '\\').casefold()
                current = {} if '\\currentversion\\uninstall\\' in section else None
                if current is not None:
                    entries.append(current)
                continue
            match = licensing.VALUE.match(line.rstrip('\n')) if current is not None else None
            if match and licensing._unescape(match.group(1)).casefold() in wanted:
                current[licensing._unescape(match.group(1)).casefold()] = licensing._normalize(match.group(2))
    return entries


def _drive_path(value):
    """C:\\Program Files\\X\\ as program files/x, for comparing with a candidate; None elsewhere."""
    value = (value or '').strip().strip('"').split(',')[0].replace('\\', '/').casefold()
    return value[3:].rstrip('/') if value.startswith('c:/') else None


def installer_apps(store, job):
    """The vendor app an installer left behind, if that is certain, and every program it could be.

    Returns (certain, candidates). certain holds the one program Plugg may
    adopt without asking; it is empty when nothing, or more than one thing,
    qualifies. A program qualifies when it is the installer itself, copied
    into the environment (Kilohearts and XLN do this), or when it calls itself
    a manager and its name agrees with the installer's: the installer's file
    name or product name, or the entry the installer registered for removal.
    """
    from . import pe_version
    directory = store.root / 'environments' / job['env_id']
    candidates = helper_candidates(directory)
    if not candidates:
        return [], []
    drive = directory / 'prefix' / 'drive_c'
    installer = Path(job.get('installer') or '')
    wanted = {program_key(installer.stem), program_key(job['name'])}
    with contextlib.suppress(Exception):
        wanted.add(program_key(pe_version.version_info(installer).get('ProductName')))
    payload = 'z:' + str(store.root / 'jobs' / job['id']).replace('/', '\\').casefold()
    registered = [entry for entry in uninstall_entries(directory)
                  if (entry.get('installsource') or '').casefold().startswith(payload)]
    wanted |= {program_key(entry.get('displayname')) for entry in registered}
    wanted.discard('')
    certain = []
    for candidate in candidates:
        path = drive / candidate
        try:
            if installer.is_file() and path.stat().st_size == installer.stat().st_size \
                    and core.digest(path) == job['hash']:
                certain.append(candidate)
                continue
            info = pe_version.version_info(path)
        except Exception:
            info = {}
        names = [Path(candidate).stem, info.get('ProductName'), info.get('FileDescription')]
        if any(program_key(n) in wanted for n in names if n) \
                and MANAGER_WORDS & set().union(*(_words(n) for n in names if n)):
            certain.append(candidate)
    return (certain if len(certain) == 1 else []), candidates


def adopt_helper(store, env_id, executable, name):
    """Make a program already in an environment its vendor manager, with a card.

    Writes only Plugg's own launch files and records. The program itself is
    the vendor's, installed by the vendor's installer; nothing is copied in.
    """
    from . import helper_component
    directory = store.root / 'environments' / env_id
    config_path = directory / 'environment.json'
    if not config_path.is_file():
        raise core.HostError('No environment ' + env_id + ' in this library.')
    full = directory / 'launch-full-proton'
    if not full.is_file() or not (directory / 'session.json').is_file():
        raise core.HostError('This environment was made on the old plain Wine setup. Install the product again so '
                             'it gets a current environment, then choose its helper there.')
    executable = str(executable).replace('\\', '/')
    if executable[:3].lower() == 'c:/':
        executable = executable[3:]
    name = ' '.join(str(name).split())
    spec = helper_component.validate({'name': name, 'executable': executable, 'archive_tools': False})
    helper_component.installed_binary(directory / 'prefix', spec)
    owners = [job for job in store.jobs() if job['env_id'] == env_id]
    if not owners:
        raise core.HostError('No installation in this library refers to this environment.')
    owner = next((job for job in owners if not job['archived']), owners[0])
    with core.lock(directory / 'helper.lock', blocking=False):
        launcher = helper_component.configure(directory / 'prefix', full, spec)
        core.atomic_json(directory / 'helper-entry.json', {'schema': 1, 'helper': spec})
        cfg = json.loads(config_path.read_text())
        makers = sorted({(item.get('vendor') or '').strip() for plugin in store.plugins()
                         if plugin['env_id'] == env_id and plugin['status'] != 'removed'
                         for item in json.loads(plugin['metadata']).get('classes', [])} - {''})
        cfg.update({'recipe': 'managed-helper', 'display_name': name,
                    'vendor': cfg.get('vendor') or (makers[0] if len(makers) == 1 else name),
                    'helper_launcher': str(launcher), 'helper_job': owner['id'], 'helper_owns_runtime': True,
                    'helper_chosen_by_user': True})
        core.atomic_json(config_path, cfg)
    try:
        scan = json.loads((store.root / 'jobs' / owner['id'] / 'scan-result.json').read_text())
    except (OSError, ValueError):
        scan = {}
    if owner['status'] == 'needs_attention' and scan.get('apps') and not scan.get('published') \
            and not scan.get('failures'):
        core.helper_installed(store, owner['id'], name)
    return {'environment': env_id, 'helper': spec, 'job': owner['id']}
