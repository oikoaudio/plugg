"""Shared checks for in-place setup in protected licensing environments."""
from pathlib import Path
from . import core, licensing, ua_connect, vendors, vendor_payload
file_manifest = vendor_payload.manifest

def destination_path(environment, relative):
    """Do not follow vendor directory links into another environment."""
    drive = Path(environment) / 'prefix/drive_c'
    if (not drive.is_dir() or drive.is_symlink()
            or not drive.resolve().is_relative_to(Path(environment).resolve())):
        raise core.HostError('An existing local Windows drive is required.')
    target = drive / relative
    if not target.resolve().is_relative_to(drive.resolve()):
        raise core.HostError('Setup destination escapes the shared environment.')
    return target


def preservation_state(environment):
    """Require a known shared identity and record PACE binaries plus runtime config."""
    environment = Path(environment)
    licensing.guard(environment, 'install_component')
    verified = licensing.verify(environment)
    if not verified['protected'] or verified['matches'] is not True:
        raise core.HostError('Select an existing PACE environment with a verified licensing identity.')
    files = {}
    for base in ('Program Files', 'Program Files (x86)'):
        root = destination_path(environment, base + '/Common Files/PACE')
        if root.is_dir():
            for name, digest in file_manifest(root).items():
                if name.lower().endswith(('.exe', '.dll')):
                    files[base + '/Common Files/PACE/' + name] = digest
    if not any(name.lower().endswith('/ldsvc.exe') for name in files):
        raise core.HostError('Existing PACE License Support is required; this operation does not install it.')
    for name in ('session.json', 'licensing.json', 'launch-full-proton'):
        files[name] = core.digest(environment / name)
    return {'identity': verified['observed'], 'files': files}



def prepare(environment, *, bootstrap_pids=()):
    allowed = vendors.SERVICES | {'mdnsresponder.exe', 'ldsvc.exe', 'xalia.exe',
        'crashpad_handler.exe', 'uahelperservice.exe', 'uacloudhelper.exe', 'installerservice.exe'}
    ua_connect.prepare_runtime(environment, bootstrap_pids=bootstrap_pids, idle_programs=allowed)
