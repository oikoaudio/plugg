#!/usr/bin/env python3
"""Opt-in real Wine service test; never copies a vendor prefix or account state.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import argparse, json, os, shlex, subprocess, tempfile, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plugg import core, softube_setup, softube, vendors
parser=argparse.ArgumentParser(description='Register Softube service in a disposable prefix without PACE or account data.')
parser.add_argument('--runtime-environment', type=Path, required=True, help='Read only its session and launcher configuration')
parser.add_argument('--service', type=Path, required=True, help='Verified extracted InstallerService.exe')
args=parser.parse_args()
source=args.runtime_environment.resolve()
root=Path(tempfile.mkdtemp(prefix='plugg-softube-service-fixture-'))
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
assert softube_setup.service_status(root)=='absent'
service=softube_setup.destination_path(root,softube.SERVICE);service.parent.mkdir(parents=True)
service.write_bytes(args.service.read_bytes())
assert core.digest(service)==softube_setup.softube_payload.SERVICE_SHA256
print('Registering reviewed service without PACE or account state',flush=True)
first=softube_setup.register_service(root)
repeat=softube_setup.register_service(root)
result={'first_registered':first,'repeat_registered':repeat,'service_status':softube_setup.service_status(root),'remaining_programs':vendors.running_programs(root/'prefix')}
core.atomic_json(root/'result.json',result)
print(json.dumps(result),flush=True)
