#!/usr/bin/env python3
"""Opt-in real Wine service test; never copies a vendor prefix or account state.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import argparse, json, os, shlex, subprocess, tempfile, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plugg import core, softube_setup, softube, vendors, ua_setup, ua_connect, windows_service, archive_component, recipes
parser=argparse.ArgumentParser(description='Stage UA Connect, shared archive tools and its service in a disposable prefix without PACE or account data.')
parser.add_argument('--runtime-environment', type=Path, required=True, help='Read only its session and launcher configuration')
parser.add_argument('--installer', type=Path, required=True, help='Original reviewed UA Connect installer')
args=parser.parse_args()
source=args.runtime_environment.resolve()
root=Path(tempfile.mkdtemp(prefix='plugg-ua-service-fixture-'))
# A failure retains this unlicensed fixture and its log for inspection.
cfg=json.loads((source/'session.json').read_text())
runtime=Path(cfg['proton']).parent
view=root/'proton-desktop';view.mkdir()
for item in runtime.iterdir():
 if item.name not in ('proton','__pycache__'): (view/item.name).symlink_to(item)
(view/'proton').write_text((source/'proton-desktop/proton').read_text());(view/'proton').chmod(0o700)
launcher=root/'launch-full-proton'
launcher.write_text((source/'launch-full-proton').read_text().replace('export WINEPREFIX='+str(source/'prefix'),'export WINEPREFIX='+shlex.quote(str(root/'prefix'))).replace('export PROTONPATH='+str(source/'proton-desktop'),'export PROTONPATH='+shlex.quote(str(view))))
expected_prefix='export WINEPREFIX='+shlex.quote(str(root/'prefix'))
expected_runtime='export PROTONPATH='+shlex.quote(str(view))
assert launcher.read_text().splitlines().count(expected_prefix)==1, 'Unsupported source launcher; no Windows process started'
assert launcher.read_text().splitlines().count(expected_runtime)==1, 'Unsupported runtime launcher; no Windows process started'
assert str(source/'prefix') not in launcher.read_text(), 'Source prefix must not reach fixture launcher'
launcher.chmod(0o700)
core.atomic_json(root/'session.json', {'prefix':str(root/'prefix'),'proton':cfg['proton'],'runtime_entry':cfg['runtime_entry'],'idle_seconds':3})
print('Fresh unlicensed fixture:',root,flush=True)
with (root/'bootstrap.log').open('w') as log:
 child=subprocess.run([str(launcher),'cmd.exe','/c','exit','0'],stdout=log,stderr=log,timeout=120)
 if child.returncode: raise RuntimeError('Bootstrap failed')
softube.prepare(root)

from types import SimpleNamespace
from urllib.parse import urlsplit
import shutil
app=root/'prefix/drive_c/Program Files/UA Connect'
ua_setup.stage(args.installer,app)
cache=root/'downloads';cache.mkdir()
for asset in recipes.recipe()['packages']:
    name=asset['sha256']+'-'+urlsplit(asset['url']).path.rsplit('/',1)[-1]
    cached=source.parent.parent/'downloads'/name
    if cached.is_file(): shutil.copyfile(cached,cache/name)
archive_component.install(SimpleNamespace(root=root),root/'prefix',recipes.recipe()['packages'],print,lambda:None)
assert ua_setup.service_status(root)=='absent'
first=windows_service.register(root,ua_setup.SERVICE_SPEC,prepare=ua_connect.prepare_runtime)
repeat=windows_service.register(root,ua_setup.SERVICE_SPEC,prepare=ua_connect.prepare_runtime)
# Only configure the launcher; do not open the app or initiate PACE downloads.
ua_connect.configure(root,allow_electron_no_sandbox=True)
result={'first_registered':first,'repeat_registered':repeat,'service_status':ua_setup.service_status(root),
        'archive_alias_matches':core.digest(root/'prefix/drive_c/Plugg/Tools/Archive/tar.exe')==core.digest(root/'prefix/drive_c/Plugg/Tools/Archive/bsdtar.exe'),
        'remaining_programs':vendors.running_programs(root/'prefix')}
core.atomic_json(root/'result.json',result)
print(json.dumps(result),flush=True)
