"""Prepare reviewed Softube files for joining an existing PACE installation.

Staging never launches Windows code, provisions a prefix or installs PACE.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import os
import json
import shutil
import subprocess
import tempfile

from . import core, softube, softube_payload, vendor_payload, windows_service, licensed_setup

INSTALLER_SHA256 = '8562f9ba43404cdd16eb36130c33d4afb0ca86dac6cef4374c477c9696046b46'
INSTALLER_SIZE = 265461440
HELPER = 'resources/deps/Softube Installer Helper Installer.exe'


# Retained public name for existing setup callers.
file_manifest = vendor_payload.manifest


def stage(installer, destination):
    """Build the verified Central payload and recover its bundled service."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise core.HostError('Choose an unused Softube staging directory.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.softube-stage-', dir=destination.parent) as temp:
        root = Path(temp) / 'payload'
        root.mkdir()
        central = root / 'central'
        files = vendor_payload.unpack(installer, central, sha256=INSTALLER_SHA256, size=INSTALLER_SIZE)
        if 'Softube Central.exe' not in files or HELPER not in files:
            raise core.HostError('Softube Central payload is incomplete.')
        (root / 'InstallerService.exe').write_bytes(softube_payload.extract_service(central / HELPER))
        record = {'schema': 1, 'installer_sha256': INSTALLER_SHA256,
                  'helper_sha256': softube_payload.HELPER_SHA256,
                  'service_sha256': softube_payload.SERVICE_SHA256, 'central_files': files}
        core.atomic_json(root / 'payload.json', record)
        os.rename(root, destination)
    return record


destination_path = licensed_setup.destination_path


def compare(environment, staged):
    """Read-only adoption check: identify missing or different vendor files.

    Existing newer/self-updated helpers are never silently downgraded.
    """
    staged = Path(staged)
    expected = file_manifest(staged / 'central')
    expected[softube.SERVICE] = softube_payload.SERVICE_SHA256
    missing, different = [], []
    for name, digest in expected.items():
        relative = name if name == softube.SERVICE else 'Program Files/Softube Central/' + name
        target = destination_path(environment, relative)
        if not target.exists():
            missing.append(relative)
        elif not target.is_file() or core.digest(target) != digest:
            different.append(relative)
    return {'missing': missing, 'different': different, 'matching': len(expected) - len(missing) - len(different)}


SERVICE_SECTION = r'System\ControlSet001\Services\SoftubeInstallerDaemon'
SERVICE_IMAGE = r'"C:\Program Files\Softube\InstallerDaemon\InstallerService.exe"'


SERVICE_SPEC = windows_service.Service('SoftubeInstallerDaemon', 'Softube Installer Helper', softube.SERVICE)


def service_status(environment):
    return windows_service.status(environment, SERVICE_SPEC)


preservation_state = licensed_setup.preservation_state


def register_service(environment, timeout=90):
    if service_status(environment) == 'matching':
        return False
    return windows_service.register(environment, SERVICE_SPEC, prepare=softube.prepare, timeout=timeout)


def add_powershell(store, environment, report=print):
    """Install the shared PowerShell component, which Softube Central's installer service needs.

    PowerShell is an ordinary in-place component: it adds files and one DLL
    override and touches neither PACE nor the machine identity. A recovery
    point is still taken first, and the licensing state is compared after.
    """
    from . import licensing, powershell_component
    report('Adding Microsoft PowerShell to this environment (Softube Central needs it)')
    licensing.backup(environment, label='before-powershell')
    before = preservation_state(environment)
    powershell_component.install(store, environment, environment / 'launch-full-proton', report, lambda: None)
    if preservation_state(environment) != before:
        raise core.HostError('PACE or licensing state changed while adding PowerShell; stop and inspect this '
                             'environment. A recovery point was taken first; see plugg licensing backups.')


def missing_runtimes(environment, assets):
    """The pinned Visual C++ installers this environment has not had yet."""
    record = Path(environment) / 'dependencies.json'
    try:
        done = {item.get('sha256') for item in json.loads(record.read_text())}
    except (OSError, ValueError, AttributeError):
        done = set()
    return [asset for asset in assets if asset['sha256'] not in done]


