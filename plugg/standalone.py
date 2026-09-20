"""Import user-supplied Windows VST3 files and bundles into private environments.
SPDX-License-Identifier: GPL-3.0-or-later
"""
import json
import os
from pathlib import Path
import shutil
import stat
import time
import uuid

from . import core, licensing, recipes, proton_session, vendors, recipe_engine

LIMIT = 2 * 1024**3
#: A bundle of empty directories still costs inodes and space on every copy.
DIRECTORY_COST = 4096
MAX_ENTRIES = 10000
MAX_DEPTH = 32


def module_path(source):
    if source.is_file():
        module = source
    else:
        modules = list((source / 'Contents/x86_64-win').glob('*.vst3'))
        if len(modules) != 1:
            raise core.HostError('Choose a Windows VST3 bundle containing one x86_64-win module.')
        module = modules[0]
    if module.is_symlink() or core.pe_machine(module) != 0x8664:
        raise core.HostError('Only 64-bit Windows VST3 plug-ins are supported.')
    return module


def inventory(root):
    """List a bundle's files, refusing anything that is not a plain tree.

    Directories count toward the entry limit and carry a nominal size: a
    bundle of empty directories costs inodes and space on every copy, so
    counting files alone would let it past both limits. Depth is bounded
    because the copy and the cleanup that follows are recursive.
    """
    entries = []
    size = 0
    counted = 0
    for parent, dirs, files in os.walk(root, followlinks=False):
        depth = len(Path(parent).relative_to(root).parts)
        if depth > MAX_DEPTH:
            raise core.HostError('Plug-in import is nested too deeply.')
        for name in dirs + files:
            path = Path(parent) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise core.HostError('Plug-in imports must contain regular files and folders, without links.')
        counted += len(dirs)
        size += len(dirs) * DIRECTORY_COST
        if size > LIMIT or counted + len(files) > MAX_ENTRIES:
            raise core.HostError('Plug-in import exceeds the size or file-count limit.')
        for name in sorted(files):
            path = Path(parent) / name
            size += path.stat().st_size
            counted += 1
            if size > LIMIT or counted > MAX_ENTRIES:
                raise core.HostError('Plug-in import exceeds the size or file-count limit.')
            entries.append({'path': path.relative_to(root).as_posix(), 'sha256': core.digest(path)})
    return sorted(entries, key=lambda x: x['path'])


