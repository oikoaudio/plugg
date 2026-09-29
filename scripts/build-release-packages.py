#!/usr/bin/env python3
"""Build Plugg's .deb, .rpm and generic tarball from a release's built parts.

The inputs are what the release workflow has already built: the wheel (or,
without --wheel, one built here from the checkout with
scripts/build-python-package.py), the bridge archive from
scripts/build-release-bridge.py and the forwarder directory from
scripts/build-powershell-forwarder.py. They are laid out as they install:

  /usr/lib/plugg/app/plugg/            the manager, the files the wheel holds
  /usr/lib/plugg/bridge/               the prebuilt bridge and its licences
  /usr/lib/plugg/powershell-forwarder/ the PowerShell forwarder and its licences
  /usr/bin/plugg                       runs the system python3 on the app
  /usr/share/applications/com.oikoaudio.Plugg.desktop
  /usr/share/doc/plugg/                README.md, third-party.md
  /usr/share/licenses/plugg/LICENSE    (the .deb puts it in doc/plugg/copyright)

Writes into --output:
  plugg_<version>_amd64.deb
  plugg-<version>-1.x86_64.rpm
  plugg-<version>-x86_64.tar.gz        the same tree plus INSTALL.md

The .deb and .rpm are made by nfpm (packaging/nfpm.yaml), downloaded at a
pinned version and checked against a pinned SHA-256. Every file's mtime is
the commit time, so two builds of one commit with the same inputs match.
"""
import argparse
import gzip
import hashlib
import importlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

REPO = Path(__file__).resolve().parents[1]
NFPM_VERSION = '2.47.0'
NFPM_URL = ('https://github.com/goreleaser/nfpm/releases/download/v' + NFPM_VERSION
            + '/nfpm_' + NFPM_VERSION + '_Linux_x86_64.tar.gz')
NFPM_SHA256 = '0660ca602b2d2d2ae4781a06c692b3eeb9d437ffea05b831d76e41f4a3188783'

#: The files the forwarder build writes (scripts/build-powershell-forwarder.py).
FORWARDER_FILES = ('powershell32.exe', 'powershell64.exe', 'LICENSE.forwarder', 'LICENSE.Go')

DEB_COPYRIGHT = '''Plugg {version}
Source: https://github.com/oikoaudio/plugg (tag v{version})

Plugg is free software, GPL-3.0-or-later. The GNU General Public License version 3 follows below.

The bridge in /usr/lib/plugg/bridge is a patched build of yabridge (GPL-3.0-or-later). It carries its own licence files: COPYING.yabridge, NOTICE.md and licenses/, which cover the VST3 SDK (used under its GPLv3 option), asio, bitsery, function2, toml++ and ghc::filesystem. The PowerShell forwarder in /usr/lib/plugg/powershell-forwarder carries LICENSE.forwarder and LICENSE.Go. /usr/share/doc/plugg/third-party.md describes all of them.

'''

INSTALL = '''# Plugg {version}: generic Linux tree

This archive holds the same files as the .deb and .rpm packages, laid out under `usr/` as they install. It is for distributions without a package here, and for inspecting what the packages contain.

To install by hand, copy the tree into `/usr` as root:

```sh
sudo cp -r usr/. /usr/
```

The launcher `usr/bin/plugg` expects the app in `/usr/lib/plugg/app` and runs `/usr/bin/python3`. Plugg finds the bridge in `/usr/lib/plugg/bridge` and the PowerShell forwarder in `/usr/lib/plugg/powershell-forwarder`. Installing somewhere else needs a changed launcher.

Your distribution must provide:

- Python 3.12 or newer, PyGObject and GTK 4.10 or newer with its GObject introspection data
- glibc 2.34 or newer and libstdc++ from GCC 11 or newer
- libxcb, D-Bus, zstd, libarchive (`bsdtar`), bubblewrap, xdg-utils and CA certificates

Plugg does not need Wine. It downloads a pinned Proton runtime the first time it needs one and checks its hash.

To remove it, delete `/usr/bin/plugg`, `/usr/lib/plugg`, `/usr/share/applications/com.oikoaudio.Plugg.desktop`, `/usr/share/doc/plugg` and `/usr/share/licenses/plugg`. Your library in `~/.local/share/plugg` and your published plug-ins stay where they are.
'''

PEP440 = re.compile(r'(?P<release>[0-9]+(?:\.[0-9]+)*)(?:(?P<pre>a|b|rc)(?P<pre_n>[0-9]+))?'
                    r'(?:\.post(?P<post>[0-9]+))?(?:\.dev(?P<dev>[0-9]+))?')


def declared_version(root=REPO):
    """The version plugg/__init__.py declares, the one place it is written."""
    return re.search(r'^__version__ = "(.+)"', (root / 'plugg/__init__.py').read_text(), re.M).group(1)


