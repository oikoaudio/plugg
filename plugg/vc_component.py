"""Shared Microsoft VC installation with fixed, core-owned arguments."""
import json
import os
from pathlib import Path
from . import artifacts, core, licensing


#: How long a newly registered runtime must stay registered before the
#: installer counts as finished even though its process has not exited.
SETTLED_SECONDS = 15


class _Settled(Exception):
    pass


def registered_runtimes(directory):
    """Visual C++ redistributables the environment's registry lists as installed."""
    registry = Path(directory) / 'prefix' / 'system.reg'
    try:
        text = registry.read_text(errors='replace')
    except OSError:
        return set()
    return {line.split('=', 1)[1].strip().strip('"') for line in text.splitlines()
            if line.startswith('"DisplayName"="Microsoft Visual C++') and 'Redistributable' in line}


def stop_environment(directory):
    """End every Windows process in an environment through its own Wine server."""
    import subprocess
    session = json.loads((Path(directory) / 'session.json').read_text())
    wineserver = Path(session['proton']).parent / 'files' / 'bin' / 'wineserver'
    if wineserver.is_file():
        subprocess.run([str(wineserver), '-k'], env={**os.environ, 'WINEPREFIX': str(Path(directory) / 'prefix')},
                       timeout=30, capture_output=True)


def run_installer(directory, command, check, timeout=600):
    """Run a Visual C++ installer, and stop waiting once the runtime is registered.

    The 2015-2022 installer is a WiX Burn bundle. Under Wine it installs the
    runtime and then never exits, and so does every vendor installer that runs
    it silently in an environment that lacks the runtime: Softube's product
    installs all stalled on it. When a new redistributable has been registered
    and has stayed registered for a while, the work is done; the environment's
    Windows processes are then ended, which is what the installer should have
    done by exiting.
    """
    import time
    before = registered_runtimes(directory)
    seen = {}

    def watch():
        check()
        if not (registered_runtimes(directory) - before):
            seen.clear()
            return
        first = seen.setdefault('at', time.monotonic())
        if time.monotonic() - first >= SETTLED_SECONDS:
            raise _Settled()

    try:
        return core.run_process(command, os.environ.copy(), Path(os.devnull), watch, timeout)
    except _Settled:
        stop_environment(directory)
        return 0


def install(store, directory, full_launcher, assets, report, check):
    # Writes into an existing environment: refuse if it holds activations and
    # no longer matches the identity they were issued to.
    licensing.guard(directory, 'install_vc_runtime')
    record = Path(directory) / 'dependencies.json'
    previous = json.loads(record.read_text()) if record.exists() else []
    if not isinstance(previous, list) or not all(isinstance(item, dict) for item in previous):
        raise core.HostError('Existing dependency record needs inspection')
    installed = list(previous)
    completed = set()
    for asset in assets:
        check()
        fingerprint = asset['sha256']
        if fingerprint in completed:
            if asset not in installed:
                installed.append(asset)
            continue
        report('Installing the required Microsoft Visual C++ runtime')
        installer = artifacts.fetch(store, asset, report, check, artifacts.MICROSOFT_DOWNLOADS)
        result = run_installer(directory, [full_launcher, str(installer), '/install', '/quiet', '/norestart'], check)
        # POSIX truncates Windows ERROR_SUCCESS_REBOOT_REQUIRED (3010) to 194.
        # 1638 is "this or a newer version is already installed", which is
        # what a repeat after an interrupted run reports; 1638 & 0xff is 102.
        if result not in (0, 3010, 194, 1638, 102):
            raise core.HostError('The required Visual C++ runtime could not be installed.')
        completed.add(fingerprint)
        if asset not in installed:
            installed.append(asset)
    core.atomic_json(record, installed)
