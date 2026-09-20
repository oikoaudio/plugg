#!/usr/bin/env python3
"""Diagnose independent Proton plugin instances; never touches vendor prefixes.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import atexit, argparse, hashlib, socket, struct, concurrent.futures, json, os, shlex, signal, subprocess, sys, time, uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from plugg import core

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bridge', type=Path, help='Use a separate bridge build without changing deployed publications')
    ap.add_argument('--copy-runtime', choices=['0','1'], default='1')
    ap.add_argument('--rounds', type=int, default=3)
    ap.add_argument('--hold-ms', type=int, default=0)
    ap.add_argument('--session', action='store_true')
    ap.add_argument('--survival', action='store_true')
    ap.add_argument('--dxvk', action='store_true', help='Verify explicit prepared DXVK selection in the managed session')
    ap.add_argument('--managed-session', action='store_true', help='Test automatic persistent session startup')
    a=ap.parse_args()
    if a.bridge:
        a.bridge=a.bridge.resolve()
        manifest=json.loads((a.bridge/'build.json').read_text())
        for name in ('libyabridge-vst3.so','libyabridge-chainloader-vst3.so','yabridge-host.exe','yabridge-host.exe.so','plugg-scan'):
            if core.digest(a.bridge/name)!=manifest['files'][name]:
                ap.error('Bridge artifact does not match manifest: '+name)
    if a.managed_session:a.session=True
    if a.dxvk and not a.managed_session:ap.error("dxvk requires --managed-session")
    if not 0<=a.hold_ms<=10000:ap.error('hold-ms must be 0..10000')
    if a.survival and not a.session:ap.error('survival requires --session')
    if not 1<=a.rounds<=10:ap.error('rounds must be 1..10')
    base=ROOT/'.test-proton'; run=ROOT/'.test-proton-lifecycle'/uuid.uuid4().hex;run.mkdir(parents=True)
    prefix=run/'prefix';env=os.environ.copy()
    for k in ('WINELOADER','WINESERVER','WINEARCH','WINEDLLPATH','WINEPREFIX','WINEDLLOVERRIDES','WAYLAND_DISPLAY','LD_PRELOAD','YABRIDGE_TEMP_DIR'):env.pop(k,None)
    exports={'UMU_FOLDERS_PATH':str(base/'runtime'),'XDG_CACHE_HOME':str(base/'cache'),'WINEPREFIX':str(prefix),'PROTONPATH':str(base/'UMU-Proton-10.0-4'),'GAMEID':'umu-default','PROTON_VERB':'run','UMU_RUNTIME_UPDATE':'0','WINEDEBUG':'-all','PROTON_LOG':'0','PRESSURE_VESSEL_SHARE_PID':'1','PRESSURE_VESSEL_COPY_RUNTIME':a.copy_runtime}
    env.update(exports)
    print('Run',run,'copy_runtime',a.copy_runtime,flush=True)
    rc=core.run_process([base/'umu/umu-run',ROOT/'build/fixtures/Install-Test-Gain.exe'],env,run/'installer.log',timeout=120)
    if rc:raise RuntimeError('fixture install failed: '+str(rc))
    session_process=None
    endpoint=None
    def stop_session():
        if session_process is not None and session_process.poll() is None:
            os.killpg(session_process.pid,signal.SIGTERM)
            try:session_process.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(session_process.pid,signal.SIGKILL);session_process.wait()
        if a.managed_session and endpoint is not None and endpoint.exists():
            try:
                with socket.socket(socket.AF_UNIX) as conn:
                    conn.connect(str(endpoint))
                    pid,uid,_=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                    if uid!=os.getuid():raise RuntimeError('unexpected fixture session owner')
                    os.kill(pid,signal.SIGTERM)
                for _ in range(50):
                    if not endpoint.exists():break
                    time.sleep(.1)
            except (FileNotFoundError,ConnectionRefusedError,ProcessLookupError):pass
        if endpoint is not None:endpoint.unlink(missing_ok=True)
    atexit.register(stop_session)
    if a.session:
        ipc=Path('/dev/shm')/('ph-session-'+str(os.getuid()));ipc.mkdir(mode=0o700,exist_ok=True)
        st=ipc.lstat()
        if ipc.is_symlink() or st.st_uid!=os.getuid() or st.st_mode & 0o077:raise RuntimeError('unsafe session directory')
        endpoint=ipc/(run.name+'.sock')
        env.update(STEAM_COMPAT_DATA_PATH=str(prefix),STEAM_COMPAT_CLIENT_INSTALL_PATH=str(run),STEAM_COMPAT_INSTALL_PATH=str(run),UMU_ID='umu-default',SteamGameId='default')
        server=ROOT/'scripts/proton-session-probe.py';proton=base/'UMU-Proton-10.0-4/proton';wineserver=base/'UMU-Proton-10.0-4/files/bin/wineserver'
        # This is a fresh fixture prefix, never an active vendor environment.
        command=shlex.join([str(wineserver),'-k'])+'; '+shlex.join([str(wineserver),'-w'])+'; exec '+shlex.join(['/usr/bin/python3',str(server),'serve',str(endpoint),str(proton)])
        if a.managed_session:
            # Shut down only the throwaway fixture's installer runtime before the
            # first two scanner clients race to start the managed session.
            cleanup=shlex.join([str(wineserver),'-k'])+'; '+shlex.join([str(wineserver),'-w'])
            rc=core.run_process([base/'runtime/umu/steamrt3/_v2-entry-point','--verb=run','--','/bin/sh','-c',cleanup],env,run/'cleanup.log',timeout=30)
            if rc:raise RuntimeError('fixture runtime cleanup failed')
            config=run/'session.json'
            core.atomic_json(config,{'prefix':str(prefix),'proton':str(proton),'runtime_entry':str(base/'runtime/umu/steamrt3/_v2-entry-point'),'idle_seconds':3,'manager_sha256':core.digest(ROOT/'plugg/proton_session.py')})
            if a.dxvk:
                cfg=json.loads(config.read_text());cfg['graphics_backend']='dxvk';core.atomic_json(config,cfg)
            from plugg.proton_session import ipc_directory,foreign_prefix_processes
            for _ in range(50):
                if not foreign_prefix_processes(prefix):break
                time.sleep(.1)
            else:raise RuntimeError('fixture prefix did not become idle')
            endpoint=ipc_directory()/('session-'+hashlib.sha256(config.read_bytes()).hexdigest()[:20]+'.sock')
        with (run/'session.log').open('w') as log:
            if not a.managed_session:
                session_process=subprocess.Popen([str(base/'runtime/umu/steamrt3/_v2-entry-point'),'--verb=run','--','/bin/sh','-c',command],env=env,stdout=log,stderr=log,start_new_session=True)
                for _ in range(150):
                    if endpoint.exists():break
                    if session_process.poll() is not None:raise RuntimeError('session exited: '+str(session_process.returncode))
                    time.sleep(0.2)
                else:raise RuntimeError('session startup timed out')
    launcher=run/'launch-proton'
    launcher.write_text('#!/bin/sh\nset -eu\nunset WINELOADER WINESERVER WINEARCH WINEDLLPATH WINEDLLOVERRIDES WAYLAND_DISPLAY LD_PRELOAD\nif [ "${1:-}" = "--version" ]; then printf "%s\\n" "UMU-Proton-10.0-4"; exit 0; fi\n'+''.join('export '+k+'='+shlex.quote(v)+'\n' for k,v in exports.items())+'exec '+shlex.quote(str(base/'umu/umu-run'))+' "$@"\n');launcher.chmod(0o700)
    if a.session:
        launcher.write_text('#!/bin/sh\nexec '+shlex.join([sys.executable,str(ROOT/'scripts/proton-session-probe.py'),'client',str(endpoint)])+' "$@"\n')
    if a.managed_session:
        launcher.write_text('#!/bin/sh\nunset WINEPREFIX\nexec '+shlex.join([sys.executable,str(ROOT/'plugg/proton_session.py'),'launch',str(config)])+' "$@"\n')
    (prefix/'.plugg-runtime').write_text(str(launcher)+'\n')
    store=core.Store(run/'library',run/'unpublished')
    if a.bridge:store.bridge=lambda: a.bridge
    native=core.make_bundle(store,prefix/'drive_c/Program Files/Common Files/VST3/Plugg Test Gain.vst3',run/'ph-lifecycle.vst3')
    scanner=(a.bridge/'plugg-scan') if a.bridge else ROOT/'.test-proton-lifecycle/plugg-scan'
    if not scanner.exists():scanner=store.bridge()/'plugg-scan'
    if not scanner.exists():raise RuntimeError('build the bridge scanner first')
    def audio(i):
        out=run/f'instance-{i}.json';log=run/f'instance-{i}.log';childenv=os.environ.copy();childenv.pop('YABRIDGE_TEMP_DIR',None);childenv['PLUGG_SCAN_TRACE']='1';childenv['PLUGG_SCAN_HOLD_MS']=str(a.hold_ms)
        start=time.monotonic()
        with log.open('w') as f:p=subprocess.Popen([str(scanner),str(native),str(out),'--audio'],env=childenv,stdout=f,stderr=f,start_new_session=True)
        timedout=False
        try:p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            timedout=True
            with (run/f'instance-{i}-stack.log').open('w') as f:
                try:subprocess.run(['gdb','-q','-batch','-ex','set debuginfod enabled off','-ex','thread apply all bt 10','-p',str(p.pid)],stdout=f,stderr=f,timeout=12)
                except subprocess.TimeoutExpired:pass
        finally:
            if p.poll() is None:
                os.killpg(p.pid,signal.SIGTERM)
                try:p.wait(timeout=3)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
        data=json.loads(out.read_text()) if out.exists() and out.stat().st_size else {}
        stages=[l.split('SCAN_STAGE ',1)[1] for l in log.read_text(errors='replace').splitlines() if l.startswith('SCAN_STAGE ')]
        return {'instance':i,'passed':not timedout and p.returncode==0 and data.get('audio_fixture_passed',False),'timeout':timedout,'exit':p.returncode,'seconds':round(time.monotonic()-start,3),'stages':stages,'audio':data}
    results=[]
    for trial in range(a.rounds):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:pair=list(pool.map(audio,[trial*2,trial*2+1]))
        results+=pair
        report={'bridge_manifest':json.loads((store.bridge()/'build.json').read_text()),'session_manager_sha256':core.digest(ROOT/'plugg/proton_session.py'),'run':str(run),'copy_runtime':a.copy_runtime,'hold_ms':a.hold_ms,'persistent_session':a.session,'managed_session':a.managed_session,'dxvk':a.dxvk,'passed':all(x['passed'] for x in results),'instances':results}
        core.atomic_json(run/'results.json',report)
        print(json.dumps(pair),flush=True)
        if not all(x['passed'] for x in pair):break
    if a.survival and report['passed']:
        scenarios=[]
        def start_scan(label, blocks):
            out=run/(label+'.json');log=run/(label+'.log')
            e=os.environ.copy();e.pop('YABRIDGE_TEMP_DIR',None)
            e.update(PLUGG_SCAN_TRACE='1',PLUGG_SCAN_BLOCKS=str(blocks),PLUGG_SCAN_PACE_US='1000',PLUGG_SCAN_HOLD_MS='0')
            with log.open('w') as f:p=subprocess.Popen([str(scanner),str(native),str(out),'--audio'],env=e,stdout=f,stderr=f,start_new_session=True)
            return p,out,log
        def wait_processing(p,log):
            for _ in range(100):
                if 'SCAN_STAGE process-audio' in log.read_text(errors='replace'):return
                if p.poll() is not None:raise RuntimeError('scan exited before processing')
                time.sleep(.1)
            raise RuntimeError('scan did not begin processing')
        for mode in ('close','kill-windows-host','kill-native-host'):
            survivor,sout,slog=start_scan(mode+'-survivor',10000)
            victim,vout,vlog=start_scan(mode+'-victim',500 if mode=='close' else 30000)
            result={'mode':mode,'passed':False}
            try:
                wait_processing(survivor,slog);wait_processing(victim,vlog)
                if mode=='close':victim.wait(timeout=5)
                elif mode=='kill-native-host':victim.kill()
                else:
                    matches=[]
                    for p in Path('/proc').iterdir():
                        if not p.name.isdigit():continue
                        try:args=(p/'cmdline').read_bytes().split(b'\0')
                        except OSError:continue
                        if args and b'yabridge-host' in args[0] and str(victim.pid).encode() in args:matches.append(int(p.name))
                    if len(matches)!=1:raise RuntimeError('could not identify unique fixture Windows host: '+str(matches))
                    os.kill(matches[0],signal.SIGKILL)
                    result['killed_windows_pid']=matches[0]
                src=survivor.wait(timeout=18)
                data=json.loads(sout.read_text()) if sout.exists() and sout.stat().st_size else {}
                result.update(survivor_exit=src,passed=src==0 and data.get('audio_fixture_passed',False),victim_exit=victim.poll())
            except Exception as e:result['error']=str(e)
            finally:
                for p in (survivor,victim):
                    if p.poll() is None:
                        os.killpg(p.pid,signal.SIGTERM)
                        try:p.wait(timeout=3)
                        except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
            scenarios.append(result);report['survival']=scenarios;report['passed']=report['passed'] and result['passed']
            core.atomic_json(run/'results.json',report);print(json.dumps(result),flush=True)
            if not result['passed']:break
    if a.managed_session and report['passed']:
        for _ in range(150):
            if not endpoint.exists():break
            time.sleep(.1)
        idle_stopped=not endpoint.exists()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            restarted=list(pool.map(audio,[a.rounds*2,a.rounds*2+1])) if idle_stopped else []
        report['idle_restart']={'idle_stopped':idle_stopped,'instances':restarted,'passed':idle_stopped and len(restarted)==2 and all(x['passed'] for x in restarted)}
        report['passed']=report['passed'] and report['idle_restart']['passed']
        core.atomic_json(run/'results.json',report)
        print(json.dumps({'idle_restart':report['idle_restart']}),flush=True)
    stop_session()
    print('Results',run/'results.json',flush=True)
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
