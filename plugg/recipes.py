"""Reproducible vendor preparation; never clone an activated prefix.
SPDX-License-Identifier: GPL-3.0-or-later
"""
import hashlib
import json
import contextlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

from . import core, licensing, vendors, proton_session, helper_component
# Compatibility aliases for existing provisioning scripts.
from . import artifacts
from .artifacts import fetch, unpack


KLEVGRAND_HELPER = {
    'name': 'Klevgrand Helper',
    'executable': 'Program Files (x86)/Klevgrand/Klevgrand Helper/Klevgrand Helper.exe',
    'archive_tools': True,
}


def recipe():
    return json.loads((Path(__file__).parent/'recipes/klevgrand.json').read_text())


def recognized(installer_hash):
    return installer_hash in recipe()['installer_sha256']


def provision(store, report, check):
    spec=recipe();identity=hashlib.sha256(json.dumps(spec['runtimes'],sort_keys=True).encode()).hexdigest()[:16]
    target=store.root/'runtimes'/('proton-'+identity)
    markers=('UMU-Proton-10.0-4/proton','umu/umu-run','runtime/umu/steamrt3/_v2-entry-point')
    with core.lock(store.root/'proton-provision.lock'):
        if (target/'runtime.json').exists():
            manifest=json.loads((target/'runtime.json').read_text())
            if manifest.get('assets')!=spec['runtimes']:raise core.HostError('Managed Proton runtime provenance does not match the recipe')
            for p in markers:
                if not (target/p).is_file():raise core.HostError('Managed Proton runtime is incomplete')
                if core.digest(target/p)!=manifest.get('files',{}).get(p):raise core.HostError('Managed Proton runtime entry point changed')
            return target
        archives=[fetch(store,a,report,check,artifacts.RUNTIME_RELEASES) for a in spec['runtimes']]
        target.parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=target.parent,prefix='.prepare-proton-') as tmp:
            stage=Path(tmp)
            for archive in archives:
                check();report('Unpacking Windows support');unpack(archive,stage)
            steam=stage/'runtime/umu/steamrt3';steam.parent.mkdir(parents=True)
            (stage/'SteamLinuxRuntime_sniper').rename(steam)
            core.atomic_json(stage/'runtime.json',{'assets':spec['runtimes'],'recipe_revision':spec['revision'],'files':{p:core.digest(stage/p) for p in markers}})
            stage.rename(target)
        return target


def archive_tools(store, prefix, report, check):
    from . import archive_component
    archive_component.install(store, prefix, recipe()['packages'], report, check)


def executable(path, text):
    path.write_text(text);path.chmod(0o700)


