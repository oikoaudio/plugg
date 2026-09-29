#!/usr/bin/env python3
"""Build the release bridge in the pinned container and pack it with its licences.

The same command runs locally and in the release workflow. It sends the
checkout's tracked files into a fresh container on stdin and reads the built
bridge back on stdout: no host mounts, and only this run's container is
removed. The container needs network access to fetch yabridge and its Meson
subprojects at their pinned revisions.

Writes into --output:
  plugg-bridge-<version>-x86_64.tar.gz   the bridge directory, licences included
  plugg-bridge-<version>-x86_64.tar.gz.sha256

With --pin URL, also writes plugg/recipes/bridge-release.json naming the
archive at URL/<archive name> and its SHA-256, so the wheel built next
downloads exactly this bridge (plugg/bridge_download.py). The release
workflow does this; a checkout never commits that file.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile

REPO = Path(__file__).resolve().parents[1]
CONTEXT = REPO / 'packaging/bridge'
LABEL = 'plugg.build=release-bridge'
#: The builder image, published by .github/workflows/bridge-builder.yml and
#: tagged with the Dockerfile's hash, so one Dockerfile names one image.
PUBLISHED = 'ghcr.io/oikoaudio/plugg-bridge-builder'

# Inside the container: unpack the checkout, build, gather every licence the
# binaries carry, report the newest glibc symbol they need, and send the
# result back as a tar on stdout. Build output goes to stderr.
BUILD = r'''
set -eu
mkdir src && tar -x -C src && cd src
{
  PLUGG_BUILD_DIR="$HOME/build" PLUGG_BRIDGE_OUTPUT="$HOME/out" PLUGG_BUILD_JOBS="$(nproc)" scripts/build-bridge.sh
  mkdir -p "$HOME/out/licenses"
  for dir in vendor/yabridge/subprojects/*/; do
    name=$(basename "$dir")
    [ "$name" = packagefiles ] && continue
    found=$(find "$dir" -maxdepth 2 -type f \( -iname 'licen[cs]e*' -o -iname 'copying*' \) ! -iname '*.pdf' | sort)
    [ -n "$found" ] || continue
    mkdir -p "$HOME/out/licenses/$name"
    for file in $found; do cp "$file" "$HOME/out/licenses/$name/"; done
  done
  echo "Newest glibc symbol needed:" $(objdump -T "$HOME"/out/*.so "$HOME/out/plugg-scan" \
    | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -n1)
  echo "Newest libstdc++ symbol needed:" $(objdump -T "$HOME"/out/*.so "$HOME/out/plugg-scan" \
    | grep -o 'GLIBCXX_[0-9.]*' | sort -uV | tail -n1)
} 1>&2
tar -c -C "$HOME" out
'''

NOTICE = '''# Plugg bridge {version}: licences and source

This directory is Plugg's build of yabridge's VST3 bridge, the Windows plug-in host that runs under Wine, and Plugg's scanner.

- yabridge is GPL-3.0-or-later (`COPYING.yabridge`). The source is https://github.com/robbert-vdh/yabridge at the revision in `build.json`, plus the patches in `patches/` of https://github.com/oikoaudio/plugg at tag `v{version}`, listed with their hashes in `build.json`.
- `plugg-scan` is part of Plugg, GPL-3.0-or-later, built from `native/scan.cpp` in the same Plugg tag.
- Both link parts of the VST3 SDK, used under its GPLv3 option, and yabridge links asio, bitsery, function2, tomlplusplus and ghc::filesystem. Each project's licence is in `licenses/<project>/`, and the revisions are in `build.json`.
- `scripts/build-release-bridge.py` in the Plugg tag rebuilds this in the same pinned container (`packaging/bridge/Dockerfile`). This build ran in `{image}`.
'''


def run(*command, **kwargs):
    return subprocess.run([str(part) for part in command], check=True, **kwargs)


def tracked_files():
    """The checkout's tracked files as a tar, the way a clean clone would have them."""
    names = subprocess.check_output(['git', '-C', str(REPO), 'ls-files', '-z']).split(b'\0')
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        for name in filter(None, names):
            path = REPO / name.decode()
            if path.is_file():
                archive.add(path, arcname=name.decode(), recursive=False)
    return buffer.getvalue()


