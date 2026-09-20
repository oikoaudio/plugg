#!/usr/bin/env python3
"""Exercise an installed wheel and explicit bridge without checkout imports.

Run only in the dedicated packaging container, as its unprivileged test user.
No mocks, host caches, vendor software or account data are used.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from plugg import core, recipes, vendors, proton_session

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bridge', type=Path, required=True)
parser.add_argument('--installer', type=Path, required=True)
parser.add_argument('--root', type=Path, required=True)
args = parser.parse_args()
root = args.root.resolve()
root.mkdir(parents=True, exist_ok=False)
assert 'site-packages' in Path(core.__file__).parts, 'Checkout imports are forbidden'
assert os.getuid() != 0, 'Run the fixture as the ordinary test user'
os.environ.update(XDG_CONFIG_HOME=str(root / 'config'), XDG_DATA_HOME=str(root / 'data'))
local = root / 'config/plugg/recipes'
local.mkdir(parents=True)
(local / 'fixture.toml').write_text('''schema=1
id="local.container-fixture"
revision=1
kind="vendor"
name="Container fixture"
vendor="Plugg Tests"
requires=["plugg.graphics-dxvk@1"]
[helper]
name="Fixture Helper"
executable="Program Files/Plugg Fixture/Helper.exe"
archive_tools=false
arguments=["--install-fixture"]
installer_sha256="''' + core.digest(args.installer) + '"\n')
store = core.Store(root / 'library', root / 'published', bridge_dir=args.bridge)
result = {'passed': False, 'installed_module': str(core.__file__), 'python': sys.version,
          'uid': os.getuid(), 'cached_runtime_supplied': False, 'vendor_software_used': False}
try:
    runtime = recipes.provision(store, lambda msg: print(msg, flush=True), lambda: None)
    result['runtime_acquisition_passed'] = True
    result['runtime_manifest'] = json.loads((runtime / 'runtime.json').read_text())
    job = store.ingest(args.installer)
    print('Installing synthetic helper:', job, flush=True)
    core.work(store, job)
    result['job'] = store.job(job)
    if result['job']['status'] != 'ready':
        raise RuntimeError('Synthetic helper setup failed: ' + str(result['job'].get('message')))
    plugin, = store.plugins()
    published = Path(plugin['publication'])
    native = published / 'Contents/x86_64-linux' / (published.stem + '.so')
    output = root / 'audio.json'
    rc = core.run_process([args.bridge / 'plugg-scan', native, output, '--audio'],
                          os.environ.copy(), root / 'audio.log', timeout=60)
    if rc or not json.loads(output.read_text()).get('audio_fixture_passed'):
        raise RuntimeError('Published fixture failed audio validation')
    result['audio'] = json.loads(output.read_text())
    proton_session.stop_idle_session(store.prefix(job).parent / 'session.json')
    vendors.work(store, job)
    assert len(store.plugins()) == 1, 'Helper reopening duplicated the plug-in'
    result.update(passed=True, helper_reopen_completed=True, publication_count=1)
except Exception as exc:
    result['error'] = str(exc)
    raise
finally:
    core.atomic_json(root / 'result.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('runtime_manifest', 'job')}, indent=2), flush=True)
