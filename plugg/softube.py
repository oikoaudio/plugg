"""Softube's helper in an existing shared PACE environment.

This configures launch only. It never installs PACE or provisions a prefix.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import os
import subprocess
import sys

from . import core, licensing, ua_connect, vendors
from .proton_session import foreign_prefix_processes

TITLE = 'Softube Central'
APP = 'Program Files/Softube Central/Softube Central.exe'
SERVICE = 'Program Files/Softube/InstallerDaemon/InstallerService.exe'
# An open licensing manager, UA Connect, installer or plug-in host blocks us.
BACKGROUND = vendors.SERVICES | {
    'mdnsresponder.exe', 'ldsvc.exe', 'xalia.exe', 'crashpad_handler.exe',
    'uahelperservice.exe', 'uacloudhelper.exe', 'installerservice.exe',
}


def configured(directory):
    directory = Path(directory)
    return all(p.is_file() for p in (
        directory / 'launch-softube-central', directory / 'softube-launch.json',
        directory / 'prefix/drive_c' / APP, directory / 'prefix/drive_c' / SERVICE))


def configure(directory):
    directory = Path(directory)
    licensing.guard(directory, 'install_component')
    for path in (directory / 'launch-full-proton', directory / 'prefix/drive_c' / APP,
                 directory / 'prefix/drive_c' / SERVICE):
        if not path.is_file():
            raise core.HostError('Missing Softube prerequisite: ' + path.name)
    batch = directory / 'prefix/drive_c/Plugg/launch-softube-central.cmd'
    batch.parent.mkdir(parents=True, exist_ok=True)
    batch.write_bytes(b'@echo off\r\nset "SteamAppId="\r\n'
                      b'sc.exe start SoftubeInstallerDaemon\r\n'
                      b'"C:\\Program Files\\Softube Central\\Softube Central.exe" --disable-gpu\r\n')
    launcher = directory / 'launch-softube-central'
    core.write_module_launcher(launcher, 'plugg.softube', directory)
    core.atomic_json(directory / 'softube-launch.json', {
        'revision': 1, 'helper': TITLE, 'licensing_group': 'ilok',
        'scope': 'Launch existing Central and its registered service; preserve PACE',
        'disable_gpu': True,
    })


def prepare(directory, *, bootstrap_pids=(), closed=False):
    allowed = BACKGROUND | ({'softube central.exe'} if closed else set())
    ua_connect.prepare_runtime(directory, bootstrap_pids=bootstrap_pids, idle_programs=allowed)


def release(directory, *, bootstrap_pids=()):
    # Called only after the owned helper window disappears, or its process exits.
    prepare(directory, bootstrap_pids=bootstrap_pids, closed=True)


#: The Softube recipe revision whose requirements an existing setup is kept up to.
RECIPE = 'plugg.softube@2'


def ensure_prerequisites(store, directory):
    """Add what the current Softube recipe requires and this environment lacks.

    A repair in place, not a reinstall: Softube Central shares the iLok
    environment, and only the missing components go in (PowerShell, the Visual
    C++ runtime its product installers expect). Each gets a recovery point
    first, and PACE and the machine identity are compared before and after.
    """
    from . import recipe_engine, shared_setups, softube_setup
    licensing.guard(directory, 'install_component')
    records = recipe_engine.catalogue([Path(__file__).resolve().parent / 'recipes' / 'community'])
    assets = shared_setups.validate(records, RECIPE)['vc_assets']
    missing_powershell = not (directory / 'prefix/drive_c/Program Files/PowerShell/7/pwsh.exe').is_file()
    missing = softube_setup.missing_runtimes(directory, assets)
    if not missing_powershell and not missing:
        return []
    def say(message):
        core.atomic_json(directory / 'helper-state.json', {
            'status': 'opening', 'manager': 'softube', 'message': message, 'pid': os.getpid()})
    added = []
    if missing_powershell:
        say('Adding PowerShell to the iLok environment before opening Softube Central…')
        softube_setup.add_powershell(store, directory, report=say)
        added.append('PowerShell')
    if missing:
        say('Adding the Visual C++ runtime Softube installers need before opening Softube Central…')
        softube_setup.add_vc_runtimes(store, directory, missing, report=say)
        added.append('Visual C++ runtime')
    return added


def run(directory):
    directory = Path(directory)
    try:
        store, job_id = ua_connect.library_context(directory)
        with core.lock(directory / 'helper.lock', blocking=False), \
             core.lock(store.root / 'jobs' / job_id / 'job.lock', blocking=False):
            try:
                if not configured(directory):
                    raise core.HostError('Softube Central launch is not configured.')
                licensing.guard(directory, 'install_helper')
                prepare(directory)
                ensure_prerequisites(store, directory)
                before = vendors.snapshot(directory / 'prefix')
                core.atomic_json(directory / 'helper-state.json', {
                    'status': 'opening', 'manager': 'softube', 'message': 'Opening Softube Central…',
                    'pid': os.getpid()})
                with vendors.helper_placement(TITLE):
                    child = subprocess.Popen([str(directory / 'launch-full-proton'), 'cmd.exe', '/c',
                                              r'C:\Plugg\launch-softube-central.cmd'],
                                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL)
                    core.atomic_json(directory / 'helper-state.json', {
                        'status': 'running', 'manager': 'softube', 'pid': os.getpid(),
                        'message': 'Softube Central is open. Close it after installation to refresh the library.'})
                    rc = ua_connect.wait_for_helper(child, directory, title=TITLE, release=release)
                if rc:
                    raise core.HostError('Softube Central exited unexpectedly.')
                release(directory, bootstrap_pids=ua_connect.descendants(child.pid))
                vendors.finish_installation(store, job_id, busy=foreign_prefix_processes,
                                            before_scan=ua_connect.require_idle_desktop,
                                            after_scan=lambda: prepare(directory),
                                            probe_only=vendors.probe_scope(directory, before))
                return 0
            except Exception as exc:
                core.atomic_json(directory / 'helper-state.json', {
                    'status': 'needs_attention', 'manager': 'softube', 'message': str(exc)})
                return 1
    except core.HostError:
        # Do not overwrite the state of a helper already holding the shared lock.
        return 1


def start(directory):
    directory = Path(directory)
    if not configured(directory):
        raise core.HostError('Softube Central launch is not configured.')
    ua_connect.require_idle_desktop()
    prefix = directory / 'prefix'
    if vendors.visible_window(prefix, TITLE, set(foreign_prefix_processes(prefix))) is None \
            and core.worker_running(directory / 'helper.lock'):
        # The launcher would find the environment taken and exit without a
        # word, so the button seemed to do nothing. Say what is going on.
        running = vendors.program_names(prefix)
        raise core.HostError('Something is still running in the iLok environment'
                             + (' (' + ', '.join(running) + ')' if running else '')
                             + ', so Softube Central cannot open. A product installer that Central '
                             'started may be waiting with no window. Use Force close on the card, '
                             'then open Softube Central again.')
    return vendors.open_native_access(prefix, str(directory / 'launch-softube-central'), title=TITLE)


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1]))
