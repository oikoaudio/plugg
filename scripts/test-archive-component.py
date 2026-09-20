#!/usr/bin/env python3
"""Exercise pinned archive packages in a disposable, unactivated prefix layout.

Downloads the package set into a disposable cache. Never launches Wine.
"""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plugg import archive_component, core, recipes


def main():
    assets = recipes.recipe()['packages']
    with tempfile.TemporaryDirectory(prefix='plugg-archive-check-') as temporary:
        root = Path(temporary)
        store = SimpleNamespace(root=root)
        prefix = root / 'environment/prefix'
        (prefix / 'drive_c').mkdir(parents=True)
        messages = set()
        def report(message):
            if message not in messages:
                print(message, flush=True)
                messages.add(message)
        archive_component.install(store, prefix, assets, report, lambda: None)
        archive = prefix / 'drive_c/Plugg/Tools/Archive'
        def snapshot():
            return {str(path.relative_to(prefix.parent)): core.digest(path)
                    for path in prefix.parent.rglob('*') if path.is_file()}
        original = snapshot()
        archive_component.install(store, prefix, assets, report, lambda: None)
        if snapshot() != original:
            raise RuntimeError('Repeated preparation changed installed contents')
        if core.digest(archive / 'tar.exe') != core.digest(archive / 'bsdtar.exe'):
            raise RuntimeError('tar alias differs from bsdtar')
        notices = list((prefix.parent / 'component-licenses').rglob('*'))
        if not any(path.is_file() for path in notices):
            raise RuntimeError('No license notices retained')
        print(json.dumps({'packages': len(assets), 'binaries': len(list(archive.iterdir())),
                          'installed_files': len(original), 'repeat_unchanged': True,
                          'wine_started': False, 'files': original}, indent=2))


if __name__ == '__main__':
    main()
