"""Extract an exact reviewed vendor installer without executing Windows code."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
from . import core


def manifest(directory):
    result, total = {}, 0
    for path in sorted(Path(directory).rglob('*')):
        if path.is_symlink():
            raise core.HostError('Vendor payload contains a symbolic link.')
        if path.is_dir():
            continue
        if not path.is_file():
            raise core.HostError('Vendor payload contains a special file.')
        total += path.stat().st_size
        if total > 2 * 1024**3 or len(result) >= 20000:
            raise core.HostError('Vendor payload exceeds the supported size.')
        result[path.relative_to(directory).as_posix()] = core.digest(path)
    return result


def unpack(installer, destination, *, sha256, size):
    """Pins are supplied by reviewed adapter code, never by an untrusted archive."""
    installer, destination = Path(installer), Path(destination)
    if destination.exists() or destination.is_symlink():
        raise core.HostError('Choose an unused payload staging directory.')
    if not shutil.which('bsdtar'):
        raise core.HostError('Install the Linux libarchive tools (bsdtar) to unpack this installer.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.vendor-payload-', dir=destination.parent) as temp:
        archive = Path(temp) / 'installer.exe'
        with installer.open('rb') as source, archive.open('xb') as output:
            source.seek(0, 2)
            if source.tell() != size:
                raise core.HostError('Unsupported vendor installer size.')
            source.seek(0)
            remaining = size
            while remaining:
                block = source.read(min(1024 * 1024, remaining))
                if not block:
                    raise core.HostError('Vendor installer was truncated.')
                output.write(block)
                remaining -= len(block)
        if core.digest(archive) != sha256:
            raise core.HostError('Unsupported vendor installer hash.')
        extracted = Path(temp) / 'files'
        extracted.mkdir()
        subprocess.run(['bsdtar', '-xf', str(archive), '-C', str(extracted)],
                       check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        files = manifest(extracted)
        os.rename(extracted, destination)
    return files
