#!/usr/bin/env python3
"""Check a built manager wheel in a disposable installation outside the checkout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
import tempfile
import re
import tomllib
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    root = Path(__file__).resolve().parents[1]
    package = root / 'plugg'
    expected = [*package.glob('*.py'), *package.glob('recipes/*.json'),
                *package.glob('recipes/community/*.toml'), *package.glob('leads/*/*.toml'),
                 *package.glob('assets/*')]
    expected_names = {path.relative_to(root).as_posix() for path in expected}
    # The version is written once, in plugg/__init__.py (pyproject.toml reads it).
    version = re.search(r'^__version__ = "(.+)"', (root / 'plugg/__init__.py').read_text(), re.M).group(1)
    metadata_root = 'plugg-' + version + '.dist-info'
    with zipfile.ZipFile(wheel) as archive:
        unexpected_roots = {name.split('/')[0] for name in archive.namelist()
                            if not name.startswith('plugg/')
                            and name.split('/')[0] != metadata_root}
        if unexpected_roots:
            raise ValueError('Unexpected wheel contents: ' + ', '.join(sorted(unexpected_roots)))
        actual = {name for name in archive.namelist() if name.startswith('plugg/') and not name.endswith('/')}
        if actual != expected_names:
            raise ValueError(f'Package contents differ: missing={sorted(expected_names - actual)}, extra={sorted(actual - expected_names)}')
        licenses = [name for name in archive.namelist() if name.endswith('.dist-info/licenses/LICENSE')]
        if len(licenses) != 1 or archive.read(licenses[0]) != (root / 'LICENSE').read_bytes():
            raise ValueError('Wheel must retain the project license')
        for path in expected:
            if archive.read(path.relative_to(root).as_posix()) != path.read_bytes():
                raise ValueError('Wheel differs from checkout: ' + str(path.relative_to(root)))
    references = set()
    for path in package.glob('recipes/community/*.toml'):
        data = tomllib.loads(path.read_text())
        references.add(f"{data['id']}@{data['revision']}")
    wheel_sha256 = hashlib.sha256(wheel.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='plugg-package-') as directory:
        temporary = Path(directory)
        env = dict(os.environ, XDG_CONFIG_HOME=str(temporary / 'config'),
                   XDG_DATA_HOME=str(temporary / 'data'), PYTHONDONTWRITEBYTECODE='1',
                   UV_NO_CONFIG='1', UV_LINK_MODE='copy')
        python = temporary / 'venv/bin/python'
        if shutil.which('uv'):
            subprocess.run(['uv', 'venv', '--python', sys.executable, str(temporary / 'venv')],
                           cwd=temporary, env=env, check=True)
            subprocess.run(['uv', 'pip', 'install', '--python', str(python), '--no-index', '--no-deps', str(wheel)],
                           cwd=temporary, env=env, check=True)
        else:
            # A CI runner has Python's own venv and pip, not uv. Same isolation:
            # no index, no dependencies, only the wheel under test.
            subprocess.run([sys.executable, '-m', 'venv', str(temporary / 'venv')], cwd=temporary, env=env, check=True)
            subprocess.run([str(python), '-m', 'pip', 'install', '--quiet', '--no-index', '--no-deps', str(wheel)],
                           cwd=temporary, env=env, check=True)

        def cli(*arguments):
            result = subprocess.run([str(python), '-I', '-m', 'plugg', 'recipe', *arguments],
                                    cwd=temporary, env=env, check=True, text=True, capture_output=True)
            return json.loads(result.stdout)

        checked = cli('check')
        if {item['reference'] for item in checked} != references:
            raise ValueError('Installed catalogue differs from source catalogue')
        bundled_leads = sum(len(tomllib.loads(path.read_text())['products'])
                            for path in package.glob('leads/*/*.toml'))
        if len(cli('leads', '--json')) != bundled_leads:
            raise ValueError('Installed recipe leads differ from the source leads')
        local = temporary / 'local-recipes'
        local.mkdir()
        (local / 'vendor.toml').write_text('''schema = 1
id = "local.package-test"
revision = 1
kind = "vendor"
name = "Package test"
vendor = "Local"
requires = ["plugg.graphics-wined3d@1"]
''')
        (local / 'helper.toml').write_text('''schema = 1
id = "local.package-helper"
revision = 1
kind = "vendor"
name = "Package helper"
requires = ["plugg.graphics-dxvk@1"]
[helper]
name = "Example Manager"
executable = "Program Files/Example/Manager.exe"
archive_tools = false
arguments = []
installer_sha256 = "''' + '0' * 64 + '"\n')
        extended = cli('check', '--recipe-dir', str(local))
        if {item['reference'] for item in extended} != references | {'local.package-test@1', 'local.package-helper@1'}:
            raise ValueError('Installed manager did not resolve the local extension')
        environment = temporary / 'environment'
        environment.mkdir()
        (environment / 'session.json').write_text(json.dumps({'graphics_backend': 'wined3d'}))
        status = cli('status', '--environment', str(environment))
        if status['requirements_match_record'] is not None or status['requirement_issues']:
            raise ValueError('Installed status must report absent requirement evidence as unknown')
        for name in ('config', 'data'):
            if (temporary / name).exists():
                raise ValueError('Read-only recipe checks created application ' + name)
        # Exercise the shipped console entry point, not the checkout or module shortcut.
        command = [str(temporary / 'venv/bin/plugg'), 'recipe', 'add',
                   str(local / 'helper.toml')]
        for added in (True, False):
            result = subprocess.run(command, cwd=temporary, env=env, check=True,
                                    text=True, capture_output=True)
            receipt = json.loads(result.stdout)
            destination = temporary / 'config/plugg/recipes/local.package-helper@1.toml'
            if receipt != {'reference': 'local.package-helper@1', 'added': added,
                           'path': str(destination)}:
                raise ValueError('Installed recipe add returned an unexpected receipt')
            if destination.read_bytes() != (local / 'helper.toml').read_bytes():
                raise ValueError('Installed recipe add did not preserve validated source bytes')
        if {item['reference'] for item in cli('check')} != references | {'local.package-helper@1'}:
            raise ValueError('Added recipe was not available to the installed manager')
        if (temporary / 'data').exists():
            raise ValueError('Recipe addition initialized the application library')
    print(json.dumps({'wheel_sha256': wheel_sha256,
                      'package_files': len(expected), 'builtin_recipes': len(references),
                      'local_extension': 'passed', 'helper_recipe': 'passed', 'status': 'passed',
                      'recipe_add_and_repeat': 'passed', 'library_state_created': False,
                      'config_created_only_by_add': True}, indent=2))


if __name__ == '__main__':
    main()