def package_version(version):
    """A normalised PEP 440 version in the syntax dpkg and rpm both order correctly.

    A pre-release or development version must sort before the release it
    leads to, which both tools do with a tilde: 0.1.0rc1 becomes 0.1.0~rc1.
    A development release of a final version sorts before its alpha in PEP
    440, so it gets two tildes: 0.1.0.dev0 becomes 0.1.0~~dev0. A
    post-release becomes +postN, which sorts after the release and before
    the next one in both. Epochs and local versions are refused.
    """
    match = PEP440.fullmatch(version)
    if not match:
        raise ValueError('Not a normalised PEP 440 version without epoch or local part: ' + version)
    result = match['release']
    if match['pre']:
        result += '~' + match['pre'] + match['pre_n']
    if match['post']:
        result += '+post' + match['post']
    if match['dev']:
        result += ('~dev' if match['pre'] or match['post'] else '~~dev') + match['dev']
    return result


def checkout_module(name):
    """A module of this checkout's plugg package, for its checks and pinned values."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    return importlib.import_module('plugg.' + name)


def safe_member(name, top):
    """A relative archive path under top, or refuse it."""
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != top:
        raise ValueError('Unexpected path in archive: ' + name)
    return PurePosixPath(*path.parts[1:])


def write(target, data, executable=False):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    target.chmod(0o755 if executable else 0o644)


def stage_app(wheel, version, target):
    """The wheel's plugg/ files, byte for byte; nothing else from it."""
    expected = 'plugg-' + version + '-py3-none-any.whl'
    if wheel.name != expected:
        raise ValueError('Expected the wheel ' + expected + ', got ' + wheel.name)
    metadata = 'plugg-' + version + '.dist-info'
    with zipfile.ZipFile(wheel) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            top = PurePosixPath(info.filename).parts[0]
            if top == metadata:
                continue
            relative = safe_member(info.filename, 'plugg')
            write(target / 'plugg' / relative, archive.read(info))
    if not (target / 'plugg/__main__.py').is_file():
        raise ValueError('The wheel has no plugg package')


def stage_bridge(archive_path, version, target):
    """The bridge archive's one directory, checked against its build manifest."""
    top = 'plugg-bridge-' + version + '-x86_64'
    if archive_path.name != top + '.tar.gz':
        raise ValueError('Expected the bridge archive ' + top + '.tar.gz, got ' + archive_path.name)
    checksum = archive_path.with_name(archive_path.name + '.sha256')
    if checksum.is_file():
        recorded = checksum.read_text().split()[0]
        if hashlib.sha256(archive_path.read_bytes()).hexdigest() != recorded:
            raise ValueError('The bridge archive does not match ' + checksum.name)
    with tarfile.open(archive_path) as archive:
        for member in archive.getmembers():
            relative = safe_member(member.name, top)
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError('Only files and directories are allowed in the bridge archive: ' + member.name)
            write(target / relative, archive.extractfile(member).read(), bool(member.mode & 0o100))
    checkout_module('bridge_bundle').inspect(target)
    for name in ('NOTICE.md', 'COPYING.yabridge', 'licenses'):
        if not (target / name).exists():
            raise ValueError('The bridge archive has no ' + name)


