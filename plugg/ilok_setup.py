"""Create the shared iLok environment from scratch, on the plugg-1 runtime.

One environment holds PACE and iLok License Manager for every iLok vendor, so
the computer is one machine to iLok. This creates it fresh: the unmodified
PACE installer, run with msiexec in a new prefix whose runtime carries the
Wine fixes that installer needs, and the computer's own machine identity set
before anything vendor-made runs.

It will not replace an iLok environment that still records activations. Tell
the old one what you deactivated first (`licensing deactivated`); the old
environment is left on disk, and archiving it is a separate, explicit step.

Vendor managers join afterwards through their own adapters (UA Connect,
Softube Central). `install` runs any other vendor's installer inside this
environment and publishes what it added.

SPDX-License-Identifier: GPL-3.0-or-later
"""
import json
import os
from pathlib import Path
import time

from . import core, helper_component, licensing, runtime_overlay

#: PACE License Support 6.0.1, as UA Connect downloads it. The only version tested.
PACE_SHA256 = '1db141190e1f06f58be6f8389b574fb4ba68c5dcc4be57ccaea90e5b33f0e6b8'
RUNTIME = 'plugg-1'
GROUPS = 'licensing-environments.json'
LDSVC = 'Program Files (x86)/Common Files/PACE/Services/LicenseServices/LDSvc.exe'
#: The Windows service LDSvc.exe runs as.
SERVICE = 'PaceLicenseDServices'
MANAGER = {'name': 'iLok License Manager', 'archive_tools': False,
           'executable': 'Program Files/iLok License Manager/iLok License Manager.exe'}
DECLARATION = {'vendor': 'iLok (PACE)', 'recovery': 'deactivate-first',
               'deactivate_at': 'in iLok License Manager',
               'note': 'Shared iLok environment. Deactivate in iLok License Manager before rebuilding or moving it.'}


def groups(store):
    path = Path(store.root) / GROUPS
    return json.loads(path.read_text()) if path.is_file() else {'schema': 1, 'groups': {}}


def current(store):
    """The environment directory the library records as its iLok environment, if any."""
    entry = groups(store).get('groups', {}).get('ilok')
    return Path(store.root) / 'environments' / entry['environment'] if entry else None


def preflight(store, installer):
    """Everything that can be checked before anything is created. Reads only."""
    installer = Path(installer).expanduser().resolve()
    if core.installer_type(installer) != 'msi':
        raise core.HostError('Choose the PACE License Support MSI.')
    if core.digest(installer) != PACE_SHA256:
        raise core.HostError('This is not the PACE installer that has been tested (PACE 6.0.1, SHA-256 '
                             + PACE_SHA256[:12] + '…). Other versions are not supported yet.')
    settings = json.loads((Path(store.root) / 'settings.json').read_text())
    if settings.get(runtime_overlay.SETTING) != RUNTIME:
        raise core.HostError('PACE needs the ' + RUNTIME + ' runtime. Run "plugg runtime assemble ' + RUNTIME
                             + '" and "plugg runtime select ' + RUNTIME + '" first.')
    runtime_overlay.verify(runtime_overlay.overlay(RUNTIME),
                           Path(store.root) / 'runtimes' / runtime_overlay.directory_name(runtime_overlay.overlay(RUNTIME)))
    previous = current(store)
    if previous is not None and previous.is_dir():
        record = licensing.read(previous)
        if record and record.get('protected'):
            held = ', '.join(item['name'] for item in record.get('products', []))
            raise core.HostError('The current iLok environment still records activations (' + held + '). '
                                 'Deactivate them in iLok License Manager, record that with '
                                 '"plugg licensing deactivated", then try again.')
        from .proton_session import foreign_prefix_processes
        if foreign_prefix_processes(previous / 'prefix'):
            raise core.HostError('Programs are still running in the current iLok environment. Close them first.')
    return {'installer': str(installer), 'runtime': RUNTIME,
            'replaces': str(previous) if previous is not None else None}


