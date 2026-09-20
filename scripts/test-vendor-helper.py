#!/usr/bin/env python3
"""Fresh, unauthenticated vendor helper installation through the normal recipe worker.

Never points at an existing store. Public cached archives may be copied by exact
filename; the production downloader still verifies their contents before use.
Does not sign in, activate products, or publish into the user's DAW folders.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from plugg import core, recipes, helper_component, vendors

parser = argparse.ArgumentParser()
parser.add_argument('--recipe', default='plugg.klevgrand@1')
parser.add_argument('--installer', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path, help='New directory, must not exist')
parser.add_argument('--cache', action='append', type=Path, default=[])
args = parser.parse_args()
root = args.output.resolve()
root.mkdir(parents=True, exist_ok=False)
os.environ['XDG_CONFIG_HOME'] = str(root / 'config')
store = core.Store(root / 'library', root / 'published', bridge_dir=ROOT / 'bundle/bridge')
update = store.update

def progress(job, status, message, **extra):
    print(status + ': ' + message, flush=True)
    return update(job, status, message, **extra)

store.update = progress
spec = recipes.recipe()
(store.root / 'downloads').mkdir(exist_ok=True)
from plugg import powershell_component
for asset in spec['runtimes'] + spec['packages'] + [powershell_component.ASSET]:
    filename = asset['sha256'] + '-' + Path(urlsplit(asset['url']).path).name
    for cache in args.cache:
        source = cache / filename
        if not source.is_file():
            source = cache / Path(urlsplit(asset['url']).path).name
        if source.is_file() and not source.is_symlink():
            shutil.copyfile(source, store.root / 'downloads' / filename)
            break
job = store.ingest(args.installer)
saved = json.loads((store.root / 'jobs' / job / 'helper-recipe.json').read_text())
assert saved['reference'] == args.recipe
core.work(store, job)
assert store.job(job)['status'] == 'ready'
prefix = store.prefix(job)
helper = helper_component.installed_binary(prefix, {
    key: saved['helper'][key] for key in ('name', 'executable', 'archive_tools')})
if saved['helper']['archive_tools']:
    assert (prefix / 'drive_c/Plugg/Tools/Archive/tar.exe').is_file()
assert not store.plugins(), 'No vendor products should be installed by this test'
card, = vendors.cards(store)
assert card['can_refresh'] and card['vendor'] == saved['vendor']
result = {'schema': 1, 'recipe': saved['reference'], 'installer_sha256': store.job(job)['hash'],
          'status': 'ready', 'helper_sha256': core.digest(helper),
          'prefix': str(prefix), 'library': str(store.root), 'job': job,
          'scope': 'Fresh helper install, extraction tools and refresh-capable card. No login, activation or product UI validation.'}
(root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2), flush=True)