def stage_forwarder(source, target):
    """The forwarder build, checked against its manifest and the reviewed source."""
    built = json.loads((source / 'build.json').read_text())
    if built.get('source_sha256') != checkout_module('powershell_component').FORWARDER_SOURCE_SHA256:
        raise ValueError('The PowerShell forwarder was built from different source; rebuild it.')
    if set(built.get('files', {})) != set(FORWARDER_FILES):
        raise ValueError('The forwarder manifest must list exactly ' + ', '.join(FORWARDER_FILES))
    for name in FORWARDER_FILES:
        data = (source / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != built['files'][name]:
            raise ValueError('The forwarder file changed after its build: ' + name)
        write(target / name, data, name.endswith('.exe'))
    write(target / 'build.json', (source / 'build.json').read_bytes())


def stage(root, wheel, bridge, forwarder, version, staging):
    """The installed tree in staging/tree, the .deb's copyright in staging/deb and
    the package scripts in staging/scripts."""
    tree = staging / 'tree'
    lib = tree / 'usr/lib/plugg'
    stage_app(wheel, version, lib / 'app')
    stage_bridge(bridge, version, lib / 'bridge')
    stage_forwarder(forwarder, lib / 'powershell-forwarder')
    # The Arch package installs the same launcher (packaging/aur/*/PKGBUILD).
    write(tree / 'usr/bin/plugg', (root / 'packaging/launcher.sh').read_bytes(), executable=True)
    write(tree / 'usr/share/applications/com.oikoaudio.Plugg.desktop',
          (root / 'packaging/arch/com.oikoaudio.Plugg.desktop').read_bytes())
    write(tree / 'usr/share/doc/plugg/README.md', (root / 'README.md').read_bytes())
    write(tree / 'usr/share/doc/plugg/third-party.md', (root / 'docs/third-party.md').read_bytes())
    licence = (root / 'LICENSE').read_bytes()
    write(tree / 'usr/share/licenses/plugg/LICENSE', licence)
    write(staging / 'deb/copyright', DEB_COPYRIGHT.format(version=version).encode() + licence)
    for name in ('postinstall.sh', 'preremove.sh'):
        write(staging / 'scripts' / name, (root / 'packaging/nfpm-scripts' / name).read_bytes(), executable=True)
    return tree


def tarball(tree, version, output, epoch):
    """A reproducible .tar.gz of the tree and INSTALL.md under one directory."""
    top = 'plugg-' + version + '-x86_64'
    files = {'INSTALL.md': (INSTALL.format(version=version).encode(), 0o644)}
    for path in sorted(tree.rglob('*')):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError('Unexpected file in the staging tree: ' + str(path))
        if path.is_file():
            files[path.relative_to(tree).as_posix()] = (path.read_bytes(), 0o755 if path.stat().st_mode & 0o100 else 0o644)
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w', format=tarfile.PAX_FORMAT) as archive:
        directories = {top}
        for name in files:
            parent = PurePosixPath(top, name).parent
            while str(parent) != top:
                directories.add(str(parent))
                parent = parent.parent
        for directory in sorted(directories):
            info = tarfile.TarInfo(directory)
            info.type, info.mode, info.mtime = tarfile.DIRTYPE, 0o755, epoch
            archive.addfile(info)
        for name in sorted(files):
            data, mode = files[name]
            info = tarfile.TarInfo(top + '/' + name)
            info.size, info.mode, info.mtime = len(data), mode, epoch
            archive.addfile(info, io.BytesIO(data))
    target = output / (top + '.tar.gz')
    with target.open('wb') as stream, gzip.GzipFile(fileobj=stream, mode='wb', mtime=epoch, filename='') as zipped:
        zipped.write(raw.getvalue())
    return target


def nfpm(cache):
    """The pinned nfpm binary, downloaded once into cache and checked every time."""
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / Path(NFPM_URL).name
    if not archive.is_file():
        print('Downloading', NFPM_URL, flush=True)
        partial = archive.with_name(archive.name + '.part')
        with urllib.request.urlopen(NFPM_URL, timeout=120) as response, partial.open('wb') as stream:
            shutil.copyfileobj(response, stream)
        partial.replace(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != NFPM_SHA256:
        raise SystemExit('nfpm download does not match its pinned SHA-256: ' + str(archive))
    binary = cache / ('nfpm-' + NFPM_VERSION)
    with tarfile.open(archive) as tar:
        data = tar.extractfile(tar.getmember('nfpm')).read()
    if not binary.is_file() or binary.read_bytes() != data:
        binary.write_bytes(data)
    binary.chmod(0o755)
    return binary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--bridge', type=Path, required=True, help='plugg-bridge-<version>-x86_64.tar.gz')
    parser.add_argument('--forwarder', type=Path, default=REPO / 'bundle/powershell-forwarder',
                        help='The PowerShell forwarder build (default: bundle/powershell-forwarder)')
    parser.add_argument('--wheel', type=Path, help='The release wheel (default: build one from the checkout)')
    parser.add_argument('--output', type=Path, required=True, help='Directory for the packages')
    parser.add_argument('--cache', type=Path, default=REPO / 'build/tools',
                        help='Where the pinned nfpm download is kept (default: build/tools)')
    args = parser.parse_args()
    version = declared_version()
    converted = package_version(version)
    epoch = int(subprocess.check_output(['git', '-C', str(REPO), 'log', '-1', '--format=%ct']).strip())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    tool = nfpm(args.cache.resolve())
    with tempfile.TemporaryDirectory(prefix='plugg-packages-') as temporary:
        temporary = Path(temporary)
        wheel = args.wheel
        if wheel is None:
            subprocess.run([sys.executable, str(REPO / 'scripts/build-python-package.py'),
                            '--output', str(temporary / 'wheel')], check=True)
            wheel = temporary / 'wheel' / ('plugg-' + version + '-py3-none-any.whl')
        staging = temporary / 'staging'
        tree = stage(REPO, wheel.resolve(strict=True), args.bridge.resolve(strict=True),
                     args.forwarder.resolve(strict=True), version, staging)
        # nfpm takes each file's mtime from the file, so they all get the commit time.
        for path in [*staging.rglob('*'), staging]:
            os.utime(path, (epoch, epoch), follow_symlinks=False)
        built = [tarball(tree, version, output, epoch)]
        environment = dict(os.environ, PLUGG_PACKAGE_VERSION=converted, SOURCE_DATE_EPOCH=str(epoch))
        for packager, name in (('deb', 'plugg_' + version + '_amd64.deb'),
                               ('rpm', 'plugg-' + version + '-1.x86_64.rpm')):
            target = output / name
            target.unlink(missing_ok=True)
            subprocess.run([str(tool), 'package', '--config', str(REPO / 'packaging/nfpm.yaml'),
                            '--packager', packager, '--target', str(target)],
                           cwd=staging, env=environment, check=True, stdout=subprocess.DEVNULL)
            built.append(target)
    print('Package version', converted, '(from', version + ')')
    for path in built:
        print(path, hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == '__main__':
    sys.exit(main())
