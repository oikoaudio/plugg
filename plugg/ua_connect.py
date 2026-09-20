"""Local UA Connect compatibility launcher; independent of audio launch flags.
SPDX-License-Identifier: GPL-3.0-or-later
"""
import json
import time
import os
from pathlib import Path
import subprocess
import sys

from . import core, licensing, vendors
from .proton_session import foreign_prefix_processes, stop_idle_session


def configure(directory, *, allow_electron_no_sandbox=False):
    # Writes launchers into an existing environment, which for this vendor is
    # the one holding the user's iLok activations.
    licensing.guard(directory, 'install_component')
    directory = Path(directory)
    if not allow_electron_no_sandbox:
        raise core.HostError('UA Connect requires explicit Electron sandbox compatibility consent.')
    prefix = directory / 'prefix'
    for path in (directory / 'launch-full-proton',
                 prefix / 'drive_c/Program Files/UA Connect/UA Connect.exe',
                 prefix / 'drive_c/Plugg/Tools/Archive/tar.exe'):
        if not path.is_file():
            raise core.HostError('Missing UA Connect prerequisite: ' + path.name)
    batch = prefix / 'drive_c/Plugg/launch-ua-connect.cmd'
    batch.write_bytes(b'@echo off\r\nset "PATH=C:\\Plugg\\Tools\\Archive;%PATH%"\r\n'
                      b'"C:\\Program Files\\UA Connect\\UA Connect.exe" --disable-gpu --no-sandbox\r\n')
    core.atomic_json(directory / 'ua-connect-launch.json', {
        'revision': 1, 'electron_no_sandbox': True,
        'scope': 'UA Connect only', 'archive_path': r'C:\Plugg\Tools\Archive',
    })
    launcher = directory / 'launch-ua-connect'
    core.write_module_launcher(launcher, 'plugg.ua_connect', directory)


def require_idle_desktop():
    # Keep this prototype conservative, including zombie Windows main threads
    # whose surviving workers are not visible through the leader's cmdline.
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            first = (process / 'cmdline').read_bytes().split(b'\0')[0].lower()
        except OSError:
            continue
        if b'bitwig' in first or b'reaper' in first:
            raise core.HostError('Close your DAW before opening a vendor helper for installation or updates.')


# These services can outlive both the DAW and UA Connect. Unknown applications
# (including installers and plug-in hosts) always block the handoff.
IDLE_PROGRAMS = vendors.SERVICES | {
    'mdnsresponder.exe', 'uahelperservice.exe', 'ldsvc.exe', 'xalia.exe',
    'ua connect.exe', 'uacloudhelper.exe', 'crashpad_handler.exe',
}


