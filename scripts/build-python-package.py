#!/usr/bin/env python3
"""Build the manager wheel from an isolated, explicitly selected source tree.

Never clean the checkout's build directory: it also contains native artifacts.
"""
import argparse
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('dist'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='plugg-wheel-source-') as temp:
        source = Path(temp)
        for name in ('pyproject.toml', 'LICENSE'):
            shutil.copy2(root / name, source / name)
        package = root / 'plugg'
        files = [*package.glob('*.py'), *package.glob('recipes/*.json'),
                 *package.glob('recipes/community/*.toml'), *package.glob('leads/*/*.toml'),
                 *package.glob('assets/*')]
        for path in files:
            if not path.is_file() or path.is_symlink():
                raise ValueError('Unsupported package source: ' + str(path))
            target = source / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        if shutil.which('uv'):
            subprocess.run(['uv', '--no-config', 'build', '--wheel', '--out-dir', str(output), str(source)], check=True)
        else:
            # Distribution builds (makepkg) have the build backend installed and no network.
            subprocess.run([sys.executable, '-m', 'build', '--wheel', '--no-isolation', '--outdir', str(output),
                            str(source)], check=True)


if __name__ == '__main__':
    main()