def ingest(store, source):
    source = source.expanduser().absolute()
    if source.is_symlink():
        raise core.HostError('Choose the original VST3, not a link.')
    module_path(source)
    job_id = uuid.uuid4().hex
    directory = store.root / 'jobs' / job_id
    payload = directory / 'payload'
    payload.mkdir(parents=True, mode=0o700)
    dest = payload / source.name
    try:
        if source.is_dir():
            inventory(source)
            shutil.copytree(source, dest, symlinks=True)
        else:
            if source.stat().st_size > LIMIT:
                raise core.HostError('Plug-in import exceeds the size limit.')
            shutil.copy2(source, dest)
        # Nothing beside the selection is copied. The folder the user imported
        # from is theirs and may hold anything; documentation that belongs to a
        # plug-in travels inside its bundle, and is copied with it.
        files = inventory(payload)
        module = module_path(dest)
        fingerprint = core.digest(module)
        for previous in store.plugins():
            if previous['hash'] == fingerprint and previous['status'] == 'ready':
                raise core.HostError('This plug-in is already in your library.')
        core.atomic_json(directory / 'import-files.json', {'schema': 1, 'files': files, 'selection': dest.name})
        now = time.time()
        with store.db() as db:
            db.execute('INSERT INTO jobs(id,name,installer,kind,hash,status,message,created,updated,env_id) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (job_id, source.stem, str(dest), 'vst3', fingerprint, 'queued', 'Preparing plug-in import', now, now, job_id))
    except Exception:
        shutil.rmtree(directory)
        raise
    return job_id


def verify(job):
    source = Path(job['installer'])
    data = json.loads((source.parent.parent / 'import-files.json').read_text())
    if data.get('schema') != 1 or data.get('selection') != source.name or inventory(source.parent) != data.get('files'):
        raise core.HostError('Saved plug-in files changed. Import the original download again.')
    if core.digest(module_path(source)) != job['hash']:
        raise core.HostError('Saved plug-in module changed. Import the original download again.')
    return source


def catalogue(issues=None):
    """Compile importable modules, ignoring recipes that cannot be used."""
    records, load_issues = recipe_engine.usable_catalogue(recipe_engine.default_directories())
    if issues is not None:
        issues.extend(load_issues)
    return recipe_engine.standalone_catalogue(records, tolerant=True, issues=issues)


def compatible_environment(store, job, spec, runtime):
    """Reuse only a known vendor with satisfied recorded dependencies and matching runtime.

    Existing first-generation imports can be recognized from their owner's exact
    module hash. Unknown modules never share based on filenames or claimed vendor.

    Sharing is keyed on the owning recipe's identity, not on its vendor string.
    A vendor name is free text that any recipe may claim, so keying on it would
    let one recipe put its plug-in into an environment another recipe built.
    """
    wanted = spec['modules'].get(job['hash'])
    if not wanted:
        return None
    expected = spec['dependencies'][wanted['dependency']]
    seen = set()
    for owner in store.jobs():
        identity = owner['env_id']
        known = spec['modules'].get(owner['hash'])
        if identity in seen or owner['status'] != 'ready' or owner['kind'] != 'vst3' or not known:
            continue
        seen.add(identity)
        if known.get('recipe') != wanted.get('recipe') or not wanted.get('recipe'):
            continue
        directory = store.root / 'environments' / identity
        try:
            cfg = json.loads((directory / 'environment.json').read_text())
            session = json.loads((directory / 'session.json').read_text())
            deps = json.loads((directory / 'dependencies.json').read_text())
            if cfg.get('recipe') != 'standalone-vst3' or cfg.get('status') != 'ready' or expected not in deps:
                continue
            if Path(session['proton']).resolve() != (runtime / 'UMU-Proton-10.0-4/proton').resolve():
                continue
            if Path(session['prefix']).resolve() != (directory / 'prefix').resolve() or session.get('graphics_backend') != 'dxvk':
                continue
            proton_session.graphics_overrides(session)
        except (OSError, ValueError, KeyError, RuntimeError):
            continue
        return identity
    return None


def check_one(store, job_id):
    """Rescan only this import; never republish other residents under a new ID."""
    job = store.job(job_id)
    source = Path(job['installer'])
    target = store.prefix(job_id) / 'drive_c/Program Files/Common Files/VST3' / source.name
    if not target.exists():
        raise core.HostError('This import did not reach plug-in installation. Inspect installation details before adding it again.')
    module = module_path(target)
    # A prefix is not a security boundary: a Windows process can plant a link
    # inside it. Discovery checks containment, so publication does too.
    prefix = store.prefix(job_id).resolve()
    if not module.resolve().is_relative_to(prefix):
        raise core.HostError('The installed module now points outside its environment.')
    fingerprint = core.digest(module)
    if fingerprint != job['hash']:
        raise core.HostError('The installed module changed; managed updates are not supported yet.')
    if vendors.applications(store.prefix(job_id)):
        raise core.HostError('Close this vendor’s plug-ins before checking the installation.')
    store.update(job_id, 'scanning', 'Checking ' + job['name'])
    metadata = core.probe(store, module, job_id)
    if core.digest(module) != fingerprint:
        raise core.HostError('The plug-in changed during discovery.')
    existing = next((p for p in store.plugins() if p['hash'] == fingerprint and p['env_id'] == job['env_id'] and Path(p['module']).resolve() == module.resolve()), None)
    core.publish(store, {'path': module, 'name': module.stem, 'hash': fingerprint}, job_id, metadata, environment=job['env_id'], identity=existing['id'] if existing else None)
    core.atomic_json(store.root / 'jobs' / job_id / 'scan-result.json', {'published': 1, 'failures': []})
    store.update(job_id, 'ready', 'Plug-in is available to your DAW.')


def prepare(store, job_id, job, runtime, spec, report, check):
    prefix = store.prefix(job_id)
    prefix.mkdir(parents=True, exist_ok=True)
    full, _ = recipes.configure(store, job_id, runtime, helper_enabled=False)
    rc = core.run_process([full, 'cmd.exe', '/c', 'exit', '0'], os.environ.copy(), Path(os.devnull), check, 180)
    if rc:
        raise core.HostError('Windows environment initialization failed.')
    # Every new prefix would otherwise invent its own machine identity, so one
    # computer presents as many machines to a vendor counting them.
    licensing.adopt_machine_identity(prefix.parent, [str(full)], os.environ.copy(), check)
    dependency = spec['modules'].get(job['hash'])
    if dependency:
        from . import vc_component
        asset = spec['dependencies'][dependency['dependency']]
        vc_component.install(store, prefix.parent, full, [asset], report, check)
    for _ in range(60):
        check()
        if not proton_session.foreign_prefix_processes(prefix):
            break
        time.sleep(1)
    else:
        raise core.HostError('Windows setup is still running. Wait before checking the plug-in again.')
    proton_session.graphics_overrides(json.loads((prefix.parent / 'session.json').read_text()))
    core.atomic_json(prefix.parent / 'environment.json', {'id': job_id, 'recipe': 'standalone-vst3', 'runtime': 'UMU-Proton-10.0-4', 'sandbox': False, 'status': 'ready', 'session_launcher': str(prefix.parent / 'launch-plugin'), 'graphics_backend': 'dxvk'})



def reconcile_interrupted(store):
    """Mark only journalled imports whose worker lock is no longer held.

    Does not kill Windows processes, install components or replay work.
    """
    return core.reconcile_journalled_jobs(store, 'import-state.json',
        'Import monitoring stopped. Close any setup windows and inspect installation details before checking again.',
        kind='vst3')

def work(store, job_id, rescan=False):
    job = store.job(job_id)
    # Serialize selection and preparation so simultaneous drops cannot create
    # duplicate environments or alter the same installation concurrently.
    with core.lock(store.root / 'standalone-import.lock'), core.lock(store.root / 'jobs' / job_id / 'job.lock', blocking=False):
        # Another queued worker may have finished while we waited for the import lock.
        job = store.job(job_id)
        state_path = store.root / 'jobs' / job_id / 'import-state.json'
        if not rescan and state_path.exists() and job['status'] not in core.TERMINAL:
            store.update(job_id, 'needs_attention', 'An earlier import was interrupted. Inspect its saved setup before trying again.', pid=None)
            raise core.HostError('Interrupted import will not be replayed automatically. See installation details.')
        if not rescan and job['status'] in core.TERMINAL:
            raise core.HostError('This import already finished. Use Check again to rescan it.')
        stage = None
        def record_stage(value, status='running', error=None):
            nonlocal stage
            stage = value
            core.atomic_json(state_path, {'schema': 1, 'stage': stage, 'status': status,
                                         'input_sha256': job['hash'], 'environment': store.job(job_id)['env_id'],
                                         **({'error': error} if error else {})})
        try:
            check = lambda: store.cancelled(job_id)
            report = lambda msg: store.update(job_id, 'preparing', msg, pid=os.getpid())
            store.bridge()
            if rescan:
                if state_path.exists() and json.loads(state_path.read_text()).get('stage') not in ('scanning', 'complete'):
                    raise core.HostError('Import setup or file copying did not finish. Inspect installation details before adding it again.')
                store.update(job_id, 'scanning', 'Checking imported VST3', cancel=0)
                check_one(store, job_id)
                if state_path.exists():
                    record_stage('complete', status='complete')
                return
            source = verify(job)
            report('Preparing Windows plug-in support')
            spec = catalogue()
            # Record resolved intent before runtime or prefix changes. Existing
            # environments and rescans do not re-resolve or replay this recipe.
            provenance = spec.get('provenance', {}).get(job['hash'])
            if provenance:
                core.atomic_json(store.root / 'jobs' / job_id / 'recipe-lock.json', provenance)
            record_stage('preparing-runtime')
            runtime = recipes.provision(store, report, check)
            record_stage('preparing-environment')
            shared = compatible_environment(store, job, spec, runtime)
            if shared:
                prefix = store.root / 'environments' / shared / 'prefix'
                # Joining an environment someone else activated is exactly what
                # the licensing guard exists to stop.
                licensing.guard(prefix.parent, 'import_module')
                if vendors.applications(prefix):
                    raise core.HostError('Close this vendor’s plug-ins, then import again to reuse their environment.')
                with store.db() as db:
                    db.execute('UPDATE jobs SET env_id=? WHERE id=?', (shared, job_id))
                report('Using the existing compatible vendor environment')
            else:
                prepare(store, job_id, job, runtime, spec, report, check)
                prefix = store.prefix(job_id)
            record_stage('installing-files')
            install_root = prefix / 'drive_c/Program Files/Common Files/VST3'
            install_root.mkdir(parents=True, exist_ok=True)
            target = install_root / source.name
            if target.exists() or target.is_symlink():
                raise core.HostError('An installed file already uses this name. It has been left unchanged.')
            verify(job)
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
            # Only what the library already holds for this import; nothing is
            # read from the user's folder a second time.
            documents = prefix.parent / 'documents' / job_id
            documents.mkdir(parents=True, exist_ok=True)
            for p in sorted(source.parent.glob('*.txt')):
                if p.is_file() and not p.is_symlink():
                    shutil.copy2(p, documents / p.name)
            core.atomic_json(store.root / 'jobs' / job_id / 'environment-selection.json', {'environment': store.job(job_id)['env_id'], 'reused': bool(shared), 'dependency_changes': False if shared else bool(spec['modules'].get(job['hash']))})
            record_stage('scanning')
            check_one(store, job_id)
            record_stage('complete', status='complete')
        except core.Cancelled as exc:
            if stage:
                record_stage(stage, status='cancelled', error=str(exc))
            store.update(job_id, 'cancelled', str(exc))
            raise
        except Exception as exc:
            if stage:
                record_stage(stage, status='failed', error=str(exc))
            previous = [p for p in store.plugins() if p['hash'] == job['hash'] and p['status'] == 'ready']
            store.update(job_id, 'ready' if rescan and previous else 'failed', str(exc))
            raise
        finally:
            with store.db() as db:
                db.execute('UPDATE jobs SET pid=NULL WHERE id=?', (job_id,))