def add_vc_runtimes(store, environment, assets, report=print):
    """Install the Visual C++ runtime Softube's product installers expect.

    Each product installer runs its own vcredist_x64.exe /quiet. Without the
    runtime already present, that step sat waiting with no window, and Central
    showed an install that never finished. The pinned Microsoft installer runs
    here instead, once, with a recovery point first and licensing checked after.
    """
    from . import licensing, vc_component
    licensing.backup(environment, label='before-vc-runtime')
    before = preservation_state(environment)
    vc_component.install(store, environment, environment / 'launch-full-proton', assets, report, lambda: None)
    if preservation_state(environment) != before:
        raise core.HostError('PACE or licensing state changed while adding the Visual C++ runtime; stop and '
                             'inspect this environment. A recovery point was taken first; see plugg licensing backups.')


def join(installer, environment, vc_assets=()):
    """Install verified vendor files into an explicit, idle shared PACE prefix.

    Never overwrite different files, recreate a prefix, or run bundled PACE.
    Failed registration retains new vendor files for a checked repeat.
    """
    from . import ua_connect, licensing
    environment = Path(environment).resolve()
    licensing.guard(environment, 'install_helper')
    store, job = ua_connect.library_context(environment)
    with core.lock(environment / 'helper.lock', blocking=False), \
         core.lock(store.root / 'jobs' / job / 'job.lock', blocking=False):
        ua_connect.require_idle_desktop()
        session = json.loads((environment / 'session.json').read_text())
        if not destination_path(environment, 'Program Files/PowerShell/7/pwsh.exe').is_file():
            add_powershell(store, environment)
        missing_vc = missing_runtimes(environment, vc_assets)
        if missing_vc:
            add_vc_runtimes(store, environment, missing_vc)
        before = preservation_state(environment)
        graphics = session.get('graphics_policy', {}).get('default', session.get('graphics_backend', 'dxvk'))
        if graphics != 'dxvk':
            raise core.HostError('Softube shared setup currently requires an existing DXVK environment.')
        if not destination_path(environment, 'Program Files/PowerShell/7/pwsh.exe').is_file():
            raise core.HostError('PowerShell is still missing after installing it; see the environment.')
        if service_status(environment) == 'different':
            raise core.HostError('Existing Softube service differs; it has not been replaced.')
        softube.prepare(environment)
        with tempfile.TemporaryDirectory(prefix='plugg-softube-join-') as temp:
            staged = Path(temp) / 'payload'
            record = stage(installer, staged)
            comparison = compare(environment, staged)
            if comparison['different']:
                raise core.HostError('Existing Softube files differ; no downgrade or replacement was made: '
                                     + ', '.join(comparison['different'][:3]))
            ua_connect.require_idle_desktop()
            softube.prepare(environment)
            if preservation_state(environment) != before:
                raise core.HostError('Shared licensing or runtime state changed during preparation.')
            try:
                for relative in comparison['missing']:
                    source = (staged / 'InstallerService.exe' if relative == softube.SERVICE else
                              staged / 'central' / relative.removeprefix('Program Files/Softube Central/'))
                    target = destination_path(environment, relative)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # Publish each file atomically and refuse overwrite on a race.
                    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as out:
                        temporary = Path(out.name)
                        with source.open('rb') as src:
                            shutil.copyfileobj(src, out)
                    try:
                        os.link(temporary, target)
                    finally:
                        temporary.unlink(missing_ok=True)
                registered = register_service(environment)
                softube.configure(environment)
            finally:
                if preservation_state(environment) != before:
                    raise core.HostError('PACE or licensing identity changed; stop and inspect this environment.')
            after = compare(environment, staged)
            if after['missing'] or after['different']:
                raise core.HostError('Softube deployment did not pass verification.')
            result = {'schema': 1, 'installer_sha256': record['installer_sha256'],
                      'service_sha256': record['service_sha256'], 'files_added': len(comparison['missing']),
                      'service_registered': registered, 'identity_preserved': True, 'pace_preserved': True}
            core.atomic_json(environment / 'softube-setup.json', result)
            return result
