"""UA Connect payload preparation and read-only existing-installation checks.

This module does not launch UA Connect, install PACE or mutate a live prefix.
"""
from pathlib import Path
from . import core, vendor_payload, licensed_setup, windows_service

INSTALLER_SHA256 = '1d4b1c8e6f64abba2570c76e100132b268220630ac7786c13f8a0ff8c39a55d5'
INSTALLER_SIZE = 308186200
#: Reviewed UA Connect installers, by version. Their payloads are app files
#: only; neither carries a PACE installer.
VERSIONS = {
    '1.9.6.3797': (INSTALLER_SHA256, INSTALLER_SIZE),
    '1.10.0.3844': ('cac93d13c1cbc7415db22932fb085525677f33cef3ea9df844170741087d56af', 314303768),
}


def version_of(installer):
    digest = core.digest(installer)
    for version, (sha256, _) in VERSIONS.items():
        if digest == sha256:
            return version
    raise core.HostError('This UA Connect installer has not been reviewed. Known versions: '
                         + ', '.join(VERSIONS) + '.')
APPLICATION = 'Program Files/UA Connect'
SERVICE = 'resources/native/windows/x64/uahelperservice.exe'


def stage(installer, destination):
    version = version_of(installer)
    sha256, size = VERSIONS[version]
    files = vendor_payload.unpack(installer, destination, sha256=sha256, size=size)
    if not {'UA Connect.exe', SERVICE}.issubset(files):
        raise core.HostError('UA Connect payload is incomplete.')
    if any('pace' in name.lower() or name.lower().endswith('.msi') for name in files):
        raise core.HostError('This UA Connect payload carries licensing components; it is not handled here.')
    return {'schema': 1, 'installer_sha256': sha256, 'version': version, 'files': files}


def compare(environment, staged):
    """Inspect vendor files only; never read account data or write the prefix."""
    files = vendor_payload.manifest(staged)
    if not {'UA Connect.exe', SERVICE}.issubset(files):
        raise core.HostError('UA Connect comparison requires the complete payload.')
    missing, different = [], []
    for relative, digest in files.items():
        target = licensed_setup.destination_path(environment, APPLICATION + '/' + relative)
        if not target.exists():
            missing.append(relative)
        elif not target.is_file() or core.digest(target) != digest:
            different.append(relative)
    return {'matching': len(files) - len(missing) - len(different), 'missing': missing, 'different': different}


SERVICE_SPEC = windows_service.Service('UAHelperService', 'Universal Audio Helper Service',
    APPLICATION + '/' + SERVICE, start='auto')


def service_status(environment):
    return windows_service.status(environment, SERVICE_SPEC)


def prerequisites(environment):
    """Read-only checks; a working patched runtime is required, never replaced."""
    import json
    from . import file_requirements, recipe_engine
    environment = Path(environment)
    preserved = licensed_setup.preservation_state(environment)
    cfg = json.loads((environment / 'session.json').read_text())
    record = recipe_engine.load(Path(__file__).parent / 'recipes/community/ole32-foreign-window-guard.toml')
    checks = file_requirements.verify(cfg, record['data']['required_files'])
    service = service_status(environment)
    if service == 'different':
        raise core.HostError('UA service configuration differs; it has not been changed.')
    return preserved, checks, service