def configure(store, job_id, runtime, helper_enabled=True, *, helper_spec=None):
    """Prepare launch files; caller owns environment allocation and idle locking."""
    custom_helper = helper_spec is not None
    if custom_helper and not helper_enabled:
        raise ValueError('A helper description cannot be supplied when helper launch is disabled')
    if helper_enabled:
        helper_spec = helper_component.validate(helper_spec if custom_helper else KLEVGRAND_HELPER)
    profile = 'managed-helper-1' if custom_helper else ('klevgrand-1' if helper_enabled else 'standalone-vst3-1')
    prefix=store.prefix(job_id);directory=prefix.parent
    adapter=directory/'proton-desktop';adapter.mkdir(exist_ok=True)
    from . import runtime_overlay
    original=runtime_overlay.proton_for_new_environment(store.root, runtime/'UMU-Proton-10.0-4')
    if (directory/'session.json').exists():
        previous=json.loads((directory/'session.json').read_text()).get('proton')
        if previous and Path(previous)!=original/'proton':
            licensing.guard(directory,'replace_runtime')
    for p in original.iterdir():
        if p.name!='proton' and not (adapter/p.name).exists():(adapter/p.name).symlink_to(p)
    executable(adapter/'proton','#!/usr/bin/env python3\nimport os,sys\nos.environ.pop("SteamAppId",None)\np='+repr(str(original/'proton'))+'\nos.execv(p,[p,*sys.argv[1:]])\n')
    exports={'UMU_FOLDERS_PATH':str(runtime/'runtime'),'XDG_CACHE_HOME':str(store.root/'runtime-cache'),'WINEPREFIX':str(prefix),'PROTONPATH':str(adapter),'GAMEID':'umu-default','PROTON_VERB':'run','UMU_RUNTIME_UPDATE':'0','WINEDEBUG':'-all','PROTON_LOG':'0','PRESSURE_VESSEL_SHARE_PID':'1','PRESSURE_VESSEL_COPY_RUNTIME':'1'}
    full=directory/'launch-full-proton'
    executable(full,'#!/bin/sh\nset -eu\nunset WINELOADER WINESERVER WINEARCH WINEDLLPATH WINEDLLOVERRIDES WAYLAND_DISPLAY LD_PRELOAD\n'+''.join('export '+k+'='+shlex.quote(v)+'\n' for k,v in exports.items())+'exec '+shlex.quote(str(runtime/'umu/umu-run'))+' "$@"\n')
    source=Path(proton_session.__file__);manager=directory/('session-manager-'+core.digest(source)[:16]+'.py');shutil.copy2(source,manager)
    core.atomic_json(directory/'session.json',{'prefix':str(prefix),'proton':str(original/'proton'),'runtime_entry':str(runtime/'runtime/umu/steamrt3/_v2-entry-point'),'idle_seconds':300,'manager_sha256':core.digest(manager),'graphics_backend':'dxvk','recipe':profile})
    plugin=directory/'launch-plugin'
    executable(plugin,'#!/bin/sh\nunset WINEPREFIX\nexec '+shlex.join([sys.executable,str(manager),'launch',str(directory/'session.json')])+' "$@"\n')
    (prefix/'.plugg-runtime').write_text(str(plugin)+'\n')
    if not helper_enabled:
        return full,None
    helper=helper_component.configure(prefix,full,helper_spec)
    core.atomic_json(directory/'helper-entry.json',{'schema':1,'helper':helper_spec})
    return full,helper


def work(store, job_id, installer_args=None):
    job=store.job(job_id)
    if installer_args is None:installer_args=recipe()['installer_args']
    with core.lock(store.root/'klevgrand-setup.lock',blocking=False), core.lock(store.root/'jobs'/job_id/'job.lock',blocking=False):
        if job['status'] in core.TERMINAL:raise core.HostError('This setup already finished; open the vendor Helper instead.')
        if not recognized(job['hash']):raise core.HostError('This installer has not been validated for the Klevgrand recipe.')
        try:
            # One vendor environment per library. Duplicate intake must not consume
            # another activation or silently create a second vendor installation.
            if any(v['job']!=job_id and v['recipe']=='klevgrand' for v in vendors.cards(store)):
                raise core.HostError('Klevgrand is already configured. Use Open Helper on its vendor card.')
            core.verify_installer(job)
            check=lambda:store.cancelled(job_id)
            report=lambda msg:store.update(job_id,'preparing',msg,pid=os.getpid())
            report('Preparing Klevgrand support')
            runtime=provision(store,report,check)
            prefix=store.prefix(job_id);prefix.mkdir(parents=True,exist_ok=True)
            full,helper=configure(store,job_id,runtime)
            # Before the vendor installer runs, so it sees this computer rather
            # than an identity invented for this prefix.
            licensing.adopt_machine_identity(prefix.parent,[str(full)],os.environ.copy(),check,timeout=600)
            store.update(job_id,'installing','Installing Klevgrand Helper…')
            # Discard vendor output; it may contain account information.
            with vendors.helper_placement():
                helper_component.install(job,prefix,full,KLEVGRAND_HELPER,installer_args,check)
            report('Preparing the private archive utility')
            archive_tools(store,prefix,report,check)
            proton_session.graphics_overrides(json.loads((prefix.parent/'session.json').read_text()))
            # Ensure the full installer runtime is gone before managed probes.
            for _ in range(60):
                check()
                if not proton_session.foreign_prefix_processes(prefix):break
                time.sleep(1)
            else:raise core.HostError('Close the installer and Helper, then retry setup.')
            core.atomic_json(prefix.parent/'environment.json',{'id':job_id,'recipe':'klevgrand','recipe_revision':1,'runtime':'UMU-Proton-10.0-4','status':'ready','sandbox':False,'helper_launcher':str(helper),'session_launcher':str(prefix.parent/'launch-plugin'),'helper_owns_runtime':True,'graphics_backend':'dxvk','automatic_updates':False})
            # Protected before the first activation exists, not after someone
            # thinks to ask what would happen if this were rebuilt.
            licensing.protect_declared(prefix.parent, recipe().get('licensing'))
            store.update(job_id,'ready','Klevgrand is ready. Open Helper to sign in and install VST3 plug-ins.')
        except core.Cancelled as exc:
            store.update(job_id,'cancelled',str(exc));raise
        except Exception as exc:
            store.update(job_id,'failed',str(exc));raise
        finally:
            with store.db() as db:db.execute('UPDATE jobs SET pid=NULL WHERE id=?',(job_id,))


