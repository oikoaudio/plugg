#!/usr/bin/env python3
"""Publish a runtime's Wine modules as a GitHub release, from files in this repository.

    python3 scripts/publish-runtime-release.py plugg-1 --archive plugg-1-wine-modules.tar
    python3 scripts/publish-runtime-release.py plugg-1 --archive ... --commit <rev> --publish

Without --publish it only says what it would do. Everything it publishes
comes from the repository or is checked against it:

  the archive           must match the SHA-256 in plugg/recipes/runtime-overlays.json
  NOTES.md, SOURCE.md   from packaging/runtime/<name>/
  Wine's licence files  LICENSE, COPYING.LIB and AUTHORS at the Wine revision in
                        patches/wine/series.json, attached as wine-<name>

The tag is the one the release URL names. A missing tag is created, annotated,
at --commit, which must hold the patches and build script. An existing tag is
never moved, and a published file is never replaced: if a release already
has a file with different bytes, the script stops and says so.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from plugg import runtime_overlay  # noqa: E402

WINE_FILES = ('LICENSE', 'COPYING.LIB', 'AUTHORS')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.run(['git', '-C', str(REPO), *args], check=True, capture_output=True, text=True).stdout.strip()


def gh(*args, check=True):
    return subprocess.run(['gh', *args], check=check, capture_output=True, text=True)


def wine_licences(series):
    base = series['wine_source'].replace('https://github.com/', 'https://raw.githubusercontent.com/')
    files = {}
    for name in WINE_FILES:
        with urllib.request.urlopen(base + '/' + series['wine_revision'] + '/' + name, timeout=60) as response:
            files['wine-' + name] = response.read()
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('runtime', help='runtime name, as in runtime-overlays.json')
    parser.add_argument('--archive', type=Path, required=True, help='the built modules archive')
    parser.add_argument('--commit', help='where to create the tag if it does not exist yet')
    parser.add_argument('--publish', action='store_true', help='create the tag and release; otherwise only report')
    args = parser.parse_args()

    spec = runtime_overlay.overlay(args.runtime)
    if spec.get('draft') or not spec.get('release'):
        raise SystemExit(args.runtime + ' is a draft or has no release entry; nothing to publish.')
    url, expected = spec['release']['url'], spec['release']['sha256']
    parts = url.split('/')
    repository, tag, asset = '/'.join(parts[3:5]), parts[-2], parts[-1]
    if url != f'https://github.com/{repository}/releases/download/{tag}/{asset}':
        raise SystemExit('Unexpected release URL: ' + url)
    archive = args.archive.read_bytes()
    if args.archive.name != asset or sha256(archive) != expected:
        raise SystemExit(f'{args.archive} is not {asset} with SHA-256 {expected}.')

    folder = REPO / 'packaging/runtime' / args.runtime
    notes = (folder / 'NOTES.md').read_text()
    series = json.loads((REPO / 'patches/wine/series.json').read_text())
    files = {asset: archive, 'SOURCE.md': (folder / 'SOURCE.md').read_bytes(), **wine_licences(series)}
    for name, data in files.items():
        print(f'  {name:32} {sha256(data)}')

    remote = git('ls-remote', '--tags', 'origin', 'refs/tags/' + tag + '^{}') or git('ls-remote', '--tags', 'origin', 'refs/tags/' + tag)
    if remote:
        target = remote.split()[0]
        print(f'Tag {tag} exists at {target[:12]}; it will not be moved.')
        if args.commit and git('rev-parse', args.commit + '^{commit}') != target:
            raise SystemExit(f'--commit {args.commit} is not where {tag} points. Tags are never moved.')
    else:
        if not args.commit:
            raise SystemExit(f'Tag {tag} does not exist yet: pass --commit with the commit that holds the patches.')
        target = git('rev-parse', args.commit + '^{commit}')
        print(f'Tag {tag} will be created at {target[:12]}.')

    existing = gh('release', 'view', tag, '--repo', repository, '--json', 'assets', check=False)
    published = {}
    if existing.returncode == 0:
        published = {a['name']: (a.get('digest') or '').removeprefix('sha256:')
                     for a in json.loads(existing.stdout)['assets']}
        for name, data in files.items():
            if name in published and published[name] != sha256(data):
                raise SystemExit(f'The release already has a different {name}. Published files are never replaced.')
    missing = [name for name in files if name not in published]
    print(('Release exists; ' if existing.returncode == 0 else 'Release will be created; ')
          + (('uploading ' + ', '.join(missing)) if missing else 'everything is already published') + '.')

    if not args.publish:
        print('Nothing changed. Run again with --publish to do this.')
        return
    if not remote:
        git('tag', '-a', tag, target, '-m', f'{args.runtime} runtime: patched Wine modules\n\n'
            f'The patches and the build script that reproduce {asset}\n(SHA-256 {expected}) byte for byte.')
        git('push', 'origin', 'refs/tags/' + tag)
    with tempfile.TemporaryDirectory() as temporary:
        paths = []
        for name in missing:
            path = Path(temporary) / name
            path.write_bytes(files[name])
            paths.append(str(path))
        if existing.returncode != 0:
            notes_file = Path(temporary) / 'notes.md'
            notes_file.write_text(notes)
            gh('release', 'create', tag, '--repo', repository, '--verify-tag', '--latest=false',
               '--title', f'{args.runtime} runtime: patched Wine modules', '--notes-file', str(notes_file), *paths)
        elif paths:
            gh('release', 'upload', tag, '--repo', repository, *paths)
    print('Published', f'https://github.com/{repository}/releases/tag/{tag}')


if __name__ == '__main__':
    main()
