#!/usr/bin/env python3
"""Rebuild a runtime overlay's Wine modules from source, and check them.

    python3 scripts/build-runtime-overlay.py plugg-1 --container docker
    python3 scripts/build-runtime-overlay.py plugg-1            # host toolchain

Reads the build description in plugg/recipes/runtime-overlays.json:

1. fetches the Wine source archive at the exact revision UMU-Proton ships and
   checks its SHA-256;
2. applies the patches in this repository, each checked against its recorded
   hash;
3. generates what the source archive leaves out (autoreconf, the Vulkan and
   server protocol files), configures, and builds only the named modules;
4. links with the recorded timestamp (SOURCE_DATE_EPOCH), which is the only
   thing that otherwise differs between two builds;
5. compares every module with the SHA-256 recorded for the runtime.

With the recorded toolchain the result is byte-for-byte what `plugg runtime
assemble` downloads, so the published modules can be checked rather than
trusted. `--container` builds in an Arch Linux container whose packages come
from the Arch Linux Archive snapshot of the day the modules were first built,
which is the easiest way to get that toolchain. A different compiler version
produces working modules with different hashes; the script says which files
differ and `runtime assemble` will refuse them.

`--package FILE` also writes the deterministic release archive, which is how
the published archive was made.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / 'plugg' / 'recipes' / 'runtime-overlays.json'
PACKAGES = ['base-devel', 'clang', 'lld', 'llvm', 'perl', 'autoconf', 'flex', 'bison', 'python']


def digest(path):
    value = hashlib.sha256()
    with open(path, 'rb') as stream:
        while block := stream.read(1 << 20):
            value.update(block)
    return value.hexdigest()


def overlay(name):
    data = json.loads(SPEC.read_text())
    for spec in data['overlays']:
        if spec['name'] == name:
            if 'build' not in spec:
                sys.exit(name + ' has no build description')
            return spec
    sys.exit('No such runtime: ' + name)


def run(command, cwd, log=None, env=None):
    print('+ ' + ' '.join(str(part) for part in command) + ('  > ' + str(log) if log else ''), flush=True)
    if log:
        with open(log, 'w') as stream:
            result = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, env=env)
        if result.returncode:
            sys.stdout.write(''.join(Path(log).read_text().splitlines(True)[-30:]))
            sys.exit('Failed: ' + ' '.join(str(part) for part in command))
    else:
        subprocess.run(command, cwd=cwd, check=True, env=env)


def source_archive(build, work, given):
    wanted = build['source_archive']['sha256']
    path = Path(given) if given else work / ('wine-' + build['wine_revision'] + '.tar.gz')
    if not path.is_file():
        url = build['source_archive']['url']
        print('Downloading ' + url, flush=True)
        partial = path.with_suffix('.partial')
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Plugg'}), timeout=120) as response, \
                open(partial, 'wb') as stream:
            shutil.copyfileobj(response, stream)
        partial.replace(path)
    if digest(path) != wanted:
        sys.exit(str(path) + ' is not the recorded Wine source archive (SHA-256 ' + wanted + ')')
    return path


def tool_versions():
    versions = {}
    for name, command in (('clang', ['clang', '--version']), ('lld', ['ld.lld', '--version']),
                          ('autoconf', ['autoconf', '--version'])):
        try:
            versions[name] = subprocess.run(command, capture_output=True, text=True).stdout.splitlines()[0]
        except (OSError, IndexError):
            versions[name] = None
    return versions


def build_tree(spec, tree, archive, work, jobs):
    build = spec['build']
    root = work / tree['name']
    if root.exists():
        shutil.rmtree(root)
    source = root / tree['source_directory']
    source.mkdir(parents=True)
    run(['tar', 'xzf', str(archive), '-C', str(source), '--strip-components=1'], root)
    for entry in tree['patches']:
        patch = REPO / entry['patch']
        if digest(patch) != entry['sha256']:
            sys.exit(entry['patch'] + ' does not match its recorded SHA-256')
        with open(patch, 'rb') as stream:
            subprocess.run(['patch', '-p1', '-s', '--no-backup-if-mismatch'], cwd=source, stdin=stream, check=True)
    for index, step in enumerate(build['generate']):
        run(step['command'], source / step.get('directory', '.'), log=root / ('generate-' + str(index) + '.log'))
    objects = root / 'build'
    objects.mkdir()
    run([os.path.relpath(source / 'configure', objects), *tree['configure']], objects, log=root / 'configure.log')
    env = dict(os.environ, SOURCE_DATE_EPOCH=str(tree['source_date_epoch']))
    variables = [key + '=' + value.replace('{build}', str(objects)) for key, value in tree.get('make_variables', {}).items()]
    run(['make', '-j' + str(jobs), *tree['targets'], *variables], objects, log=root / 'make.log', env=env)
    return objects


def collect(spec, trees, output):
    output.mkdir(parents=True, exist_ok=True)
    results = {}
    for tree, objects in trees:
        for relative, built in tree['files'].items():
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                destination.unlink()
            if tree.get('strip_debug'):
                subprocess.run(['llvm-strip', '-g', '-o', str(destination), str(objects / built)], check=True)
            else:
                shutil.copyfile(objects / built, destination)
            expected = spec['files'][relative]['sha256']
            value = digest(destination)
            results[relative] = {'sha256': value, 'recorded': expected is not None,
                                 'matches': expected is not None and value == expected}
    return results


def package(spec, modules, archive):
    """The release archive: an uncompressed tar with sorted members and fixed owners, times and modes.

    Uncompressed so the archive's own hash does not depend on a compressor
    version; it is a few megabytes.
    """
    epoch = spec['build']['trees'][0]['source_date_epoch']
    with tarfile.open(archive, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for relative in sorted(spec['files']):
            data = (Path(modules) / relative).read_bytes()
            info = tarfile.TarInfo(relative)
            info.size, info.mtime, info.mode = len(data), epoch, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            tar.addfile(info, io.BytesIO(data))
    return digest(archive)


def container(args, spec):
    engine = shutil.which(args.container)
    if not engine:
        sys.exit(args.container + ' is not installed')
    snapshot = spec['build']['arch_linux_archive']
    work = Path(args.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    inner = ['python3', '/plugg/scripts/build-runtime-overlay.py', args.name, '--work', '/work', '--jobs', str(args.jobs)]
    for tree in args.tree:
        inner += ['--tree', tree]
    if args.output:
        Path(args.output).mkdir(parents=True, exist_ok=True)
        inner += ['--output', '/output']
    if args.package:
        Path(args.package).parent.mkdir(parents=True, exist_ok=True)
        inner += ['--package', '/package/' + Path(args.package).name]
    if args.source:
        inner += ['--source', '/source/' + Path(args.source).name]
    setup = ('set -e; '
             'echo "Server = https://archive.archlinux.org/repos/' + snapshot + '/\\$repo/os/\\$arch" > /etc/pacman.d/mirrorlist; '
             'if ls /etc/ca-certificates/trust-source/anchors/*.crt >/dev/null 2>&1; then update-ca-trust; fi; '
             'pacman -Syuu --noconfirm --needed ' + ' '.join(PACKAGES) + ' >/work/pacman.log 2>&1 '
             '|| { tail -20 /work/pacman.log; exit 1; }; '
             + ' '.join("'" + part + "'" for part in inner))
    command = [engine, 'run', '--rm', *args.container_option,
               '-v', str(REPO) + ':/plugg:ro', '-v', str(work) + ':/work']
    if args.output:
        command += ['-v', str(Path(args.output).resolve()) + ':/output']
    if args.package:
        command += ['-v', str(Path(args.package).resolve().parent) + ':/package']
    if args.source:
        command += ['-v', str(Path(args.source).resolve()) + ':/source/' + Path(args.source).name + ':ro']
    command += ['docker.io/library/archlinux:latest', 'sh', '-c', setup]
    return subprocess.run(command).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('name', help='Runtime overlay, e.g. plugg-1')
    parser.add_argument('--work', default=str(Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache'))
                                              / 'plugg' / 'runtime-build'),
                        help='Build directory (default: ~/.cache/plugg/runtime-build)')
    parser.add_argument('--output', help='Where to put the modules (default: WORK/NAME-modules)')
    parser.add_argument('--package', help='Also write the deterministic release archive here')
    parser.add_argument('--source', help='A local copy of the Wine source archive, checked against its hash')
    parser.add_argument('--jobs', type=int, default=os.cpu_count() or 2)
    parser.add_argument('--container', choices=('docker', 'podman'),
                        help='Build inside an Arch Linux container with the recorded toolchain')
    parser.add_argument('--container-option', action='append', default=[],
                        help='Extra option for the container engine (repeatable)')
    parser.add_argument('--tree', action='append', default=[],
                        help='Build only this source tree from the build description (repeatable). '
                             'Modules from the other trees are left alone and not compared.')
    args = parser.parse_args()
    spec = overlay(args.name)
    if args.container:
        return container(args, spec)
    build = spec['build']
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    versions = tool_versions()
    for name, recorded in build['toolchain'].items():
        if versions.get(name) != recorded:
            print('Note: ' + name + ' is ' + str(versions.get(name)) + '; the recorded build used ' + recorded
                  + '. The modules will work but their hashes will probably differ.', flush=True)
    wanted = build['trees']
    if args.tree:
        names = {tree['name'] for tree in wanted}
        missing = [name for name in args.tree if name not in names]
        if missing:
            sys.exit('No such tree in ' + args.name + ': ' + ', '.join(missing) + ' (have: ' + ', '.join(sorted(names)) + ')')
        wanted = [tree for tree in wanted if tree['name'] in args.tree]
    archive = source_archive(build, work, args.source)
    trees = [(tree, build_tree(spec, tree, archive, work, args.jobs)) for tree in wanted]
    output = Path(args.output) if args.output else work / (args.name + '-modules')
    results = collect(spec, trees, output)
    for relative, result in sorted(results.items()):
        state = 'identical  ' if result['matches'] else ('unrecorded ' if not result['recorded'] else 'DIFFERENT  ')
        print(state + relative + '  ' + result['sha256'])
    print('Modules in ' + str(output))
    if args.tree:
        print('Only ' + ', '.join(args.tree) + ' was built; this is not a complete set of modules for '
              + args.name + '.')
    unrecorded = {relative: result['sha256'] for relative, result in results.items() if not result['recorded']}
    if unrecorded and all(result['matches'] or not result['recorded'] for result in results.values()):
        print('\n' + args.name + ' is still a draft. Record these in plugg/recipes/runtime-overlays.json, '
              'then this build can be checked against them:')
        for relative, value in sorted(unrecorded.items()):
            print('  ' + relative + '  ' + value)
        return 0
    if all(result['matches'] for result in results.values()):
        print('Every module is byte-for-byte the one recorded for ' + args.name + '.')
        if args.package:
            value = package(spec, output, args.package)
            recorded = spec.get('release', {}).get('sha256')
            print('Release archive ' + args.package + '  ' + value
                  + ('  (identical to the published one)' if value == recorded else ''))
        return 0
    print('Some modules differ from the recorded ones, usually because of a different compiler version. '
          'runtime assemble accepts only the recorded bytes.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
