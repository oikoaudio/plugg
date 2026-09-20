"""Pinned Microsoft PowerShell and a source-built forwarding executable."""
import json,os,shutil
from pathlib import Path
from . import artifacts,core,licensing

ASSET = {'url':'https://github.com/PowerShell/PowerShell/releases/download/v7.4.11/PowerShell-7.4.11-win-x64.msi',
         'sha256':'9579011c463a3ad6abf890736a97e2fbba9a7b4e09ce851576ccf263e15bdc97'}
SOURCE = artifacts.Source(('github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'),
                         entry_prefixes=('https://github.com/PowerShell/PowerShell/releases/download/',))

#: The reviewed forwarder source (components/powershell-forwarder/main.go).
FORWARDER_SOURCE_SHA256 = 'f798fdbffc86264acfccc8fd4dc678ad9f4e2363a1ab64ab55ae1503e307ac6e'


def forwarder_directory():
    """A checkout's own build first, then the one an installed package ships."""
    import sys
    for candidate in (core.REPO/'bundle/powershell-forwarder', Path(sys.prefix)/'lib/plugg/powershell-forwarder',
                      Path('/usr/lib/plugg/powershell-forwarder')):
        if (candidate/'build.json').is_file():
            return candidate
    raise core.HostError('The PowerShell forwarder is not built. From a checkout, run '
                         'scripts/build-powershell-forwarder.py; the Arch package includes it.')


def install(store,directory,launcher,report,check):
    directory=Path(directory)
    licensing.guard(directory,'install_component')
    bundle=forwarder_directory()
    manifest=bundle/'build.json'
    built=json.loads(manifest.read_text())
    if built.get('source_sha256') != FORWARDER_SOURCE_SHA256:
        raise core.HostError('This PowerShell forwarder was built from different source; rebuild it.')
    for name in ('powershell32.exe','powershell64.exe','LICENSE.forwarder','LICENSE.Go'):
        if core.digest(bundle/name) != built['files'].get(name):
            raise core.HostError('PowerShell forwarder build changed.')
    drive=(directory/'prefix/drive_c').resolve()
    if not drive.is_relative_to(directory.resolve()):
        raise core.HostError('PowerShell drive escapes its environment.')
    targets=[(name,drive/relative) for name,relative in (
        ('powershell32.exe','windows/syswow64/WindowsPowerShell/v1.0/powershell.exe'),
        ('powershell64.exe','windows/system32/WindowsPowerShell/v1.0/powershell.exe'))]
    for _,target in targets:
        if not target.resolve().is_relative_to(drive) or target.is_symlink():
            raise core.HostError('PowerShell installation path escapes its environment.')
    report('Installing Microsoft PowerShell')
    installer=artifacts.fetch(store,ASSET,report,check,SOURCE)
    rc=core.run_process([launcher,'msiexec','/i',str(installer),'/quiet','/norestart',
        'ENABLE_PSREMOTING=0','REGISTER_MANIFEST=1','DISABLE_TELEMETRY=1','USE_MU=0',
        'ENABLE_MU=0','LAUNCHAPPONEXIT=0'],os.environ.copy(),Path(os.devnull),check,900)
    if rc not in (0,194,3010):raise core.HostError('PowerShell installation failed: '+str(rc))
    if not (drive/'Program Files/PowerShell/7/pwsh.exe').is_file():raise core.HostError('PowerShell was not installed.')
    for name,target in targets:
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(bundle/name,target)
    rc=core.run_process([launcher,'reg','add',r'HKCU\Software\Wine\DllOverrides','/v','powershell.exe','/t','REG_SZ','/d','native','/f'],
                        os.environ.copy(),Path(os.devnull),check,120)
    if rc:raise core.HostError('PowerShell native override failed.')
    notices=directory/'component-licenses/powershell-forwarder'
    if not notices.resolve().is_relative_to(directory.resolve()):
        raise core.HostError('PowerShell notices escape their environment.')
    notices.mkdir(parents=True,exist_ok=True)
    for name in ('LICENSE.forwarder','LICENSE.Go'):
        shutil.copyfile(bundle/name,notices/name)
    core.atomic_json(directory/'powershell-component.json',{'asset':ASSET,'forwarder':built,'profile_installed':False})