@contextlib.contextmanager
def graphics_change(directory):
    """Serialize graphics edits with each other and managed helper activity."""
    directory = Path(directory).resolve()
    with core.lock(directory / 'helper.lock', blocking=False), core.lock(directory / 'graphics-policy.lock', blocking=False):
        yield directory


def update_session_manager(directory):
    """Give an existing environment the current session launcher.

    Environments keep the launcher they were created with, so a fix in it
    reaches them only through this. It replaces the manager copy, its recorded
    fingerprint and launch-plugin, and keeps a backup of what was there. The
    prefix, its installed software and its machine identity are untouched, so
    an activated environment keeps its activations.
    """
    from . import licensing
    directory = Path(directory)
    licensing.guard(directory, 'update_launcher')
    with graphics_change(directory) as directory:
        previous = (directory / 'session.json').read_bytes()
        cfg = json.loads(previous)
        source = Path(proton_session.__file__)
        digest = core.digest(source)
        if cfg.get('manager_sha256') == digest:
            return {'updated': False, 'manager_sha256': digest}
        manager = directory / ('session-manager-' + digest[:16] + '.py')
        shutil.copy2(source, manager)
        backup = directory / 'configuration-history' / hashlib.sha256(previous).hexdigest()[:16]
        backup.mkdir(parents=True, exist_ok=True)
        for name in ('session.json', 'launch-plugin'):
            if not (backup / name).exists():
                shutil.copy2(directory / name, backup / name)
        cfg['manager_sha256'] = digest
        core.atomic_json(directory / 'session.json', cfg)
        executable(directory / 'launch-plugin', '#!/bin/sh\nunset WINEPREFIX\nexec ' +
                   shlex.join([sys.executable, str(manager), 'launch', str(directory / 'session.json')]) + ' "$@"\n')
        return {'updated': True, 'manager_sha256': digest}


def configure_graphics(directory, policy):
    """Apply graphics settings to an idle environment, preserving its identity.

    This is the documented extension point, so it carries the same guard as the
    recipe path it shares an implementation with. An operation reachable two
    ways must be protected both ways.
    """
    from . import licensing
    licensing.guard(directory, 'configure_graphics')
    with graphics_change(directory) as directory:
        return _configure_graphics_locked(directory, policy)


def _configure_graphics_locked(directory, policy):
    """Caller holds graphics_change through any related provenance writes."""
    from . import ua_connect
    policy = json.loads(json.dumps(proton_session.validate_graphics_policy(policy)))
    previous = (directory / 'session.json').read_bytes()
    cfg = json.loads(previous)
    cfg['graphics_policy'] = policy
    proton_session.prepare_graphics(cfg)
    ua_connect.require_idle_desktop()
    ua_connect.prepare_runtime(directory)
    source = Path(proton_session.__file__)
    digest = core.digest(source)
    manager = directory / ('session-manager-' + digest[:16] + '.py')
    shutil.copy2(source, manager)
    # Preserve one backup per previous config identity, without duplicating prefixes.
    if (directory / 'session.json').read_bytes() != previous:
        raise ValueError('Environment configuration changed during preparation; create a new plan')
    backup = directory / 'configuration-history' / hashlib.sha256(previous).hexdigest()[:16]
    backup.mkdir(parents=True, exist_ok=True)
    for name in ('session.json', 'launch-plugin'):
        if not (backup / name).exists():
            shutil.copy2(directory / name, backup / name)
    cfg['manager_sha256'] = digest
    cfg.pop('diagnostic_mode', None)
    core.atomic_json(directory / 'session.json', cfg)
    executable(directory / 'launch-plugin', '#!/bin/sh\nunset WINEPREFIX\nexec ' +
               shlex.join([sys.executable, str(manager), 'launch', str(directory / 'session.json')]) + ' "$@"\n')
    return cfg
