#!/usr/bin/env python3
"""Managed persistent Proton sessions. SPDX-License-Identifier: GPL-3.0-or-later

One container per vendor prefix; disconnecting a client cancels only its child.
Existing environments must be idle before changing launchers.
"""
import base64,json,os,selectors,signal,socket,struct,subprocess,sys,threading
import fcntl,hashlib,time,stat
from pathlib import Path

def serve(path,proton,idle_seconds=300,graphics=None):
    listener=socket.socket(socket.AF_UNIX)
    listener.bind(path);os.chmod(path,0o600);listener.listen(16);listener.settimeout(1)
    active=set();mutex=threading.Lock();stopping=threading.Event()
    def stop(*_):stopping.set()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def handle(conn):
        process=None;reader=None;sel=None
        try:
            _,uid,_=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            if uid!=os.getuid():return
            conn.settimeout(5)
            reader=conn.makefile('rb');line=reader.readline(65537)
            conn.settimeout(None)
            if not line.endswith(b'\n') or len(line)>65536:return
            args=json.loads(line)
            if args == {'ping':1}:
                conn.sendall(b'{"ready":true}\n');return
            if not isinstance(args,list) or not args or len(args)>256 or not all(isinstance(a,str) and len(a)<=16384 and '\0' not in a for a in args):return
            process=subprocess.Popen([proton,'runinprefix',*args],env=graphics_environment(args,graphics),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
            os.set_blocking(process.stdout.fileno(),False)
            died=threading.Event()
            def watch():
                if watch_windows_process(args[0],process,stopping):died.set()
            watchdog=threading.Thread(target=watch,daemon=True);watchdog.start()
            sel=selectors.DefaultSelector();sel.register(process.stdout,selectors.EVENT_READ);sel.register(conn,selectors.EVENT_READ)
            pipe_open=True
            while not stopping.is_set() and not died.is_set() and (process.poll() is None or pipe_open):
                for key,_ in sel.select(timeout=0.2):
                    if key.fileobj is conn:
                        if not conn.recv(1):return
                        raise ValueError('Unexpected extra request data')
                    chunk=os.read(process.stdout.fileno(),16384)
                    if chunk:conn.sendall(json.dumps({'output':base64.b64encode(chunk).decode()}).encode()+b'\n')
                    else:sel.unregister(process.stdout);pipe_open=False
            if died.is_set() and process.poll() is None:
                conn.sendall(json.dumps({'output':base64.b64encode(
                    b'Plugg: the Windows program exited without its launcher noticing; ending the launch.\n').decode()}).encode()+b'\n')
                conn.sendall(json.dumps({'exit':127}).encode()+b'\n')
            elif not stopping.is_set():conn.sendall(json.dumps({'exit':process.returncode}).encode()+b'\n')
        except (OSError,ValueError,RuntimeError) as error:
            print('Session launch failed:', error, file=sys.stderr, flush=True)
        finally:
            if process is not None and process.poll() is None:
                try:os.killpg(process.pid,signal.SIGINT)
                except ProcessLookupError:pass
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    process.wait()
            if sel is not None:sel.close()
            if process is not None and process.stdout is not None:process.stdout.close()
            if reader is not None:reader.close()
            conn.close()
            with mutex:active.discard(threading.current_thread())
    print('SESSION_READY',flush=True)
    idle_since=time.monotonic()
    try:
        while not stopping.is_set():
            with mutex:busy=bool(active)
            if busy:idle_since=time.monotonic()
            elif time.monotonic()-idle_since>=idle_seconds:break
            try:c,_=listener.accept()
            except socket.timeout:continue
            t=threading.Thread(target=handle,args=(c,),daemon=True)
            with mutex:active.add(t)
            t.start()
    finally:
        stopping.set();listener.close()
        with mutex:threads=list(active)
        for t in threads:t.join(timeout=5)
        Path(path).unlink(missing_ok=True)

def windows_process_state(program,group=None):
    """Is the launched Windows program running, gone after running, or absent?

    Wine's launcher keeps waiting when the program it started dies, so the
    caller would wait with it. A host whose main thread died shows as a
    zombie while its other threads keep the process, and so the launcher,
    alive: that is 'exited', not absent.

    The program is recognised by its own name, not by its path appearing
    somewhere in a command line: Proton's runinprefix and Wine's start.exe
    carry that path as an argument and are the launcher, while the program's
    own argv[0] is the same path in Windows form (X:\\...\\yabridge-host.exe.so).
    A zombie's command line may be unreadable, so its 15-character comm name
    stands in for it.

    Every plug-in instance runs the same host program, so the name alone
    cannot tell one launch from another: a healthy instance would hide a dead
    one. The group is the launch's own process group, which Wine keeps for
    the processes it starts.
    """
    name=os.fsencode(os.path.basename(program));found=None
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            fields=(p/'stat').read_bytes().rpartition(b')')[2].split()
            if len(fields)<3 or (group is not None and int(fields[2])!=group):continue
            argv0=(p/'cmdline').read_bytes().split(b'\0',1)[0]
            if argv0:
                if argv0.replace(b'\\',b'/').rpartition(b'/')[2]!=name:continue
            elif (p/'comm').read_bytes().rstrip(b'\n')!=name[:15]:continue
        except (OSError,ValueError):continue
        if fields[0] not in (b'Z',b'X'):return 'running'
        found='exited'
    return found


def windows_process_alive(program,group=None):
    return windows_process_state(program,group)=='running'


def watch_windows_process(program,process,stopping,appeared_within=60,interval=2):
    """Stop a launch whose Windows program has exited but whose launcher has not.

    Returns once the program is gone after having run, once the launcher
    exits, or once the session stops. The caller then ends the launcher, so a
    crashed plug-in is reported as a failed launch instead of a DAW that waits
    for a process which no longer exists. The launcher is started in a
    session of its own, so its pid is the launch's process group.
    """
    started=time.monotonic();seen=False
    while not stopping.is_set() and process.poll() is None:
        state=windows_process_state(program,process.pid)
        if state=='running':
            seen=True
        elif state=='exited' or seen or time.monotonic()-started>appeared_within:
            return seen or state=='exited'
        stopping.wait(interval)
    return False

def client(path,args):
    if args==['--version']:print('Plugg persistent UMU-Proton-10.0-4');return 0
    conn=socket.socket(socket.AF_UNIX);conn.connect(path)
    def cancel(*_):conn.close();raise SystemExit(130)
    signal.signal(signal.SIGINT,cancel);signal.signal(signal.SIGTERM,cancel)
    conn.sendall(json.dumps(args).encode()+b'\n')
    with conn,conn.makefile('rb') as inp:
        for line in inp:
            event=json.loads(line)
            if 'exit' in event:return event['exit']
            os.write(2,base64.b64decode(event['output']))
    return 125
def configuration(path, *, contents=None, verify_manager=False):
    cfg=json.loads(Path(path).read_bytes() if contents is None else contents)
    if not isinstance(cfg,dict):
        raise RuntimeError('Managed session configuration must be an object')
    for key in ('prefix','proton','runtime_entry'):
        if not isinstance(cfg.get(key),str) or not cfg[key]:
            raise RuntimeError('Missing or invalid managed session '+key)
        value=Path(cfg[key])
        if not value.is_absolute() or not value.exists():raise RuntimeError('Missing managed session '+key)
    if not (Path(cfg['prefix'])/'drive_c').is_dir():raise RuntimeError('Initialize this environment before starting its session')
    for key in ('proton','runtime_entry'):
        if not Path(cfg[key]).is_file() or not os.access(cfg[key],os.X_OK):raise RuntimeError('Managed session executable unavailable: '+key)
    idle=cfg.get('idle_seconds',300)
    if type(idle) is not int or not 2<=idle<=3600:raise RuntimeError('Invalid session idle timeout')
    if verify_manager and 'manager_sha256' in cfg:
        expected=cfg['manager_sha256']
        if not isinstance(expected,str) or len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected):
            raise RuntimeError('Invalid managed session launcher fingerprint')
        if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=expected:
            raise RuntimeError('Managed session launcher differs from its recorded version; inspect this environment before loading plug-ins')
    return cfg