def pack(built, version, output, epoch, image):
    """A reproducible .tar.gz of the bridge directory, named for the version."""
    top = 'plugg-bridge-' + version + '-x86_64'
    source = tarfile.open(fileobj=io.BytesIO(built))
    members = sorted((m for m in source.getmembers() if m.isfile()), key=lambda m: m.name)
    files = {}
    for member in members:
        if not member.name.startswith('out/') or '..' in Path(member.name).parts:
            raise SystemExit('Unexpected path from the build: ' + member.name)
        files[member.name[len('out/'):]] = (source.extractfile(member).read(), member.mode & 0o777)
    files['NOTICE.md'] = (NOTICE.format(version=version, image=image).encode(), 0o644)
    target = output / (top + '.tar.gz')
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w', format=tarfile.PAX_FORMAT) as archive:
        directories = sorted({str(Path(top, name).parent) for name in files} | {top})
        for directory in directories:
            info = tarfile.TarInfo(directory)
            info.type, info.mode, info.mtime = tarfile.DIRTYPE, 0o755, epoch
            archive.addfile(info)
        for name in sorted(files):
            data, mode = files[name]
            info = tarfile.TarInfo(top + '/' + name)
            info.size, info.mode, info.mtime = len(data), (0o755 if mode & 0o100 else 0o644), epoch
            archive.addfile(info, io.BytesIO(data))
    with target.open('wb') as stream, gzip.GzipFile(fileobj=stream, mode='wb', mtime=epoch, filename='') as zipped:
        zipped.write(raw.getvalue())
    checksum = hashlib.sha256(target.read_bytes()).hexdigest()
    (output / (target.name + '.sha256')).write_text(checksum + '  ' + target.name + '\n')
    return target, checksum


def published_digest(tag):
    """The registry digest of a pulled image, or None when it is not published."""
    pulled = subprocess.run(['docker', 'pull', '--quiet', tag], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if pulled.returncode != 0:
        return None
    digests = json.loads(subprocess.check_output(['docker', 'image', 'inspect', tag, '--format', '{{json .RepoDigests}}']))
    return next((d for d in digests if d.startswith(PUBLISHED + '@')), None)


def builder_image(tag, local):
    """The published image for this Dockerfile, pulled by digest; or one built here."""
    if not local and (digest := published_digest(tag)):
        print('Builder image', digest, file=sys.stderr)
        return digest
    print('Builder image not published for this Dockerfile; building it here (slow).', file=sys.stderr)
    local_tag = 'plugg-bridge-builder:' + tag.rsplit(':', 1)[1]
    # The full build log goes to stderr, so a failed package download says why.
    run('docker', 'build', '--progress=plain', '--tag', local_tag, CONTEXT, stdout=sys.stderr)
    return local_tag


def publish_image(tag):
    """Build the builder image and push it, unless this Dockerfile's image is already published."""
    if digest := published_digest(tag):
        print('Already published:', digest)
        return 0
    run('docker', 'build', '--progress=plain', '--tag', tag, CONTEXT, stdout=sys.stderr)
    run('docker', 'push', '--quiet', tag, stdout=sys.stderr)
    print('Published:', published_digest(tag))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, help='Directory for the archive and its checksum')
    parser.add_argument('--pin', metavar='URL', help='Release download URL the archive will be published under')
    parser.add_argument('--publish-image', action='store_true',
                        help='only build the builder image and push it to ' + PUBLISHED + ', unless it is there')
    parser.add_argument('--local-image', action='store_true', help='build the builder image here instead of pulling it')
    args = parser.parse_args()
    tag = PUBLISHED + ':dockerfile-' + hashlib.sha256((CONTEXT / 'Dockerfile').read_bytes()).hexdigest()[:16]
    if args.publish_image:
        return publish_image(tag)
    if args.output is None:
        parser.error('--output is required')
    version = re.search(r'^__version__ = "(.+)"', (REPO / 'plugg/__init__.py').read_text(), re.M).group(1)
    epoch = int(subprocess.check_output(['git', '-C', str(REPO), 'log', '-1', '--format=%ct']).strip())
    image = builder_image(tag, args.local_image)
    built = run('docker', 'run', '--rm', '--interactive', '--label', LABEL, image, 'sh', '-c', BUILD,
                input=tracked_files(), stdout=subprocess.PIPE).stdout
    args.output.mkdir(parents=True, exist_ok=True)
    target, checksum = pack(built, version, args.output, epoch, image)
    if args.pin:
        pinned = REPO / 'plugg/recipes/bridge-release.json'
        pinned.write_text(json.dumps({'version': version, 'url': args.pin.rstrip('/') + '/' + target.name,
                                      'sha256': checksum}, indent=2) + '\n')
        print('Pinned in', pinned)
    print(target, checksum)


if __name__ == '__main__':
    sys.exit(main())
