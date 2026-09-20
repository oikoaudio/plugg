"""Native Access helper lifecycle, scoped to one installed environment."""
import json,os,subprocess,time
from pathlib import Path
from . import core,licensing,protocols,vendors,proton_session,native_access_routing

APPLICATION = 'Program Files/Native Instruments/Native Access/Native Access.exe'
BACKGROUND = {'ntkdaemon.exe','crashpad_handler.exe','xalia.exe','tabtip.exe','umu.exe'}

def configure(directory):
    directory=Path(directory)
    licensing.guard(directory,'install_component')
    drive=(directory/'prefix/drive_c').resolve()
    downloads=drive/'Native Instruments Downloads'
    if not downloads.resolve().is_relative_to(drive):raise core.HostError('NI download path escapes its environment.')
    downloads.mkdir(exist_ok=True)
    from . import ntk_component
    ntk_component.configure_launcher(directory)
    core.atomic_json(directory/'native-access-protocol.json',{'launcher':str(directory/'launch-full-proton'),'application':str(drive/APPLICATION)})

def complete_sign_in(directory,uri):
    # Callbacks are accepted only through an explicit UI action for this setup.
    # Do not redirect the user's existing desktop protocol association.
    return protocols.dispatch(Path(directory)/'native-access-protocol.json',uri)

def prepare_runtime(directory, *, closed_window=False, bootstrap_pids=()):
    directory=Path(directory);prefix=directory/'prefix'
    allowed=BACKGROUND | ({'native access.exe'} if closed_window else set())
    for pid,name in vendors.running_programs(prefix):
        bootstrap = pid in bootstrap_pids and name.lower() in ('cmd.exe','start.exe')
        if name.lower() not in allowed and not bootstrap:
            raise core.HostError('Close applications in this NI environment before continuing: '+name)
    cfg=json.loads((directory/'session.json').read_text())
    expected=Path(cfg['proton']).parent/'files/bin/wineserver'
    found=False
    for pid in proton_session.foreign_prefix_processes(prefix):
        try:exe=(Path('/proc')/str(pid)/'exe').resolve(strict=True)
        except OSError:continue
        if exe.name.startswith('wineserver'):
            if exe!=expected.resolve():raise core.HostError('A different Wine runtime is using this NI environment.')
            found=True
    if found:
        subprocess.run([str(expected),'-k'],env=dict(os.environ,WINEPREFIX=str(prefix)),
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=10)
    proton_session.stop_idle_session(directory/'session.json')

def descendants(parent):
    parents = {}
    for path in Path('/proc').iterdir():
        if not path.name.isdigit(): continue
        try:
            parents[int(path.name)] = int((path/'stat').read_text().rsplit(')',1)[1].split()[1])
        except (OSError,ValueError,IndexError): pass
    owned = {parent}
    while True:
        extra = {pid for pid,ppid in parents.items() if ppid in owned} - owned
        if not extra: return owned
        owned.update(extra)


def work(store,job_id,refresh=False):
    directory,cfg=vendors.configuration(store,job_id)
    prefix=directory/'prefix'
    with core.lock(directory/'helper.lock',blocking=False),core.lock(store.root/'jobs'/job_id/'job.lock',blocking=False):
        def report(status,message):
            core.atomic_json(directory/'helper-state.json',{'status':status,'message':message,'pid':os.getpid(),'updated':time.time()})
        try:
            if not refresh:
                from . import ntk_component
                ntk_component.require_available(directory)
            prepare_runtime(directory)
            if not refresh:
                report('opening','Opening Native Access…')
                with native_access_routing.active(directory/'native-access-protocol.json'), vendors.helper_placement('Native Access'):
                    child=subprocess.Popen([cfg['helper_launcher']],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    seen=False;absent=0
                    report('running','Native Access is open. Browser sign-in returns to this setup automatically. Download location: C:\\Native Instruments Downloads.')
                    while child.poll() is None:
                        # A failed compositor query must never be interpreted as a close.
                        if os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):
                            result=subprocess.run(['hyprctl','-j','clients'],capture_output=True,text=True,timeout=3)
                            if result.returncode==0:
                                clients=json.loads(result.stdout)
                                pids=set(proton_session.foreign_prefix_processes(prefix))
                                visible=any(w.get('pid') in pids and w.get('title')=='Native Access' for w in clients)
                                if visible:seen=True;absent=0
                                elif seen:
                                    absent+=1
                                    if absent>=3:
                                        prepare_runtime(directory,closed_window=True,bootstrap_pids=descendants(child.pid))
                                        child.wait(timeout=15)
                                        break
                        time.sleep(1)
                    if child.returncode and not (seen and absent>=3):
                        raise core.HostError('Native Access exited unexpectedly.')
                prepare_runtime(directory)
            return vendors.finish_installation(store,job_id,busy=proton_session.foreign_prefix_processes)
        except Exception as exc:
            report('needs_attention',str(exc));raise