def join(installer, environment, *, allow_electron_no_sandbox=False):
    """Explicit existing-PACE setup. No bundled PACE installer is ever run."""
    import json, os, tempfile, shutil
    from types import SimpleNamespace
    from . import ua_connect, licensing, archive_component, recipes
    environment = Path(environment).resolve()
    licensing.guard(environment, 'install_helper')
    store, job = ua_connect.library_context(environment)
    with core.lock(environment / 'helper.lock', blocking=False), \
         core.lock(store.root / 'jobs' / job / 'job.lock', blocking=False):
        ua_connect.require_idle_desktop()
        before, patch_checks, _ = prerequisites(environment)
        consent = environment / 'ua-connect-launch.json'
        if not allow_electron_no_sandbox and not (consent.is_file() and json.loads(consent.read_text()).get('electron_no_sandbox') is True):
            raise core.HostError('UA Connect requires Electron sandbox compatibility consent for the helper only.')
        with tempfile.TemporaryDirectory(prefix='plugg-ua-setup-') as temp:
            root = Path(temp)
            app = root / 'app'
            record = stage(installer, app)
            support = root / 'support'
            (support / 'prefix/drive_c').mkdir(parents=True)
            archive_component.install(SimpleNamespace(root=store.root), support / 'prefix',
                                      recipes.recipe()['packages'], lambda _: None, lambda: None)
            copies = [(app / name, licensed_setup.destination_path(environment, APPLICATION + '/' + name))
                      for name in record['files']]
            for name in vendor_payload.manifest(support):
                target = environment / name
                if target.is_symlink() or not target.resolve().is_relative_to(environment):
                    raise core.HostError('Archive support path escapes the shared environment.')
                copies.append((support / name, target))
            missing = []
            for source, target in copies:
                if target.is_symlink():
                    raise core.HostError('Refusing a linked UA setup destination.')
                if target.exists():
                    if not target.is_file() or core.digest(target) != core.digest(source):
                        raise core.HostError('Existing UA setup file differs; no replacement made: ' + target.name)
                else:
                    missing.append((source, target))
            ua_connect.require_idle_desktop()
            # Unlike interactive helper launch, setup must not close an open manager.
            licensed_setup.prepare(environment)
            if prerequisites(environment)[0] != before:
                raise core.HostError('Shared licensing or runtime state changed during preparation.')
            try:
                for source, target in missing:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as out:
                        temporary = Path(out.name)
                        with source.open("rb") as src:
                            shutil.copyfileobj(src, out)
                    try:
                        os.link(temporary, target)
                    finally:
                        temporary.unlink(missing_ok=True)
                registered = windows_service.register(environment, SERVICE_SPEC, prepare=ua_connect.prepare_runtime)
                ua_connect.configure(environment, allow_electron_no_sandbox=True)
            finally:
                if licensed_setup.preservation_state(environment) != before:
                    raise core.HostError('PACE or licensing state changed; stop and inspect this environment.')
            result = {'schema': 1, 'installer_sha256': record.get('installer_sha256', INSTALLER_SHA256),
                      'version': record.get('version', '1.9.6.3797'),
                      'files_added': len(missing),
                      'service_registered': registered, 'pace_preserved': True, 'identity_preserved': True,
                      'patch_checks': patch_checks}
            core.atomic_json(environment / 'ua-setup.json', result)
            return result


def update(installer, environment):
    """Replace UA Connect's own files with a newer reviewed version.

    UA Connect cannot update itself here: its updater checks the new
    installer's signature by running PowerShell, which Wine does not provide,
    and gives up. This does the same replacement without running the
    installer. It touches only files under Program Files/UA Connect: PACE, the
    iLok state and the environment's identity are compared before and after,
    and a licensing recovery point is taken first. Installing an older
    reviewed version the same way is the rollback.
    """
    import json, os, tempfile, shutil
    from . import ua_connect, licensing
    environment = Path(environment).resolve()
    licensing.guard(environment, 'install_helper')
    store, job = ua_connect.library_context(environment)
    if not (environment / 'ua-setup.json').is_file():
        raise core.HostError('UA Connect is not set up in this environment yet; use setup-existing first.')
    with core.lock(environment / 'helper.lock', blocking=False), \
         core.lock(store.root / 'jobs' / job / 'job.lock', blocking=False):
        ua_connect.require_idle_desktop()
        from .proton_session import foreign_prefix_processes
        if foreign_prefix_processes(environment / 'prefix'):
            raise core.HostError('Close UA Connect, iLok License Manager and any plug-ins from this environment first.')
        before, _, service = prerequisites(environment)
        # Staged beside the library, not in /tmp: the payload is about 600 MB unpacked.
        with tempfile.TemporaryDirectory(prefix='.ua-update-', dir=store.root) as temp:
            app = Path(temp) / 'app'
            record = stage(installer, app)
            licensing.backup(environment, label='before-ua-connect-' + record['version'])
            replaced = 0
            try:
                for name in sorted(record['files']):
                    target = licensed_setup.destination_path(environment, APPLICATION + '/' + name)
                    if target.is_symlink():
                        raise core.HostError('Refusing a linked UA Connect file: ' + name)
                    if target.is_file() and core.digest(target) == record['files'][name]:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as out:
                        temporary = Path(out.name)
                        with (app / name).open('rb') as source:
                            shutil.copyfileobj(source, out)
                    os.replace(temporary, target)
                    replaced += 1
            finally:
                if licensed_setup.preservation_state(environment) != before:
                    raise core.HostError('PACE or licensing state changed; stop and inspect this environment. '
                                         'A recovery point was taken first; see plugg licensing backups.')
        previous = json.loads((environment / 'ua-setup.json').read_text())
        result = {**previous, 'installer_sha256': record['installer_sha256'], 'version': record['version'],
                  'updated_from': previous.get('version', '1.9.6.3797'), 'files_written': replaced,
                  'pace_preserved': True, 'identity_preserved': True}
        core.atomic_json(environment / 'ua-setup.json', result)
        return result
