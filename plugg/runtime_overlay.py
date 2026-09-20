"""One runtime with this project's Wine fixes built in, for new environments.

The fixes are a handful of Wine modules rebuilt from the exact source revision
of UMU-Proton 10.0-4 (see patches/wine/series.json and the ole32 provenance).
Assembling puts them into a new, separately named copy of that Proton build;
nothing existing is modified. The copy shares unchanged files with the base by
hard link where the filesystem allows, so it costs a few megabytes, and each
replaced file is unlinked first, so the base keeps its own bytes.

An environment chooses its runtime once, when it is created. Moving an
existing environment to another runtime is a `replace_runtime` operation,
which a protected (licensed) environment refuses without the user's explicit
acknowledgement: Proton rewrites Windows files inside the prefix when its
runtime changes, and a licensing system may count that as a different
machine. The shared iLok environment stays on the runtime it was activated on.

SPDX-License-Identifier: GPL-3.0-or-later
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from . import artifacts, core

SPEC = Path(__file__).resolve().parent / 'recipes' / 'runtime-overlays.json'
MANIFEST = 'plugg-build.json'
SETTING = 'new_environment_runtime'
WINE_LIB = Path('files/lib/wine')


def overlays():
    data = json.loads(SPEC.read_text())
    if data.get('schema') != 1:
        raise core.HostError('Unsupported runtime overlay description')
    for spec in data['overlays']:
        if 'identity' in spec and spec.get('content_sha256') != content_digest(spec):
            raise core.HostError('The modules or base of runtime ' + spec['name'] + ' changed after it was named. '
                                 'Assembled copies and the environments on them expect the recorded bytes; '
                                 'describe the change as a new runtime instead.')
    return {overlay['name']: overlay for overlay in data['overlays']}


def overlay(name):
    known = overlays()
    if name not in known:
        raise core.HostError('No such runtime: ' + name + ' (known: ' + ', '.join(sorted(known)) + ')')
    return known[name]


def content_digest(spec):
    """What the assembled runtime consists of: its name, its base and the replacement files.

    Notes, validation records and build instructions are not part of it, so
    documenting a runtime never renames the directory environments point at.
    """
    content = {key: spec[key] for key in ('name', 'base', 'files')}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def identity(spec):
    """The short identity in the runtime's directory name.

    A published runtime records it, frozen at its first assembly, together with
    content_sha256; overlays() refuses a description whose content no longer
    matches. An unrecorded description derives it from its content.
    """
    return spec.get('identity') or content_digest(spec)[:12]


def directory_name(spec):
    return 'proton-10.0-4-' + spec['name'] + '-' + identity(spec)


def check_artifacts(spec, artifacts):
    """Every replacement file present with its recorded hash; nothing is trusted by name."""
    artifacts = Path(artifacts)
    problems = []
    for relative, entry in sorted(spec['files'].items()):
        path = artifacts / relative
        if not path.is_file() or path.is_symlink():
            problems.append('missing ' + relative)
        elif core.digest(path) != entry['sha256']:
            problems.append(relative + ' has a different SHA-256 than the one recorded for ' + entry['patch'])
    if problems:
        raise core.HostError('The built Wine modules do not match this runtime description:\n  ' + '\n  '.join(problems))


def check_base(spec, base):
    base = Path(base)
    proton = base / 'proton'
    if not proton.is_file():
        raise core.HostError('Not a Proton build (no proton script): ' + str(base))
    if core.digest(proton) != spec['base']['proton_sha256']:
        raise core.HostError(str(base) + ' is not the ' + spec['base']['release'] + ' build this runtime is made from.')
    for relative in spec['files']:
        if not (base / WINE_LIB / relative).is_file():
            raise core.HostError('Base runtime has no ' + str(WINE_LIB / relative))


def _link_tree(source, target):
    """Copy a tree, hard-linking regular files when possible. Symlinks are kept as links."""
    for root, directories, files in os.walk(source):
        here = Path(root)
        destination = target / here.relative_to(source)
        destination.mkdir(exist_ok=True)
        shutil.copystat(here, destination)
        for name in [*directories, *files]:
            path = here / name
            if path.is_symlink():
                (destination / name).symlink_to(os.readlink(path))
                if name in directories:
                    directories.remove(name)
            elif name in files:
                try:
                    os.link(path, destination / name)
                except OSError:
                    shutil.copy2(path, destination / name)


def download_modules(store, spec, destination, report=print, check=lambda: None):
    """Fetch the published modules for a runtime and unpack them into destination.

    The archive is pinned by SHA-256 in the runtime description, comes only
    from this project's GitHub releases, and every module in it is checked
    again by assemble(). scripts/build-runtime-overlay.py rebuilds the same
    bytes from source for anyone who would rather not download them.
    """
    release = spec.get('release')
    if not release:
        raise core.HostError(spec['name'] + ' has no published modules; build them with '
                             'scripts/build-runtime-overlay.py and pass --artifacts.')
    archive = artifacts.fetch(store, release, report, check, artifacts.RUNTIME_RELEASES)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    core.safe_extract(archive, destination, check)
    return destination


def plan(spec, base, runtimes):
    base, runtimes = Path(base).resolve(), Path(runtimes)
    return {'runtime': spec['name'], 'base': str(base), 'target': str(runtimes / directory_name(spec)),
            'replaces': {str(WINE_LIB / relative): entry['sha256'] for relative, entry in sorted(spec['files'].items())},
            'changes_existing_files': False}


def assemble(spec, base, artifacts, runtimes):
    """Create the runtime beside the others. Returns its directory; repeating is a no-op."""
    base, runtimes = Path(base).resolve(), Path(runtimes)
    check_base(spec, base)
    check_artifacts(spec, artifacts)
    target = runtimes / directory_name(spec)
    if target.exists():
        verify(spec, target)
        return target
    runtimes.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=runtimes, prefix='.assemble-' + spec['name'] + '-') as temporary:
        stage = Path(temporary) / 'proton'
        _link_tree(base, stage)
        replaced = {}
        for relative, entry in sorted(spec['files'].items()):
            destination = stage / WINE_LIB / relative
            replaced[str(WINE_LIB / relative)] = {'base_sha256': core.digest(destination), 'sha256': entry['sha256'],
                                                  'patch': entry['patch']}
            destination.unlink()
            shutil.copy2(Path(artifacts) / relative, destination)
        core.atomic_json(stage / MANIFEST, {
            'schema': 1, 'runtime': spec['name'], 'identity': identity(spec), 'base': spec['base'],
            'base_directory': str(base), 'files': replaced, 'purpose': spec['purpose'],
            'not_yet_tested': spec.get('not_yet_tested', [])})
        verify(spec, stage)
        stage.rename(target)
    return target


def verify(spec, target):
    target = Path(target)
    manifest_path = target / MANIFEST
    if not manifest_path.is_file():
        raise core.HostError(str(target) + ' has no build record; it was not assembled by this tool.')
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('runtime') != spec['name'] or manifest.get('identity') != identity(spec):
        raise core.HostError(str(target) + ' was assembled from a different description.')
    if core.digest(target / 'proton') != spec['base']['proton_sha256']:
        raise core.HostError(str(target / 'proton') + ' has changed since assembly.')
    for relative, entry in spec['files'].items():
        path = target / WINE_LIB / relative
        if not path.is_file() or core.digest(path) != entry['sha256']:
            raise core.HostError(str(path) + ' has changed since assembly.')
    return manifest


def _settings(store_root):
    path = Path(store_root) / 'settings.json'
    return json.loads(path.read_text()) if path.is_file() else {}


def select_for_new_environments(store_root, name):
    """Record which runtime new environments get. None returns to the plain base."""
    path = Path(store_root) / 'settings.json'
    settings = _settings(store_root)
    if name is None:
        settings.pop(SETTING, None)
    else:
        spec = overlay(name)
        verify(spec, Path(store_root) / 'runtimes' / directory_name(spec))
        settings[SETTING] = name
    core.atomic_json(path, settings)
    return settings.get(SETTING)


def proton_for_new_environment(store_root, base_proton):
    """The Proton directory a new environment should use: the selected overlay, or the base."""
    name = _settings(store_root).get(SETTING)
    if not name:
        return Path(base_proton)
    spec = overlay(name)
    target = Path(store_root) / 'runtimes' / directory_name(spec)
    verify(spec, target)
    return target


def inventory(store_root):
    """Which runtimes exist and which environments use each. Reads only."""
    root = Path(store_root)
    users = {}
    for session in sorted((root / 'environments').glob('*/session.json')):
        try:
            proton = json.loads(session.read_text()).get('proton', '')
        except (OSError, ValueError):
            continue
        users.setdefault(str(Path(proton).parent), []).append(session.parent.name)
    known = {directory_name(spec): name for name, spec in overlays().items()}
    result = []
    for path in sorted((root / 'runtimes').iterdir()) if (root / 'runtimes').is_dir() else []:
        if path.name.startswith('.'):
            continue
        candidates = {str(path), str(path / 'UMU-Proton-10.0-4'), str(path.resolve()),
                      str(path.resolve() / 'UMU-Proton-10.0-4')}
        result.append({'directory': path.name, 'overlay': known.get(path.name),
                       'environments': sorted({e for key in candidates for e in users.get(key, [])})})
    return {'new_environments': _settings(root).get(SETTING) or 'base UMU-Proton-10.0-4', 'runtimes': result}