def prepare_runtime(directory, *, bootstrap_pids=(), idle_programs=None):
    directory = Path(directory)
    allowed = IDLE_PROGRAMS if idle_programs is None else idle_programs
    require_idle_desktop()
    cfg = json.loads((directory / 'session.json').read_text())
    prefix = directory / 'prefix'
    for pid in vendors.applications(prefix):
        try:
            first = (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0')[0]
        except FileNotFoundError:
            continue
        name = os.fsdecode(first).replace('\\', '/').rsplit('/', 1)[-1].lower()
        if name not in allowed and not (pid in bootstrap_pids and name in ('cmd.exe', 'start.exe')):
            raise core.HostError('Close shared iLok applications and installers before managing this environment: ' + name)
    # Check the actual running Wine server, rather than guessing which runtime
    # owns this prefix. Never stop a server from another runtime or prefix.
    expected = Path(cfg['proton']).parent / 'files/bin/wineserver'
    servers = []
    for pid in foreign_prefix_processes(prefix):
        try:
            exe = (Path('/proc') / str(pid) / 'exe').resolve(strict=True)
        except OSError:
            continue
        if exe.name.startswith('wineserver'):
            if exe != expected.resolve():
                raise core.HostError('A different Wine runtime is using this environment; close it first.')
            servers.append(pid)
    if servers:
        require_idle_desktop()
        env = os.environ.copy()
        env['WINEPREFIX'] = str(prefix)
        subprocess.run([str(expected), '-k'], env=env, check=True, timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if not vendors.applications(prefix):
                break
            time.sleep(.1)
    stop_idle_session(directory / 'session.json')


def descendants(parent):
    """Identify only bootstrap processes descended from our own helper launch."""
    parents = {}
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            parents[int(path.name)] = int((path / 'stat').read_text().rsplit(')', 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            pass
    owned = {parent}
    while True:
        extra = {pid for pid, ppid in parents.items() if ppid in owned} - owned
        if not extra:
            return owned
        owned.update(extra)


def wait_for_helper(child, directory, *, title="UA Connect", release=None):
    # UA Connect's close button leaves Electron and licensing services alive.
    # On Hyprland, observe its visible windows rather than waiting forever for
    # the process. A minimized window remains a compositor client.
    if not os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):
        return child.wait()
    seen = False
    absent = 0
    while child.poll() is None:
        try:
            result = subprocess.run(['hyprctl', '-j', 'clients'], capture_output=True,
                                    text=True, timeout=3, check=True)
            pids = set(foreign_prefix_processes(Path(directory) / 'prefix'))
            windows = [w for w in json.loads(result.stdout)
                       if w.get('pid') in pids and w.get('title') == title]
            if windows:
                seen = True
                absent = 0
            elif seen:
                absent += 1
                if absent >= 3:
                    (release or prepare_runtime)(directory, bootstrap_pids=descendants(child.pid))
                    child.wait(timeout=15)
                    return 0
        except (OSError, subprocess.SubprocessError, ValueError):
            # A compositor query failure is not evidence that the user closed
            # the helper. Leave its processes alone and try again.
            pass
        time.sleep(1)
    return child.returncode


def _run(directory):
    directory = Path(directory)
    try:
        cfg = json.loads((directory / 'ua-connect-launch.json').read_text())
        if cfg.get('revision') != 1 or cfg.get('electron_no_sandbox') is not True:
            raise core.HostError('UA Connect compatibility configuration has not been approved.')
        require_idle_desktop()
        prefix = directory / 'prefix'
        prepare_runtime(directory)
        before = vendors.snapshot(prefix)
        core.atomic_json(directory / 'helper-state.json', {'status': 'opening', 'message': 'Opening UA Connect…'})
        with vendors.helper_placement('UA Connect'):
            child = subprocess.Popen([str(directory / 'launch-full-proton'), 'cmd.exe', '/c',
                                      r'C:\Plugg\launch-ua-connect.cmd'],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
            core.atomic_json(directory / 'helper-state.json', {
                'status': 'running', 'message': 'UA Connect is open. Close it when installation finishes; your library will refresh automatically.',
                'pid': os.getpid()})
            rc = wait_for_helper(child, directory)
        if rc:
            raise core.HostError('UA Connect exited unexpectedly.')
        prepare_runtime(directory)
        store, job_id = library_context(directory)
        vendors.finish_installation(store, job_id, busy=foreign_prefix_processes,
                                    before_scan=require_idle_desktop,
                                    after_scan=lambda: prepare_runtime(directory),
                                    probe_only=vendors.probe_scope(directory, before))
    except Exception as exc:
        core.atomic_json(directory / 'helper-state.json', {'status': 'needs_attention', 'message': str(exc)})
        return 1
    return 0


def library_context(directory):
    directory = Path(directory).resolve()
    cfg = json.loads((directory / 'environment.json').read_text())
    store = core.Store(directory.parent.parent)
    job_id = cfg['helper_job']
    if store.prefix(job_id).parent.resolve() != directory:
        raise core.HostError('The helper does not belong to this library environment.')
    return store, job_id


def run(directory):
    directory = Path(directory)
    # Use the same locks as the other vendor worker. A duplicate request must
    # not overwrite the running operation's state or start a second scan.
    try:
        store, job_id = library_context(directory)
        with core.lock(directory / 'helper.lock', blocking=False), \
             core.lock(store.root / 'jobs' / job_id / 'job.lock', blocking=False):
            return _run(directory)
    except core.HostError:
        return 1


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1]))