def create(store, installer, report=print, check=lambda: None):
    from . import recipes
    plan = preflight(store, installer)
    job_id = store.ingest(Path(plan['installer']))
    directory = store.root / 'environments' / store.job(job_id)['env_id']
    prefix = directory / 'prefix'
    journal = directory.parent.parent / 'jobs' / job_id / 'ilok-setup.json'

    def stage(name, **extra):
        core.atomic_json(journal, {'schema': 1, 'stage': name, 'runtime': RUNTIME, **extra})
        store.update(job_id, 'preparing' if name != 'complete' else 'ready', name.replace('-', ' ').capitalize())

    try:
        with core.lock(store.root / 'ilok-setup.lock', blocking=False), \
                core.lock(store.root / 'jobs' / job_id / 'job.lock', blocking=False):
            stage('preparing-runtime')
            runtime = recipes.provision(store, report, check)
            prefix.mkdir(parents=True)
            with core.lock(directory / 'helper.lock', blocking=False):
                stage('preparing-environment')
                full, _ = recipes.configure(store, job_id, runtime, helper_enabled=False)
                report('Setting this computer\'s machine identity')
                licensing.adopt_machine_identity(directory, [str(full)], os.environ.copy(), check, timeout=600)
                stage('installing-pace')
                report('Installing PACE License Support (a few minutes)')
                msi = 'Z:' + str(store.job(job_id)['installer']).replace('/', '\\')
                # msiexec silently skips a log in a directory that does not exist yet.
                (prefix / 'drive_c/Plugg').mkdir(parents=True, exist_ok=True)
                log = directory / 'pace-install.log'
                code = core.run_process([full, 'msiexec', '/i', msi, '/qn', '/l*v', r'C:\Plugg\pace-install.log'],
                                        os.environ.copy(), log, check, 3600)
                missing = [path for path in (LDSVC, MANAGER['executable']) if not (prefix / 'drive_c' / path).is_file()]
                if code or missing:
                    raise core.HostError('PACE did not install (msiexec exit ' + str(code) + ', missing: '
                                         + (', '.join(missing) or 'nothing') + '). The installer log is '
                                         'drive_c/Plugg/pace-install.log in ' + str(directory) + '.')
                stage('configuring')
                launcher = helper_component.configure(prefix, full, MANAGER)
                core.atomic_json(directory / 'environment.json', {
                    'id': directory.name, 'recipe': 'managed-helper', 'recipe_reference': 'plugg.ilok@1',
                    'display_name': 'iLok', 'vendor': 'PACE', 'runtime': 'UMU-Proton-10.0-4 (' + RUNTIME + ')',
                    'helper_job': job_id, 'helper_launcher': str(launcher), 'ilok_launcher': str(launcher),
                    'session_launcher': str(directory / 'launch-plugin'), 'licensing_group': 'ilok',
                    'lifecycle': 'persistent', 'helper_owns_runtime': True, 'automatic_updates': False,
                    'sandbox': False})
                licensing.protect_declared(directory, DECLARATION)
                _record_group(store, directory, plan['replaces'])
                for _ in range(60):
                    from .proton_session import foreign_prefix_processes
                    if not foreign_prefix_processes(prefix):
                        break
                    time.sleep(1)
                stage('complete', replaced=plan['replaces'])
                store.update(job_id, 'ready', 'iLok is ready. Open iLok to sign in, then add your vendors.')
    except core.Cancelled as exc:
        store.update(job_id, 'cancelled', str(exc))
        raise
    except Exception as exc:
        store.update(job_id, 'failed', str(exc))
        raise
    return {'environment': str(directory), 'job': job_id, 'runtime': RUNTIME,
            'machine_identity_is_this_computer': licensing.is_this_computer(directory),
            'replaced': plan['replaces']}


