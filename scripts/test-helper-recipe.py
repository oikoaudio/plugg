#!/usr/bin/env python3
"""Real Windows helper recipe, publication and audio check in a fresh library."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if '--installed' not in sys.argv:
    sys.path.insert(0, str(ROOT))
from plugg import core, recipes, vendors, proton_session

parser = argparse.ArgumentParser()
parser.add_argument('--installed', action='store_true', help='Use the installed manager package instead of the checkout')
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--bridge', type=Path, required=True)
parser.add_argument('--vc-runtime', action='store_true', help='Install the pinned VC2013 component before the fixture helper')
args = parser.parse_args()
if args.installed and Path(core.__file__).resolve().is_relative_to(ROOT):
    parser.error('--installed resolved the checkout instead of an installed package')
runtime, bridge = args.runtime.resolve(), args.bridge.resolve()
for relative in ('UMU-Proton-10.0-4/proton', 'umu/umu-run', 'runtime/umu/steamrt3/_v2-entry-point'):
    if not (runtime / relative).is_file():
        parser.error('Missing runtime artifact: ' + relative)
manifest = json.loads((bridge / 'build.json').read_text())
for name, expected in manifest['files'].items():
    if core.digest(bridge / name) != expected:
        parser.error('Bridge artifact differs: ' + name)
installer = ROOT / 'build/fixtures/Install-Test-Helper.exe'
if not installer.is_file():
    parser.error('Run scripts/build-fixture.sh first')
root = ROOT / '.test-helper-recipe' / uuid.uuid4().hex
local = root / 'config/plugg/recipes'
local.mkdir(parents=True)
(local / 'helper.toml').write_text('''schema=1
id="local.helper-fixture"
revision=1
kind="vendor"
name="Helper fixture"
vendor="Plugg Tests"
requires=["plugg.graphics-dxvk@1"]
[helper]
name="Fixture Helper"
executable="Program Files/Plugg Fixture/Helper.exe"
archive_tools=false
arguments=["--install-fixture"]
installer_sha256="''' + core.digest(installer) + '"\n')
if args.vc_runtime:
    recipe_path = local / 'helper.toml'
    recipe_path.write_text(recipe_path.read_text().replace('"plugg.graphics-dxvk@1"',
        '"plugg.graphics-dxvk@1", "plugg.vc2013-x64@1"'))
store = core.Store(root / 'library', root / 'published', bridge_dir=bridge)
update = store.update
def progress(job, status, message, **extra):
    print(status + ': ' + message, flush=True)
    return update(job, status, message, **extra)
store.update = progress
print('Isolated helper test:', root, flush=True)
job = None

def wait_for_apps():
    deadline = time.monotonic() + 30
    while vendors.applications(store.prefix(job)):
        if time.monotonic() >= deadline:
            raise RuntimeError('Fixture applications did not finish')
        time.sleep(.2)

try:
    with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(root / 'config')}), patch.object(recipes, 'provision', return_value=runtime):
        job = store.ingest(installer)
        core.work(store, job)
    if store.job(job)['status'] != 'ready':
        raise RuntimeError('Helper setup did not finish')
    card, = vendors.cards(store)
    plugin, = store.plugins()
    published = Path(plugin['publication'])
    native = published / 'Contents/x86_64-linux' / (published.stem + '.so')
    output = root / 'audio.json'
    rc = core.run_process([bridge / 'plugg-scan', native, output, '--audio'],
                          os.environ.copy(), root / 'audio.log', timeout=30)
    if rc or not json.loads(output.read_text()).get('audio_fixture_passed'):
        raise RuntimeError('Published fixture failed audio check')
    wait_for_apps()
    proton_session.stop_idle_session(store.prefix(job).parent / 'session.json')
    # Exercise the installed helper launch files, then the normal completion scan.
    vendors.work(store, job)
    if len(store.plugins()) != 1:
        raise RuntimeError('Helper completion duplicated publication')
    core.atomic_json(root / 'results.json', {
        'passed': True, 'installed_package': args.installed,
        'bridge_selection': store.bridge_selection, 'installer_sha256': core.digest(installer),
        'audio': json.loads(output.read_text()), 'helper_card': card,
        'helper_record': json.loads((store.root / 'jobs' / job / 'helper-recipe.json').read_text()),
        'setup_state': json.loads((store.root / 'jobs' / job / 'helper-setup.json').read_text()),
        'bridge': manifest, 'helper_reopen_completed': True, 'publication_count': 1,
        'runtime_files': {name: core.digest(runtime / name) for name in
                          ('UMU-Proton-10.0-4/proton', 'umu/umu-run', 'runtime/umu/steamrt3/_v2-entry-point')},
        'session_manager_sha256': core.digest(Path(proton_session.__file__)),
        'vc_files': {name: core.digest(store.prefix(job) / 'drive_c/windows/system32' / name)
                     for name in ('msvcr120.dll', 'msvcp120.dll')} if args.vc_runtime else {},
        'runtime_acquisition_tested': False, 'vendor_plugins_tested': False})
    print('Real helper recipe passed:', root / 'results.json', flush=True)
finally:
    if job is not None:
        config = store.prefix(job).parent / 'session.json'
        if config.exists():
            original_error = sys.exc_info()[0]
            try:
                wait_for_apps()
                proton_session.stop_idle_session(config)
            except Exception as exc:
                if original_error:
                    print('Fixture cleanup also failed:', exc, file=sys.stderr)
                else:
                    raise
