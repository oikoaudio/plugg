#!/usr/bin/env python3
"""Record observed build inputs, not a claim of bit-reproducible outputs."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess


ARTIFACTS = ('libyabridge-vst3.so', 'libyabridge-chainloader-vst3.so',
             'yabridge-host.exe', 'yabridge-host.exe.so', 'plugg-scan', 'COPYING.yabridge')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(root, build, output):
    def info(name):
        return json.loads((build / 'meson-info' / ('intro-' + name + '.json')).read_text())
    compilers = {
        machine: {language: {key: value[key] for key in ('id', 'version', 'full_version', 'linker_id') if key in value}
                  for language, value in group.items()}
        for machine, group in info('compilers').items()
    }
    # Meson names a dependency it was given no name for after a memory
    # address (dep140686460032512), which differs on every run. Those are
    # recorded as anonymous so that two builds of one commit match.
    dependencies = [{key: ('(anonymous)' if key == 'name' and re.fullmatch(r'dep[0-9]+', str(dep[key])) else dep[key])
                     for key in ('name', 'type', 'version') if key in dep}
                    for dep in info('dependencies')]
    options = {item['name']: item['value'] for item in info('buildoptions')
               if item['name'] in ('buildtype', 'bitbridge', 'clap', 'vst3', 'wrap_mode', 'cpp_std', 'build.cpp_std', 'b_lto', 'force_fallback_for')}
    # Compiler and linker arguments per machine, so a build made with a
    # packager's environment flags is visible in the record. The host machine
    # is the Wine side; `-march` there is what diagnostics/host-stack found.
    arguments = {item.get('machine', 'host') + '.' + item['name']: item['value'] for item in info('buildoptions')
                 if item['name'] in ('c_args', 'cpp_args', 'c_link_args', 'cpp_link_args')}
    source = root / 'vendor/yabridge'
    subprojects = []
    for item in info('projectinfo').get('subprojects', []):
        name = item['name']
        if not isinstance(name, str) or Path(name).name != name or name in ('.', '..'):
            raise ValueError('Invalid Meson subproject name')
        directory = source / 'subprojects' / name
        observed = {'name': name, 'meson_version': item.get('version')}
        if (directory / '.git').exists():
            observed['git_revision'] = subprocess.check_output(
                ['git', '-C', str(directory), 'rev-parse', 'HEAD'], text=True).strip()
            delta = subprocess.check_output(
                ['git', '-C', str(directory), 'diff', 'HEAD', '--binary'], text=True)
            observed['tracked_diff_sha256'] = hashlib.sha256(delta.encode()).hexdigest()
        if (directory / 'meson.build').is_file():
            observed['meson_build_sha256'] = digest(directory / 'meson.build')
        subprojects.append(observed)
    names = json.loads((root / 'patches/yabridge-series.json').read_text())
    if not names or len(names) != len(set(names)) or any(Path(name).name != name or not name.endswith('.patch') for name in names):
        raise ValueError('Invalid yabridge patch series')
    return {
        'upstream': 'https://github.com/robbert-vdh/yabridge',
        'revision': subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip(),
        'patches': {str(p.relative_to(root)): digest(p) for p in (root / 'patches' / name for name in names)},
        'files': {name: digest(output / name) for name in ARTIFACTS},
        'build_inputs': {
            'compilers': compilers, 'dependencies': dependencies, 'options': options, 'arguments': arguments,
            'subprojects': subprojects,
            'wine_version': subprocess.check_output(['wine', '--version'], text=True).strip(),
            'meson_version': subprocess.check_output(['meson', '--version'], text=True).strip(),
            'ninja_version': subprocess.check_output(['ninja', '--version'], text=True).strip(),
            'scanner_compiler': subprocess.check_output(['c++', '--version'], text=True).splitlines()[0],
            'source_files': {str(p.relative_to(root)): digest(p) for p in
                             [root / 'native/scan.cpp', root / 'scripts/build-bridge.sh', root / 'scripts/bridge-manifest.py', source / 'cross-wine.conf']},
            'wrap_files': {p.name: digest(p) for p in sorted((source / 'subprojects').glob('*.wrap'))},
            'limitations': 'Observed versions and source hashes; system headers and transitive dependencies are not fully pinned.',
        },
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = manifest(Path(__file__).resolve().parents[1], args.build, args.output)
    target = args.output / 'build.json'
    temporary = target.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(result, indent=2) + '\n')
    temporary.replace(target)
