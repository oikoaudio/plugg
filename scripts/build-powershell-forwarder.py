#!/usr/bin/env python3
"""Build our small PowerShell launcher offline from checked-in Go source."""
import hashlib,json,os,subprocess,shutil
from pathlib import Path
root=Path(__file__).resolve().parents[1]
source=root/'components/powershell-forwarder/main.go'
out=root/'bundle/powershell-forwarder'
out.mkdir(parents=True,exist_ok=True)
for arch,name in [('amd64','powershell64.exe'),('386','powershell32.exe')]:
 subprocess.run(['go','build','-trimpath','-buildvcs=false','-ldflags=-s -w','-o',str(out/name),str(source)],
                env=dict(os.environ,GOOS='windows',GOARCH=arch,CGO_ENABLED='0',GOPROXY='off',GOSUMDB='off'),check=True)
shutil.copyfile(root/'LICENSE',out/'LICENSE.forwarder')
go_root=Path(subprocess.check_output(['go','env','GOROOT'],text=True).strip())
notice=next((p for p in (go_root/'LICENSE',Path('/usr/share/licenses/go/LICENSE')) if p.is_file()),None)
if notice is None: raise SystemExit('Go toolchain licence notice is missing')
shutil.copyfile(notice,out/'LICENSE.Go')
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
(out/'build.json').write_text(json.dumps({'source_sha256':digest(source),'compiler':subprocess.check_output(['go','version'],text=True).strip(),
 'files':{p.name:digest(p) for p in out.iterdir() if p.name!='build.json'}},indent=2)+'\n')
