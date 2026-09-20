"""Pinned vendor service installation; callers own fresh-prefix/job locks."""
import json
import os
from pathlib import Path
import subprocess
import time
from . import core, licensing, native_access, vendors, proton_session

SPEC = {
    'installer': 'Program Files/Native Instruments/Native Access/resources/daemon/win/NTKDaemon 1.32.0 Setup PC.exe',
    'sha256': '5f2199f4e1409d6eea5edaea9c4a8af31e8ee8ac3790851aa44d33e87a46b218',
    'executable': 'Program Files/Common Files/Native Instruments/NTK/NTKDaemon.exe',
    'service': 'NTKDaemonService',
}


def require_available(directory):
    """NTK uses host-local sockets, which separate Wine prefixes do not isolate."""
    owned = set(proton_session.foreign_prefix_processes(Path(directory) / 'prefix'))
    for process in Path('/proc').iterdir():
        if not process.name.isdigit() or int(process.name) in owned:
            continue
        try:
            name = (process / 'comm').read_text().strip().casefold()
        except OSError:
            continue
        if name == 'ntkdaemon.exe':
            raise core.HostError('Close Native Access in the other environment before continuing. Its background service uses the same local network address.')


def inside(directory, relative):
    drive = (Path(directory) / 'prefix/drive_c').resolve()
    path = drive / relative
    if not path.resolve().is_relative_to(drive):
        raise core.HostError('Native Access service path escapes its environment.')
    return path


def installed(directory):
    binary = inside(directory, SPEC['executable'])
    record = inside(directory, 'users/Public/Documents/Native Instruments/NTK/install.json')
    try:
        expected = 'C:\\' + SPEC['executable'].replace('/', '\\')
        return binary.is_file() and json.loads(record.read_text()).get('path') == expected
    except (OSError, ValueError):
        return False


def install(directory, launcher, report, check, timeout=600):
    directory = Path(directory)
    licensing.guard(directory, 'install_component')
    require_available(directory)
    installer = inside(directory, SPEC['installer'])
    if not installer.is_file() or core.digest(installer) != SPEC['sha256']:
        raise core.HostError('Bundled NTKDaemon installer does not match the reviewed version.')
    report('Installing Native Instruments background service…')
    child = subprocess.Popen([str(launcher), str(installer), '/S'], env=os.environ.copy(),
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + timeout
    settled = 0
    stopped = False
    try:
        while child.poll() is None:
            check()
            if time.monotonic() >= deadline:
                raise core.HostError('NTKDaemon installer timed out; inspect this setup before retrying.')
            programs = vendors.running_programs(directory / 'prefix')
            # The vendor installer leaves its service running, which keeps UMU alive.
            # Require an installed payload and three observations with no installer or
            # other application before asking the scoped lifecycle adapter to stop it.
            quiet = installed(directory) and all(name.lower() in native_access.BACKGROUND for _, name in programs)
            settled = settled + 1 if quiet else 0
            if settled >= 3:
                native_access.prepare_runtime(directory)
                child.wait(timeout=20)
                stopped = True
                break
            time.sleep(1)
        if (child.returncode and not stopped) or not installed(directory):
            raise core.HostError('NTKDaemon installation did not complete successfully.')
        check()
        core.atomic_json(directory / 'ntk-component.json', {
            'schema': 1, **SPEC, 'installed_sha256': core.digest(inside(directory, SPEC['executable']))})
    except Exception:
        # Do not kill unknown applications or disguise failure as a usable setup.
        if child.poll() is None:
            child.terminate()
        raise


def configure_launcher(directory):
    directory = Path(directory)
    licensing.guard(directory, 'install_component')
    marker = directory / 'ntk-component.json'
    if not marker.exists():
        return
    data = json.loads(marker.read_text())
    if any(data.get(key) != value for key, value in SPEC.items()) or not installed(directory):
        raise core.HostError('Native Access service installation needs inspection.')
    batch = inside(directory, 'Plugg/launch-helper.cmd')
    batch.write_text('@echo off\nset "SteamAppId="\nsc.exe start NTKDaemonService\n'
                     'if errorlevel 1 exit /b %errorlevel%\n'
                     '"C:\\Program Files\\Native Instruments\\Native Access\\Native Access.exe"\n')
