"""Install a shared Windows archive utility from verified package assets.

The caller supplies assets and holds the environment's installation lock.
This operation does not choose a vendor, runtime or licensing environment.
"""
from pathlib import Path
import shutil
import tempfile

from . import core, artifacts, licensing


def install(store, prefix, assets, report, check):
    prefix = Path(prefix)
    licensing.guard(prefix.parent, 'prepare_archive_tools')
    drive = (prefix / 'drive_c').resolve()
    destination = prefix / 'drive_c/Plugg/Tools/Archive'
    licenses = prefix.parent / 'component-licenses'
    if not destination.resolve().is_relative_to(drive):
        raise core.HostError('Archive utility destination escapes the environment')
    if licenses.is_symlink():
        raise core.HostError('Archive component licenses must stay in the environment')
    # Assemble everything before touching installed files. A conflicting package
    # or existing DLL must not leave half of a new dependency set installed.
    with tempfile.TemporaryDirectory(prefix='plugg-archive-') as temporary:
        stage = Path(temporary)
        binaries = stage / 'binaries'
        notices = stage / 'licenses'
        binaries.mkdir()
        notices.mkdir()
        for index, asset in enumerate(assets):
            check()
            archive = artifacts.fetch(store, asset, report, check, artifacts.ARCHIVE_PACKAGES)
            extracted = stage / str(index)
            extracted.mkdir()
            artifacts.unpack(archive, extracted)
            for source_root, target_root, binary in (
                    (extracted / 'mingw64/bin', binaries, True),
                    (extracted / 'mingw64/share/licenses', notices, False)):
                sources = source_root.glob('*') if binary else source_root.rglob('*')
                for source in sources:
                    if source.is_symlink():
                        raise core.HostError('Archive component contains a symbolic link')
                    if not source.is_file() or (binary and source.suffix.lower() not in ('.dll', '.exe')):
                        continue
                    relative = Path(source.name) if binary else source.relative_to(source_root)
                    target = target_root / relative
                    if target.exists() and core.digest(target) != core.digest(source):
                        raise core.HostError('Conflicting archive-tool component: ' + str(relative))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        executable = binaries / 'bsdtar.exe'
        if not executable.is_file():
            raise core.HostError('Archive component does not provide bsdtar.exe')
        alias = binaries / 'tar.exe'
        if alias.exists() and core.digest(alias) != core.digest(executable):
            raise core.HostError('Conflicting archive-tool component: tar.exe')
        shutil.copy2(executable, alias)
        copies = []
        for source_root, target_root in ((binaries, destination), (notices, licenses)):
            for source in source_root.rglob('*'):
                if not source.is_file():
                    continue
                target = target_root / source.relative_to(source_root)
                if not target.resolve().is_relative_to(target_root.resolve()) or target.is_symlink():
                    raise core.HostError('Archive component destination contains a symbolic link')
                if target.exists() and (not target.is_file() or core.digest(target) != core.digest(source)):
                    raise core.HostError('Conflicting installed archive component: ' + str(target.name))
                copies.append((source, target))
        check()
        for source, target in copies:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        core.atomic_json(prefix.parent / 'archive-components.json', assets)