def ipc_directory():
    p=Path('/dev/shm')/('plugg-'+str(os.getuid()));p.mkdir(mode=0o700,exist_ok=True)
    st=p.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077:raise RuntimeError('Unsafe managed IPC directory')
    return p

def ping(path):
    try:
        with socket.socket(socket.AF_UNIX) as c:
            c.settimeout(.5);c.connect(str(path))
            _,uid,_=struct.unpack('3i',c.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            if uid!=os.getuid():raise RuntimeError('Unexpected runtime session owner')
            c.sendall(b'{"ping":1}\n')
            with c.makefile('rb') as inp:return inp.readline(101)==b'{"ready":true}\n'
    except (OSError,TimeoutError):return False

def foreign_prefix_processes(prefix):
    found=[];prefix=Path(prefix).resolve()
    for p in Path('/proc').iterdir():
        if not p.name.isdigit() or p.name==str(os.getpid()):continue
        try:
            if p.stat().st_uid!=os.getuid():continue
            values=(p/'environ').read_bytes().split(b'\0')
            for value in values:
                if value.startswith(b'WINEPREFIX=') and Path(os.fsdecode(value.split(b'=',1)[1])).resolve()==prefix:
                    found.append(int(p.name));break
        except (OSError,ValueError):pass
    return found


def prefix_processes():
    """Every managed prefix's processes in one pass over /proc.

    The per-prefix scan above is right for a single decision. Asking it once per
    card, several times a second, would be a full walk of /proc per card — so
    the interface asks once and looks each environment up in the answer.
    """
    found = {}
    for p in Path('/proc').iterdir():
        if not p.name.isdigit() or p.name == str(os.getpid()):
            continue
        try:
            if p.stat().st_uid != os.getuid():
                continue
            for value in (p / 'environ').read_bytes().split(b'\0'):
                if value.startswith(b'WINEPREFIX='):
                    key = Path(os.fsdecode(value.split(b'=', 1)[1])).resolve()
                    found.setdefault(key, []).append(int(p.name))
                    break
        except (OSError, ValueError):
            pass
    return found

def graphics_overrides(cfg):
    """runinprefix skips setup_prefix(), including its per-process DXVK overrides.

    Use only the DXVK DLLs already provisioned by this exact Proton build. Do not
    copy or update a live prefix here, and do not silently fall back to WineD3D.
    """
    backend = cfg.get('graphics_backend')
    if backend is None:
        return None
    if backend == 'wined3d':
        return 'd3d11,dxgi,d3d10core,d3d10,d3d10_1,d3d9=b'
    if backend != 'dxvk':
        raise RuntimeError('Unsupported managed graphics backend')
    names = ('d3d11', 'dxgi', 'd3d10core', 'd3d9')
    source = Path(cfg['proton']).parent / 'files/lib/wine/dxvk/x86_64-windows'
    target = Path(cfg['prefix']) / 'drive_c/windows/system32'
    for name in names:
        original = source / (name + '.dll')
        installed = target / (name + '.dll')
        if not original.is_file() or not installed.is_file():
            raise RuntimeError('Prepare the Proton DXVK graphics components before launching plug-ins')
        if hashlib.sha256(original.read_bytes()).digest() != hashlib.sha256(installed.read_bytes()).digest():
            raise RuntimeError('Installed graphics components differ from the selected Proton runtime')
    return ';'.join(name + '=n' for name in names)



def validate_graphics_policy(policy):
    """Small declarative recipe fragment; no executable hooks or wildcard matches."""
    if not isinstance(policy, dict) or set(policy) != {'schema', 'default', 'plugins'}:
        raise RuntimeError('Graphics policy requires schema, default and plugins only')
    if type(policy['schema']) is not int or policy['schema'] != 1:
        raise RuntimeError('Unsupported graphics policy schema')
    backends = {'dxvk', 'wined3d'}
    if not isinstance(policy['default'], str) or policy['default'] not in backends:
        raise RuntimeError('Unsupported default graphics backend')
    if not isinstance(policy['plugins'], dict):
        raise RuntimeError('Graphics plugins must map relative module paths to backends')
    for module, backend in policy['plugins'].items():
        if (not isinstance(module, str) or not module or '\\' in module
                or ':' in module or '\0' in module or module.startswith('/')
                or any(part in ('', '.', '..') for part in module.split('/'))
                or not module.lower().endswith('.vst3')):
            raise RuntimeError('Graphics module must be a relative VST3 path beneath drive_c')
        if not isinstance(backend, str) or backend not in backends:
            raise RuntimeError('Unsupported plug-in graphics backend')
    return policy


def prepare_graphics(cfg):
    """Resolve exact module identities and verify required runtime DLLs once per session."""
    policy = cfg.get('graphics_policy')
    if policy is None:
        return {'default': graphics_overrides(cfg), 'plugins': {}}
    validate_graphics_policy(policy)
    root = (Path(cfg['prefix']) / 'drive_c').resolve()
    overrides = {}
    for backend in {policy['default'], *policy['plugins'].values()}:
        overrides[backend] = graphics_overrides({**cfg, 'graphics_backend': backend})
    plugins = {}
    for relative, backend in policy['plugins'].items():
        module = (root / relative).resolve()
        if not module.is_relative_to(root):
            raise RuntimeError('Graphics module escapes the managed prefix')
        if str(module) in plugins:
            raise RuntimeError('Duplicate graphics module identity')
        plugins[str(module)] = overrides[backend]
    return {'default': overrides[policy['default']], 'plugins': plugins}


def graphics_environment(args, graphics=None):
    """Apply graphics settings only to the launched child, never the shared server."""
    env = os.environ.copy()
    if graphics is None:
        return env
    override = graphics['default']
    # Individual yabridge invocation: host, format, Windows module, IPC, parent PID.
    # Do not match arbitrary arguments, helper names, or publication substrings.
    if len(args) == 5 and Path(args[0]).name == 'yabridge-host.exe' and args[1] == 'VST3':
        module = Path(args[2])
        if module.is_absolute():
            override = graphics['plugins'].get(str(module.resolve()), override)
    elif len(args) > 1 and args[1] == 'group' and graphics['plugins']:
        raise RuntimeError('Per-plugin graphics require individual bridge hosts')
    if override is not None:
        env['WINEDLLOVERRIDES'] = override
    return env


def ensure_session(config_path):
    config_path=Path(config_path).resolve();contents=config_path.read_bytes()
    cfg=configuration(config_path,contents=contents,verify_manager=True)
    graphics=prepare_graphics(cfg)
    identity=hashlib.sha256(contents).hexdigest()[:20]
    root=ipc_directory();endpoint=root/('session-'+identity+'.sock')
    # Serialize starts across all configuration revisions for this prefix.
    lock_id=hashlib.sha256(str(Path(cfg['prefix']).resolve()).encode()).hexdigest()[:20]
    with (root/('session-'+lock_id+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if ping(endpoint):return endpoint
        if foreign_prefix_processes(cfg['prefix']):
            raise RuntimeError('This vendor environment is still in use. Close its plug-ins and Helper before starting the managed session.')
        if endpoint.exists():
            if not stat.S_ISSOCK(endpoint.lstat().st_mode):raise RuntimeError('Session address is occupied by a non-socket')
            endpoint.unlink()
        env=os.environ.copy()
        for k in ('WINELOADER','WINESERVER','WINEARCH','WINEDLLPATH','WINEDLLOVERRIDES','LD_PRELOAD','WAYLAND_DISPLAY','SteamAppId','YABRIDGE_TEMP_DIR'):
            env.pop(k,None)
        env.update(WINEPREFIX=cfg['prefix'],STEAM_COMPAT_DATA_PATH=cfg['prefix'],STEAM_COMPAT_CLIENT_INSTALL_PATH=str(config_path.parent),STEAM_COMPAT_INSTALL_PATH=str(config_path.parent),UMU_ID='umu-default',SteamGameId='default',WINEDEBUG=os.environ.get('PLUGG_WINEDEBUG','fixme-all'),PROTON_LOG='0',PRESSURE_VESSEL_SHARE_PID='1',PRESSURE_VESSEL_COPY_RUNTIME='1')
        overrides=graphics['default']
        if overrides:env['WINEDLLOVERRIDES']=overrides
        log=config_path.parent/'session.log'
        with log.open('ab') as out:
            proc=subprocess.Popen([cfg['runtime_entry'],'--verb=run','--','/usr/bin/python3',str(Path(__file__).resolve()),'serve',str(endpoint),cfg['proton'],str(cfg.get('idle_seconds',300)),str(config_path)],env=env,stdout=out,stderr=out,start_new_session=True)
        for _ in range(150):
            if ping(endpoint):return endpoint
            if proc.poll() is not None:raise RuntimeError('Runtime session failed to start; see session.log')
            time.sleep(.2)
        os.killpg(proc.pid,signal.SIGTERM)
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
        raise RuntimeError('Runtime session startup timed out; see session.log')



def stop_idle_session(config_path):
    """Stop only this configuration's idle managed container before maintenance.

    The caller must first exclude active plug-ins and installers. Recheck while
    holding the same startup lock used by ensure_session; never kill by name.
    """
    config_path=Path(config_path).resolve();cfg=configuration(config_path)
    root=ipc_directory()
    identity=hashlib.sha256(config_path.read_bytes()).hexdigest()[:20]
    endpoint=root/('session-'+identity+'.sock')
    lock_id=hashlib.sha256(str(Path(cfg['prefix']).resolve()).encode()).hexdigest()[:20]
    with (root/('session-'+lock_id+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        from .vendors import applications
        if applications(Path(cfg['prefix'])):
            raise RuntimeError('Close this vendor’s plug-ins and Helper before managing installations.')
        if not ping(endpoint):
            if foreign_prefix_processes(cfg['prefix']):
                raise RuntimeError('Another runtime is still using this vendor environment.')
            return
        with socket.socket(socket.AF_UNIX) as conn:
            conn.connect(str(endpoint))
            pid,uid,_=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            args=(Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0')
            expected=[b'serve',os.fsencode(endpoint),os.fsencode(cfg['proton'])]
            if uid!=os.getuid() or not any(args[i:i+3]==expected for i in range(len(args)-2)):
                raise RuntimeError('Cannot verify the vendor session process; left it running.')
            os.kill(pid,signal.SIGTERM)
        for _ in range(100):
            if not foreign_prefix_processes(cfg['prefix']):return
            time.sleep(.1)
        raise RuntimeError('Vendor runtime did not stop. Try again once it is idle.')


if __name__=='__main__':
    if sys.argv[1]=='serve':serve(sys.argv[2],sys.argv[3],int(sys.argv[4]) if len(sys.argv)>4 else 300,prepare_graphics(configuration(sys.argv[5])) if len(sys.argv)>5 else None)
    elif sys.argv[1]=='client':raise SystemExit(client(sys.argv[2],sys.argv[3:]))
    elif sys.argv[1]=='launch':
        args=sys.argv[3:]
        if args==['--version']:print('Plugg persistent UMU-Proton-10.0-4');raise SystemExit(0)
        try:raise SystemExit(client(str(ensure_session(sys.argv[2])),args))
        except (OSError,ValueError,RuntimeError) as e:print('Plugg:',e,file=sys.stderr);raise SystemExit(1)
    else:raise SystemExit(64)
