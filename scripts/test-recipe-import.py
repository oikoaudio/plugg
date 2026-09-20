#!/usr/bin/env python3
"""Real direct-import/VC test in a new unactivated library, using cached runtime artifacts."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from plugg import core, recipes, standalone, proton_session, vendors

parser = argparse.ArgumentParser()
parser.add_argument('--runtime', type=Path, required=True, help='Existing runtime artifact root, not a prefix')
parser.add_argument('--bridge', type=Path, required=True)
args = parser.parse_args()
runtime, bridge = args.runtime.resolve(), args.bridge.resolve()
for relative in ('UMU-Proton-10.0-4/proton', 'umu/umu-run', 'runtime/umu/steamrt3/_v2-entry-point'):
    if not (runtime / relative).is_file():
        parser.error('Runtime artifact missing: ' + relative)
manifest = json.loads((bridge / 'build.json').read_text())
for name, expected in manifest['files'].items():
    if core.digest(bridge / name) != expected:
        parser.error('Bridge artifact differs: ' + name)
fixture = ROOT / 'build/fixtures/Gain.vst3'
if not fixture.is_file():
    parser.error('Build the gain fixture first')
root = ROOT / '.test-recipe-import' / uuid.uuid4().hex
local = root / 'config/plugg/recipes'
local.mkdir(parents=True)
fingerprint = core.digest(fixture)
(local / 'gain.toml').write_text(
    'schema=1\nid="local.gain-fixture"\nrevision=1\nkind="vendor"\n'
    'name="Gain import fixture"\nvendor="Plugg Tests"\n'
    'requires=["plugg.graphics-dxvk@1","plugg.vc2013-x64@1"]\n'
    f'[modules."{fingerprint}"]\nname="Test Gain"\ndependency="plugg.vc2013-x64@1"\n'
)
store = core.Store(root / 'library', root / 'published')
store.bridge = lambda: bridge
update = store.update
def progress(job, status, message, **extra):
    print(status + ': ' + message, flush=True)
    return update(job, status, message, **extra)
store.update = progress
job = store.ingest(fixture)
print('Isolated import:', root, flush=True)
def wait_for_fixture_apps():
    deadline = time.monotonic() + 30
    while vendors.applications(store.prefix(job)):
        if time.monotonic() >= deadline:
            raise RuntimeError('Fixture Windows applications did not finish')
        time.sleep(0.2)

try:
    with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(root / 'config')}), patch.object(recipes, 'provision', return_value=runtime):
        standalone.work(store, job)
    assert store.job(job)['status'] == 'ready'
    plugin, = store.plugins()
    published = Path(plugin['publication'])
    native = published / 'Contents/x86_64-linux' / (published.stem + '.so')
    output = root / 'audio.json'
    rc = core.run_process([bridge / 'plugg-scan', native, output, '--audio'],
                          os.environ.copy(), root / 'audio.log', timeout=30)
    assert rc == 0, 'Audio scan failed: ' + str(rc)
    audio = json.loads(output.read_text())
    assert audio['audio_fixture_passed']
    prefix = store.prefix(job)
    components = {name: core.digest(prefix / 'drive_c/windows/system32' / name)
                  for name in ('msvcr120.dll', 'msvcp120.dll')}
    wait_for_fixture_apps()
    with patch.object(recipes, 'provision', side_effect=AssertionError('Rescan reprovisioned runtime')),          patch('plugg.artifacts.fetch', side_effect=AssertionError('Rescan fetched a component')):
        standalone.work(store, job, rescan=True)
    assert len(store.plugins()) == 1
    result = {'passed': True, 'input_sha256': fingerprint, 'audio': audio,
              'component_files': components,
              'recipe': json.loads((store.root / 'jobs' / job / 'recipe-lock.json').read_text()),
              'import_state': json.loads((store.root / 'jobs' / job / 'import-state.json').read_text()),
              'dependencies': json.loads((prefix.parent / 'dependencies.json').read_text()),
              'bridge': manifest, 'session_manager_sha256': core.digest(Path(proton_session.__file__)),
              'runtime_acquisition_tested': False, 'vendor_plugins_tested': False,
              'rescan_idempotent': True}
    core.atomic_json(root / 'results.json', result)
    print('Real recipe import passed:', root / 'results.json', flush=True)
finally:
    config = store.prefix(job).parent / 'session.json'
    if config.exists():
        original_error = sys.exc_info()[0]
        try:
            wait_for_fixture_apps()
            proton_session.stop_idle_session(config)
        except Exception as exc:
            if original_error:
                print('Fixture cleanup also failed:', exc, file=sys.stderr)
            else:
                raise