def _record_group(store, directory, replaced):
    data = groups(store)
    entries = data.setdefault('groups', {})
    history = entries.get('ilok', {}).get('previous', [])
    if replaced:
        history = [*history, {**{k: v for k, v in entries['ilok'].items() if k != 'previous'},
                              'replaced_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}]
    entries['ilok'] = {'environment': directory.name, 'prefix': str(directory / 'prefix'), 'status': 'ready',
                       'vendors': [], 'preserve_identity': True, 'runtime': RUNTIME, 'previous': history}
    data['schema'] = 1
    core.atomic_json(Path(store.root) / GROUPS, data)


def install(store, installers, vendor, check=lambda: None):
    """Run vendor installers inside the iLok environment, then publish what they added.

    Each installer runs with its own window, one after another, so its choices
    and any sign-in stay with the user. Afterwards only what they added or
    changed is loaded, so a new plug-in may ask for activation once; plug-ins
    from earlier installs that are still waiting are not loaded again.
    PACE is never replaced: if an installer brings its own and changes the
    installed one, that is reported, not undone.
    """
    from . import vendors
    directory = current(store)
    if directory is None or not directory.is_dir():
        raise core.HostError('There is no iLok environment yet. Create one with "plugg ilok create".')
    installers = [Path(item).expanduser().resolve() for item in installers]
    if not installers:
        raise core.HostError('Name at least one installer.')
    for installer in installers:
        core.installer_type(installer)
    licensing.guard(directory, 'install_component')
    cfg = json.loads((directory / 'environment.json').read_text())
    job_id = cfg['helper_job']
    prefix = directory / 'prefix'
    before_pace = _pace_files(directory)
    before = vendors.snapshot(prefix)
    results = []
    with core.lock(directory / 'helper.lock', blocking=False), \
            core.lock(store.root / 'jobs' / job_id / 'job.lock', blocking=False):
        for installer in installers:
            command = [directory / 'launch-full-proton']
            if installer.suffix.lower() == '.msi':
                command += ['msiexec', '/i', 'Z:' + str(installer).replace('/', '\\')]
            else:
                command.append(installer)
            code = core.run_process(command, os.environ.copy(), Path(os.devnull), check, 7200, cwd=installer.parent)
            results.append({'installer': installer.name, 'exit': code})
        # Only what these installers added or changed is loaded, the way a
        # Windows host would load a new plug-in: it may ask for activation once.
        # Plug-ins already waiting are left alone; closing iLok License Manager
        # checks them all again.
        scan = vendors.finish_installation(store, job_id,
                                           probe_only=vendors.changed_since(prefix, before))
    data = groups(store)
    entry = data['groups']['ilok']
    if vendor and vendor not in entry['vendors']:
        entry['vendors'] = sorted({*entry['vendors'], vendor})
        core.atomic_json(Path(store.root) / GROUPS, data)
    return {'installers': results, 'pace_changed': _pace_files(directory) != before_pace,
            'added': scan.get('added'), 'waiting_for_activation': sorted({*scan.get('waiting', []),
                                                                          *(f.split(':')[0] for f in scan.get('failures', []))}),
            'next': 'Activate in iLok License Manager (plugg ilok open), then close it to publish the rest.'
                    if scan.get('failures') or scan.get('waiting') else None}


def open_manager(store, name):
    from . import vendors
    directory = current(store)
    if directory is None or not directory.is_dir():
        raise core.HostError('There is no iLok environment yet.')
    job_id = json.loads((directory / 'environment.json').read_text())['helper_job']
    return vendors.open_manager(store, job_id, name)


def _pace_files(directory):
    from . import vendor_payload
    found = {}
    for base in ('Program Files', 'Program Files (x86)'):
        root = Path(directory) / 'prefix/drive_c' / base / 'Common Files/PACE'
        if root.is_dir():
            found.update({base + '/' + name: digest for name, digest in vendor_payload.manifest(root).items()
                          if name.lower().endswith(('.exe', '.dll'))})
    return found
