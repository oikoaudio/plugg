"""Exact-installer helper recipes using the existing managed Proton operations."""
import json
import os
from pathlib import Path
import re
import time

from . import core, helper_component, licensing


def validate(data):
    if not isinstance(data, dict) or set(data) != {'installer_sha256', 'arguments', 'name', 'executable', 'archive_tools'}:
        raise ValueError('Helper recipe requires installer_sha256, arguments, name, executable and archive_tools')
    if not isinstance(data['installer_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', data['installer_sha256']):
        raise ValueError('Helper installer requires an exact SHA-256')
    validate_arguments(data['arguments'])
    helper_component.validate({key: data[key] for key in ('name', 'executable', 'archive_tools')})
    return data


#: A drive reference in an installer argument. Wine maps Z: to the host root,
#: so an argument naming any drive but C: can direct a genuine vendor installer
#: to write outside its environment. The separator is optional on purpose:
#: "Z:tmp\\x" is drive-relative and just as effective as "Z:\\tmp\\x".
DRIVE = re.compile(r'([A-Za-z]):')
#: A network or device path, in either slash spelling.
NETWORK = re.compile(r'(?:\A|[=:])(?:[\\/]{2}|[\\/][.?][\\/])')
MAX_ARGUMENTS = 24
MAX_ARGUMENT = 256


def rooted(argument):
    """Does this argument name a path from the root of the current drive?

    The installer runs with its working directory on the host side, which
    Windows sees as Z:, so a rooted path reaches the host filesystem exactly as
    an explicit Z: would. A switch and a path are not distinguishable by
    inspection — "/S" is a switch and "/tmp/x" is a path — so the rule is: a
    leading backslash is always a path, a leading slash is a path only once a
    second separator appears, and any value after "=" is a path if it starts
    with a separator. That leaves the vendor's real switches usable.
    """
    head, _, value = argument.partition('=')
    if head.startswith('\\'):
        return True
    if head.startswith('/') and ('/' in head[1:] or '\\' in head):
        return True
    return value.startswith('/') or value.startswith('\\')


def validate_arguments(arguments):
    """Constrain installer arguments to switches, not filesystem instructions.

    Arguments are passed verbatim to a Windows installer that the recipe does
    not own, so the installer's own switch surface is the attack surface: an
    output-directory or log switch pointed at the host through Wine's Z: drive
    would make a trusted installer write wherever the recipe chooses. Recipes
    may say how to install silently; they may not say where.
    """
    if not isinstance(arguments, list) or any(not isinstance(item, str) for item in arguments):
        raise ValueError('Helper installer arguments must be a text array')
    if len(arguments) > MAX_ARGUMENTS:
        raise ValueError('Helper installer takes at most %d arguments' % MAX_ARGUMENTS)
    for argument in arguments:
        if len(argument) > MAX_ARGUMENT:
            raise ValueError('Helper installer argument is too long')
        if any(character in argument for character in '\0\r\n'):
            raise ValueError('Helper installer arguments must be single-line text')
        if '..' in argument:
            raise ValueError('Helper installer arguments must not contain "..": ' + argument)
        if '\\\\' in argument or NETWORK.search(argument):
            raise ValueError('Helper installer arguments must not name a network or device path: ' + argument)
        if '%' in argument:
            raise ValueError('Helper installer arguments must not expand Windows variables: ' + argument)
        if rooted(argument):
            raise ValueError('Helper installer arguments must not name a path from the root of a '
                             'drive; write it relative to C: instead: ' + argument)
        for drive in DRIVE.findall(argument):
            if drive.lower() != 'c':
                raise ValueError('Helper installer arguments may only name drive C: ' + argument)
    return arguments


def catalogue(records, tolerant=False, issues=None):
    """Compile helper recipes. Tolerant loading skips one bad recipe, not all."""
    from . import recipe_engine as engine, recipes
    result = {}
    for ref, record in records.items():
        data = record['data']
        if any(other['data']['id'] == data['id'] and other['data']['revision'] > data['revision'] for other in records.values()):
            continue
        if 'helper' not in data:
            continue
        try:
            helper = validate(data['helper'])
        except ValueError as exc:
            if not tolerant:
                raise
            _note(issues, ref, exc)
            continue
        try:
            if data['kind'] != 'vendor' or data.get('modules'):
                raise ValueError('Helper recipes must be vendors without direct-import modules')
            ordered = engine.resolve(records, ref)
            engine.require_executable(ordered)
            helper = dict(helper, archive_tools=helper['archive_tools'] or any(
                item['data'].get('archive_tools') for item in ordered))
            if any(any(key in item['data'] for key in ('required_files', 'bridge_requirements', 'bridge_patch')) for item in ordered):
                raise ValueError('Helper setup does not yet provision patched runtime or bridge requirements')
            if engine.graphics_requirements(ordered) != {'schema': 1, 'default': 'dxvk', 'plugins': {}}:
                raise ValueError('Helper setup currently requires the default DXVK profile')
            if any(item['data'].get('ntk_daemon') for item in ordered) and data.get('helper_profile') != 'native-access':
                raise ValueError('NTKDaemon requires the Native Access helper profile')
            fingerprint = helper['installer_sha256']
            if fingerprint in result:
                raise ValueError('Ambiguous helper installer: ' + result[fingerprint]['reference'] + ' and ' + ref)
        except ValueError as exc:
            if not tolerant:
                raise
            _note(issues, ref, exc)
            # An ambiguous claim disables both: neither recipe may quietly win.
            result.pop(helper['installer_sha256'], None)
            continue
        base = recipes.recipe()
        result[fingerprint] = {'schema': 1, 'reference': ref, 'vendor': data.get('vendor', data['name']),
                               'licensing': data.get('licensing'),
                               'runtime_assets': base['runtimes'],
                               'vc_assets': [item['data']['vc_runtime'] for item in ordered if 'vc_runtime' in item['data']],
                               'archive_assets': base['packages'] if helper['archive_tools'] else [],
                               'helper': helper, 'recipes': [{'reference': engine.reference(item),
                                'sha256': item['sha256'], 'resolved': item['data']} for item in ordered]}
        if any(item['data'].get('powershell') for item in ordered):
            from . import powershell_component
            result[fingerprint]['powershell_asset'] = powershell_component.ASSET
        if any(item['data'].get('ntk_daemon') for item in ordered):
            from . import ntk_component
            result[fingerprint]['ntk_daemon'] = ntk_component.SPEC
        if data.get('helper_profile'):
            result[fingerprint]['helper_profile'] = data['helper_profile']
    return result


def _note(issues, ref, exc):
    if issues is not None:
        issues.append({'reference': ref, 'error': str(exc)})


def match(fingerprint, issues=None):
    """Find the recipe claiming this installer, ignoring unusable ones.

    A recipe directory is shared material. One broken or conflicting file must
    not stop the user from adding an installer that nothing claims.
    """
    from . import recipe_engine as engine
    records, load_issues = engine.usable_catalogue(engine.default_directories())
    if issues is not None:
        issues.extend(load_issues)
    return catalogue(records, tolerant=True, issues=issues).get(fingerprint)


def replaces_builtin(selected, fingerprint):
    from . import recipe_engine as engine
    if selected.get('reference') != 'plugg.klevgrand@1':
        return False
    records = engine.catalogue([Path(__file__).parent / 'recipes/community'])
    return selected == catalogue(records).get(fingerprint)


#: Setup stages that run no vendor code.
BEFORE_VENDOR_CODE = ('preparing-runtime', 'preparing-environment')


def work(store, job_id):
    from . import recipes, vendors, proton_session, recipe_engine as engine
    job_directory = store.root / 'jobs' / job_id
    with core.lock(store.root / 'helper-setup.lock', blocking=False), core.lock(job_directory / 'job.lock', blocking=False):
        job = store.job(job_id)
        if job['status'] in core.TERMINAL:
            raise core.HostError('This setup already finished; open its helper instead.')
        try:
            selected = json.loads((job_directory / 'helper-recipe.json').read_text())
            # Recompile the saved graph rather than consulting changed local recipes.
            records = {item['reference']: {'data': item['resolved'], 'sha256': item['sha256']}
                       for item in selected['recipes']}
            expected = catalogue(records).get(job['hash'])
            if expected != selected:
                raise core.HostError('Saved helper recipe is inconsistent; inspect the installation record.')
            identity = engine.parse_ref(selected['reference'])[0]
            for card in vendors.cards(store):
                if card['job'] == job_id:
                    continue
                _, cfg = vendors.configuration(store, card['job'])
                if (cfg.get('recipe_reference', '').split('@')[0] == identity or
                        (identity == 'plugg.klevgrand' and cfg.get('recipe') == 'klevgrand') or
                        (identity == 'plugg.native-instruments' and cfg.get('recipe') == 'native-instruments-experiment')):
                    raise core.HostError('This helper is already configured; open its existing card.')
            # An interrupted installer may have created licensing state before
            # its manager card existed. Its journal also reserves the identity.
            for other in store.jobs():
                if other['id'] == job_id:
                    continue
                other_journal = store.root / 'jobs' / other['id'] / 'helper-setup.json'
                if other_journal.is_file():
                    earlier = json.loads(other_journal.read_text())
                    reserved = earlier.get('reference', '')
                    # A setup that failed before the vendor's installer ran has
                    # nothing of the vendor's to inspect: only Plugg's own launch
                    # files and, at most, this computer's machine identity.
                    if other['status'] == 'failed' and earlier.get('stage') in BEFORE_VENDOR_CODE:
                        continue
                    if reserved.split('@')[0] == identity:
                        raise core.HostError('An earlier setup of this helper needs inspection; reuse or resolve it before creating another environment.')
            journal = job_directory / 'helper-setup.json'
            if journal.exists():
                raise core.HostError('Previous helper setup needs inspection; automatic replay is disabled.')
            prefix = store.prefix(job_id)
            if prefix.exists():
                raise core.HostError('Helper setup requires a fresh environment; existing environments are preserved.')
            spec = {key: selected['helper'][key] for key in ('name', 'executable', 'archive_tools')}
            check = lambda: store.cancelled(job_id)
            def report(message):
                store.update(job_id, 'preparing', message, pid=os.getpid())
            def stage(name):
                core.atomic_json(journal, {'schema': 1, 'stage': name, 'reference': selected['reference']})
            core.verify_installer(job)
            if selected.get('ntk_daemon'):
                from . import ntk_component
                ntk_component.require_available(prefix.parent)
            stage('preparing-runtime')
            runtime = recipes.provision(store, report, check)
            prefix.mkdir(parents=True)
            with core.lock(prefix.parent / 'helper.lock', blocking=False):
                stage('preparing-environment')
                full, launcher = recipes.configure(store, job_id, runtime, helper_spec=spec)
                # Before any vendor component runs in this environment.
                licensing.adopt_machine_identity(prefix.parent, [str(full)], os.environ.copy(),
                                                 check, timeout=600)
                if selected.get('powershell_asset'):
                    from . import powershell_component
                    stage('preparing-powershell')
                    powershell_component.install(store, prefix.parent, full, report, check)
                if selected['vc_assets']:
                    from . import vc_component
                    stage('preparing-vc-runtime')
                    vc_component.install(store, prefix.parent, full, selected['vc_assets'], report, check)
                stage('installing-helper')
                store.update(job_id, 'installing', 'Installing ' + spec['name'])
                helper_component.install(job, prefix, full, spec, selected['helper']['arguments'], check)
                if selected.get('ntk_daemon'):
                    from . import ntk_component
                    stage('installing-native-access-service')
                    ntk_component.install(prefix.parent, full, report, check)
                if spec['archive_tools']:
                    stage('preparing-components')
                    from . import archive_component
                    archive_component.install(store, prefix, selected['archive_assets'], report, check)
                proton_session.graphics_overrides(json.loads((prefix.parent / 'session.json').read_text()))
                for _ in range(60):
                    check()
                    if not proton_session.foreign_prefix_processes(prefix):
                        break
                    time.sleep(1)
                else:
                    raise core.HostError('Close the installer and helper before checking this installation.')
                core.atomic_json(prefix.parent / 'environment.json', {
                    'id': job['env_id'], 'recipe': 'managed-helper', 'recipe_reference': selected['reference'],
                    'display_name': spec['name'], 'vendor': selected['vendor'], 'runtime': 'UMU-Proton-10.0-4',
                    'helper_launcher': str(launcher), 'session_launcher': str(prefix.parent / 'launch-plugin'),
                    'helper_owns_runtime': True, 'automatic_updates': False, 'sandbox': False,
                    **({'helper_profile': selected['helper_profile']} if selected.get('helper_profile') else {})})
                if selected.get('helper_profile') == 'native-access':
                    from . import native_access
                    native_access.configure(prefix.parent)
                # Protected before the first activation exists, not after
                # someone thinks to ask what a rebuild would cost.
                licensing.protect_declared(prefix.parent, selected.get('licensing'))
                stage('scanning')
                scan = vendors.finish_installation(store, job_id)
                stage('complete')
                if scan['failures']:
                    store.update(job_id, 'needs_attention', spec['name'] +
                                 ' is installed, but some plug-ins need attention. ' + scan['failures'][0])
                else:
                    store.update(job_id, 'ready', spec['name'] + ' is ready. Open Helper to install products.')
        except core.Cancelled as exc:
            store.update(job_id, 'cancelled', str(exc))
            raise
        except Exception as exc:
            store.update(job_id, 'failed', str(exc))
            raise
        finally:
            with store.db() as db:
                db.execute('UPDATE jobs SET pid=NULL WHERE id=?', (job_id,))


def reconcile_interrupted(store):
    return core.reconcile_journalled_jobs(store, 'helper-setup.json',
        'Helper setup monitoring stopped. Close any installer windows and inspect this installation before continuing.')
