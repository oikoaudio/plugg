"""Small, data-only recipe graph and recorded graphics configuration operations.

No dynamic imports, shell snippets, downloads, or installer execution in recipes.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import hashlib
import fcntl
import json
import re
import os
from urllib.parse import urlsplit
import tomllib

from . import proton_session, file_requirements, bridge_requirements

ID = re.compile(r'[a-z][a-z0-9-]*(?:\.[a-z0-9-]+)+\Z')
FIELDS = {'schema', 'id', 'revision', 'kind', 'name', 'vendor', 'requires', 'notes', 'purpose', 'graphics', 'modules', 'vc_runtime', 'bridge_patch', 'bridge_requirements', 'required_files', 'helper', 'licensing', 'documentation_only', 'archive_tools', 'powershell', 'helper_profile', 'ntk_daemon', 'existing_setup'}
#: Reserved for recipes shipped with the project, so a third party cannot
#: publish something that reads as official.
RESERVED = 'plugg.'
#: Text shown to people. Bounded, single-line, and without the control or
#: direction-override characters that let a name lie about what it says.
TEXT_LIMITS = {'name': 120, 'vendor': 120, 'purpose': 200, 'notes': 2000}
CONTROL = re.compile(r'[\x00-\x1f\x7f\u200e\u200f\u202a-\u202e\u2066-\u2069]')


def load(path):
    try:
        return _load(path)
    except (OSError, ValueError, RuntimeError) as exc:
        raise ValueError(f"{path}: {exc}") from exc


def _load(path):
    path = Path(path)
    with path.open('rb') as source:
        raw = source.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        raise ValueError('Recipe exceeds 256 KiB')
    data = tomllib.loads(raw.decode('utf-8'))
    unknown = set(data) - FIELDS
    if unknown:
        raise ValueError('Unknown recipe fields: ' + ', '.join(sorted(unknown)))
    for key in ('schema', 'id', 'revision', 'kind', 'name'):
        if key not in data:
            raise ValueError('Missing recipe field: ' + key)
    if type(data['schema']) is not int or data['schema'] != 1:
        raise ValueError('Unsupported recipe schema')
    if not isinstance(data['id'], str) or not ID.fullmatch(data['id']):
        raise ValueError('Recipe id must be namespaced, e.g. local.vendor')
    if type(data['revision']) is not int or data['revision'] < 1:
        raise ValueError('Recipe revision must be a positive integer')
    if data['kind'] not in ('vendor', 'component'):
        raise ValueError('Recipe kind must be vendor or component')
    for key, limit in TEXT_LIMITS.items():
        if key not in data:
            continue
        value = data[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(key + ' must be nonempty text')
        if len(value) > limit:
            raise ValueError(key + ' must be at most %d characters' % limit)
        if CONTROL.search(value):
            raise ValueError(key + ' must not contain control or text-direction characters')
    if 'purpose' in data and data['kind'] != 'component':
        raise ValueError('purpose describes a component: what problem it solves')
    if 'existing_setup' in data and (data['kind'] != 'vendor' or data['existing_setup'] not in ('softube', 'ua-connect')):
        raise ValueError('Unsupported existing-environment setup adapter')
    if 'ntk_daemon' in data and (data['kind'] != 'component' or data['ntk_daemon'] is not True):
        raise ValueError('ntk_daemon requires a component with value true')
    if 'powershell' in data and (data['kind'] != 'component' or data['powershell'] is not True):
        raise ValueError('powershell requires a component with value true')
    if 'helper_profile' in data and (data['kind'] != 'vendor' or data['helper_profile'] != 'native-access' or 'helper' not in data):
        raise ValueError('Unsupported helper profile')
    if 'archive_tools' in data and (data['kind'] != 'component' or data['archive_tools'] is not True):
        raise ValueError('archive_tools requires a component with value true')
    if 'documentation_only' in data and type(data['documentation_only']) is not bool:
        raise ValueError('documentation_only must be a boolean')
    requires = data.setdefault('requires', [])
    if not isinstance(requires, list) or not all(isinstance(x, str) for x in requires):
        raise ValueError('requires must be an array of exact id@revision references')
    for ref in requires:
        parse_ref(ref)
    if len(set(requires)) != len(requires):
        raise ValueError('Duplicate dependency reference')
    if 'helper' in data:
        from . import helper_recipes
        helper_recipes.validate(data['helper'])
        if data.get('helper_profile') == 'native-access' and data['helper']['executable'] != 'Program Files/Native Instruments/Native Access/Native Access.exe':
            raise ValueError('Native Access profile requires the Native Access executable path')
    if 'licensing' in data:
        from . import licensing
        if data['kind'] != 'vendor':
            raise ValueError('licensing describes a vendor whose products hold activations')
        licensing.validate_declaration(data['licensing'])
    if 'graphics' in data:
        g = data['graphics']
        if not isinstance(g, dict) or set(g) - {'default', 'plugins'}:
            raise ValueError('Unknown graphics fields')
        proton_session.validate_graphics_policy({'schema': 1, 'default': g.get('default', 'dxvk'), 'plugins': g.get('plugins', {})})
    if 'required_files' in data:
        file_requirements.validate(data['required_files'])
    if 'bridge_patch' in data:
        patch = data['bridge_patch']
        if data['kind'] != 'component' or not isinstance(patch, dict) or set(patch) != {'sha256'}:
            raise ValueError('bridge_patch requires a component with sha256')
        if not isinstance(patch['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', patch['sha256']):
            raise ValueError('bridge_patch requires an exact SHA-256')
    if 'bridge_requirements' in data:
        requirements = data['bridge_requirements']
        if not isinstance(requirements, dict):
            raise ValueError('bridge_requirements must map module paths to component references')
        proton_session.validate_graphics_policy({'schema': 1, 'default': 'wined3d', 'plugins': {key: 'wined3d' for key in requirements}})
        for refs in requirements.values():
            if not isinstance(refs, list) or not refs:
                raise ValueError('Bridge requirement must be a nonempty component reference array')
            for ref in refs:
                parse_ref(ref)
    if 'vc_runtime' in data:
        asset = data['vc_runtime']
        if data['kind'] != 'component' or not isinstance(asset, dict) or set(asset) != {'url', 'sha256', 'source'}:
            raise ValueError('vc_runtime requires a component with url, sha256 and source')
        if not isinstance(asset['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', asset['sha256']):
            raise ValueError('vc_runtime requires an exact SHA-256')
        # The same check the downloader applies to every redirect hop, so a
        # recipe cannot declare one host and be served from another.
        from . import artifacts
        for field in ('url', 'source'):
            if not isinstance(asset[field], str):
                raise ValueError('vc_runtime URLs must be text')
            parts = urlsplit(asset[field])
            if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.fragment:
                raise ValueError('vc_runtime URLs must use HTTPS without credentials or fragments')
        artifacts.validate_url(asset['url'], artifacts.MICROSOFT_DOWNLOADS, 'vc_runtime')
    if 'modules' in data:
        if data['kind'] != 'vendor' or not data.get('vendor') or not isinstance(data['modules'], dict) or not data['modules']:
            raise ValueError('modules requires a vendor recipe with a vendor name')
        for fingerprint, module in data['modules'].items():
            if not re.fullmatch('[0-9a-f]{64}', fingerprint):
                raise ValueError('Module identity must be an exact SHA-256')
            if not isinstance(module, dict) or set(module) != {'name', 'dependency'}:
                raise ValueError('Module requires name and dependency')
            if not isinstance(module['name'], str) or not module['name'].strip():
                raise ValueError('Module name must be nonempty text')
            parse_ref(module['dependency'])
    return {'data': data, 'sha256': hashlib.sha256(raw).hexdigest(), 'source': str(path.resolve())}


def parse_ref(ref):
    if not isinstance(ref, str) or '@' not in ref:
        raise ValueError('Expected exact recipe reference id@revision')
    identity, revision = ref.rsplit('@', 1)
    if not ID.fullmatch(identity) or not re.fullmatch('[1-9][0-9]*', revision):
        raise ValueError('Invalid recipe reference: ' + ref)
    return identity, int(revision)


def reference(record):
    d = record['data']
    return f"{d['id']}@{d['revision']}"


def catalogue(directories):
    """Load every recipe, refusing the whole catalogue if any file is wrong."""
    records, issues = _catalogue(directories, tolerant=False)
    return records


def usable_catalogue(directories):
    """Load what is usable, and report the rest.

    Recipes are meant to be shared, which means a user's recipe directory will
    eventually contain a file that is broken, or that collides with another.
    Refusing the entire catalogue for one bad file would stop the user adding
    any plug-in at all, with an error naming a recipe rather than what they
    were doing. Runtime paths use this; `recipe check` still uses the strict
    load, so a contributor sees every problem.
    """
    return _catalogue(directories, tolerant=True)


def _catalogue(directories, tolerant):
    records, issues = {}, []
    for directory in directories:
        directory = Path(directory)
        if not directory.exists():
            continue
        if not directory.is_dir():
            raise ValueError('Recipe catalogue path is not a directory: ' + str(directory))
        for path in sorted(directory.glob('*.toml')):
            try:
                record = load(path)
                ref = reference(record)
                if ref in records:
                    raise ValueError(f"Duplicate recipe reference {ref}: {records[ref]['source']} and {record['source']}")
            except ValueError as exc:
                if not tolerant:
                    raise
                issues.append({'source': str(path), 'error': str(exc)})
                continue
            records[ref] = record
    return records, issues


def default_directories():
    return [Path(__file__).parent / 'recipes/community',
            Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'plugg/recipes']


def resolve(records, ref):
    parse_ref(ref)
    ordered, visiting, visited, versions = [], set(), set(), {}
    def visit(key, parents=()):
        chain = (*parents, key)
        route = " -> ".join(chain)
        identity, revision = parse_ref(key)
        if key in visiting:
            raise ValueError('Recipe dependency cycle: ' + route)
        if identity in versions and versions[identity][0] != revision:
            raise ValueError('Conflicting revisions for ' + identity + ': ' +
                             ' -> '.join(versions[identity][1]) + ' conflicts with ' + route)
        versions.setdefault(identity, (revision, chain))
        if key in visited:
            return
        if key not in records:
            raise ValueError('Missing recipe dependency: ' + route)
        visiting.add(key)
        for dependency in records[key]['data']['requires']:
            if dependency in records and records[dependency]['data']['kind'] != 'component':
                raise ValueError('Dependencies must be components: ' + route + ' -> ' + dependency)
            visit(dependency, chain)
        visiting.remove(key)
        visited.add(key)
        ordered.append(records[key])
    visit(ref)
    return ordered


def require_executable(ordered):
    pending = [reference(item) for item in ordered if item['data'].get('documentation_only')]
    if pending:
        raise ValueError('Documentation only; automatic setup is unavailable: ' + ', '.join(pending))


def graphics_requirements(ordered, require_default=True):
    """Compose a resolved graph independently of any local installation."""
    default, plugins = None, {}
    default_owner, plugin_owners = None, {}
    for record in ordered:
        g = record['data'].get('graphics', {})
        if 'default' in g:
            if default is not None and default != g['default']:
                raise ValueError('Conflicting graphics defaults: ' + default_owner + ' (' + default +
                                 ') and ' + reference(record) + ' (' + g['default'] + ')')
            default = g['default']
            default_owner = reference(record)
        for module, backend in g.get('plugins', {}).items():
            if module in plugins and plugins[module] != backend:
                raise ValueError('Conflicting graphics requirements for ' + module + ': ' +
                                 plugin_owners[module] + ' (' + plugins[module] + ') and ' +
                                 reference(record) + ' (' + backend + ')')
            plugins[module] = backend
            plugin_owners[module] = reference(record)
    if default is None and require_default:
        raise ValueError('Recipe graph must declare a graphics default')
    return {'schema': 1, 'default': default, 'plugins': plugins}


def required_bridge_patches(ordered):
    available = {reference(r): r['data']['bridge_patch']['sha256']
                 for r in ordered if 'bridge_patch' in r['data']}
    requirements = {}
    for record in ordered:
        for module, refs in record['data'].get('bridge_requirements', {}).items():
            for ref in refs:
                if ref not in available:
                    raise ValueError('Bridge requirement must resolve to a bridge_patch component: ' + ref)
                requirements.setdefault(module, set()).add(available[ref])
    return {module: sorted(hashes) for module, hashes in sorted(requirements.items())}


def check(records):
    """Validate every graph without reading or provisioning an environment."""
    checked = []
    for ref, record in sorted(records.items()):
        ordered = resolve(records, ref)
        required_bridge_patches(ordered)
        file_requirements.resolve(ordered)
        # Components may intentionally leave the default to their consumer.
        if record['data']['kind'] == 'vendor' and not any(item['data'].get('documentation_only') for item in ordered):
            graphics_requirements(ordered)
        else:
            graphics_requirements(ordered, require_default=False)
        checked.append({'reference': ref, 'dependencies': [reference(r) for r in ordered[:-1]]})
    standalone_catalogue(records)
    from . import helper_recipes
    helper_recipes.catalogue(records)
    return checked


def standalone_catalogue(records, tolerant=False, issues=None):
    """Compile exact module matches for the existing direct-import operation.

    The only executable component is a pinned Microsoft VC redist, with fixed
    installer arguments owned by the importer. Recipes cannot supply commands.
    """
    modules, dependencies, provenance = {}, {}, {}
    for ref, record in sorted(records.items()):
        if not record['data'].get('modules'):
            continue
        try:
            _standalone_recipe(records, ref, record, modules, dependencies, provenance)
        except ValueError as exc:
            if not tolerant:
                raise
            if issues is not None:
                issues.append({'reference': ref, 'error': str(exc)})
            # A contested module identity disables every claim on it.
            for fingerprint in record['data']['modules']:
                modules.pop(fingerprint, None)
                provenance.pop(fingerprint, None)
    return {'schema': 1, 'modules': modules, 'dependencies': dependencies, 'provenance': provenance}


def _standalone_recipe(records, ref, record, modules, dependencies, provenance):
        ordered = resolve(records, ref)
        require_executable(ordered)
        if any(item['data'].get('archive_tools') or item['data'].get('powershell') or item['data'].get('ntk_daemon') for item in ordered):
            raise ValueError('Direct imports cannot provision archive tools; use a helper recipe')
        if any('bridge_patch' in r['data'] or 'bridge_requirements' in r['data'] or 'required_files' in r['data'] for r in ordered):
            raise ValueError('Direct imports cannot provision bridge or existing-file requirements yet')
        graphics = graphics_requirements(ordered)
        if graphics != {'schema': 1, 'default': 'dxvk', 'plugins': {}}:
            raise ValueError('Direct imports currently require the default DXVK profile')
        components = {reference(r): r['data']['vc_runtime'] for r in ordered if 'vc_runtime' in r['data']}
        for fingerprint, module in record['data']['modules'].items():
            if fingerprint in modules:
                raise ValueError('Multiple recipes claim module SHA-256: ' + fingerprint)
            dependency = module['dependency']
            if dependency not in components:
                raise ValueError('Module dependency must resolve to a vc_runtime component: ' + dependency)
            modules[fingerprint] = {**module, 'vendor': record['data']['vendor'],
                                    'recipe': record['data']['id']}
            dependencies[dependency] = components[dependency]
            provenance[fingerprint] = {
                'schema': 1, 'recipe': ref, 'operation': 'import_vst3',
                'input_sha256': fingerprint,
                'recipes': [{'reference': reference(r), 'sha256': r['sha256'], 'resolved': r['data']} for r in ordered],
                'dependency': {'reference': dependency, 'asset': components[dependency]},
            }


def match_input(records, source):
    """Explain an input match without creating a job or starting Wine."""
    from . import standalone, core
    source = Path(source).expanduser().absolute()
    if source.is_symlink():
        raise ValueError('Choose the original input file, not a link')
    if source.suffix.lower() == '.exe':
        from . import helper_recipes
        core.installer_type(source)
        fingerprint = core.digest(source)
        selected = helper_recipes.catalogue(records).get(fingerprint)
        return {'input': str(source), 'sha256': fingerprint, 'kind': 'helper_installer',
                'matched': selected is not None, 'recipe': selected,
                'limitations': ['Exact EXE match only; companion files, existing environments and installer execution have not been checked.']}
    fingerprint = core.digest(standalone.module_path(source))
    spec = standalone_catalogue(records)
    return {'input': str(source), 'sha256': fingerprint,
            'matched': fingerprint in spec['modules'],
            'module': spec['modules'].get(fingerprint),
            'recipe': spec['provenance'].get(fingerprint),
            'limitations': ['Exact module match only; Windows setup, scanning and DAW validation have not run.']}


def plan(records, ref, environment):
    """Read-only plan: does not create a Store or initialize any environment."""
    ordered = resolve(records, ref)
    require_executable(ordered)
    if any(item['data'].get('archive_tools') or item['data'].get('powershell') or item['data'].get('ntk_daemon') for item in ordered):
        raise ValueError('Archive tools are installed through helper recipes, not graphics apply')
    if any('helper' in item['data'] for item in ordered):
        raise ValueError('Helper recipes are applied by adding their exact installer, not graphics apply')
    if any('vc_runtime' in item['data'] or 'modules' in item['data'] for item in ordered):
        raise ValueError('Graphics apply cannot install VC components or import modules; add the matching installer or VST3 instead')
    from . import licensing
    environment = Path(environment).resolve()
    session = (environment / 'session.json').read_bytes()
    cfg = json.loads(session)
    # Read-only: planning reports the licensing position, applying enforces it.
    licence = licensing.status(environment)
    files = file_requirements.resolve(ordered)
    file_checks = file_requirements.verify(cfg, files)
    bridges = required_bridge_patches(ordered)
    bridge_checks = bridge_requirements.verify(environment, bridges)
    requirements = graphics_requirements(ordered)
    default, plugins = requirements['default'], requirements['plugins']
    # Preserve installation-specific overrides not addressed by this recipe.
    previous = cfg.get('graphics_policy', {'schema': 1, 'default': cfg.get('graphics_backend', 'dxvk'), 'plugins': {}})
    policy = {'schema': 1, 'default': default, 'plugins': {**previous.get('plugins', {}), **plugins}}
    proton_session.prepare_graphics({**cfg, 'graphics_policy': policy})
    return {'schema': 1, 'recipe': ref, 'environment': str(environment), 'licensing': licence,
            'bridge_requirements': bridges, 'bridge_checks': bridge_checks,
            'required_files': files, 'file_checks': file_checks,
            'session_sha256': hashlib.sha256(session).hexdigest(),
            'recipes': [{'reference': reference(r), 'sha256': r['sha256'], 'resolved': r['data']} for r in ordered],
            'operation': 'configure_graphics', 'before': previous, 'after': policy,
            'changed': previous != policy,
            'limitations': ['Configures graphics only; does not install runtimes, plugins, licensing components or bridge patches.']}


def apply(plan_data):
    """Apply only a freshly validated plan supplied by the trusted planner."""
    from . import core, licensing, recipes
    environment = Path(plan_data['environment'])
    # An environment holding activations is not a disposable target. This
    # refuses before any lock is taken or any file is written.
    licence = licensing.guard(environment, 'configure_graphics')
    with recipes.graphics_change(environment):
        current = (environment / 'session.json').read_bytes()
        if hashlib.sha256(current).hexdigest() != plan_data['session_sha256']:
            raise ValueError('Environment changed since planning; create a new plan')
        if plan_data['operation'] != 'configure_graphics':
            raise ValueError('Unsupported recipe operation')
        file_checks = file_requirements.verify(json.loads(current), plan_data.get('required_files', {}))
        if file_checks != plan_data.get('file_checks', []):
            raise ValueError('Required component files changed since planning; create a new plan')
        checks = bridge_requirements.verify(environment, plan_data.get('bridge_requirements', {}))
        if checks != plan_data.get('bridge_checks', []):
            raise ValueError('Bridge deployment changed since planning; create a new plan')
        journal = environment / 'recipe-application.json'
        if journal.exists() and json.loads(journal.read_text()).get('status') in ('applying', 'needs-inspection'):
            raise ValueError('Previous recipe application needs inspection; inspect recipe-application.json and configuration-history before retrying')
        launcher = environment / 'launch-plugin'
        before_launcher = launcher.read_bytes() if launcher.exists() else None
        attempt = {'schema': 1, 'status': 'applying', 'plan': plan_data}
        core.atomic_json(journal, attempt)
        try:
            if plan_data['changed']:
                recipes._configure_graphics_locked(environment, plan_data['after'])
            lock = {key: plan_data[key] for key in ('schema', 'recipe', 'recipes', 'operation', 'after')}
            lock['file_checks'] = file_checks
            lock['bridge_checks'] = checks
            lock['licensing'] = {'protected': licence.get('protected', False),
                                 'acknowledged': licence.get('acknowledged', False)}
            lock['applied_session_sha256'] = hashlib.sha256((environment / 'session.json').read_bytes()).hexdigest()
            core.atomic_json(environment / 'recipe-lock.json', lock)
            core.atomic_json(journal, {**attempt, 'status': 'complete',
                                      'applied_session_sha256': lock['applied_session_sha256']})
        except Exception as exc:
            unchanged = ((environment / 'session.json').read_bytes() == current and
                         (launcher.read_bytes() if launcher.exists() else None) == before_launcher)
            core.atomic_json(journal, {**attempt, 'status': 'failed' if unchanged else 'needs-inspection', 'error': str(exc)})
            raise
        return {'changed': plan_data['changed'], 'lock': str(environment / 'recipe-lock.json')}


def recorded_setup(environment):
    """Summarize application records without reading registries or account data."""
    environment = Path(environment)
    issues = []
    def read(name, default):
        path = environment / name
        try:
            with path.open('rb') as source:
                raw = source.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError('record exceeds 1 MiB')
            return json.loads(raw)
        except FileNotFoundError:
            return default
        except (OSError, ValueError) as exc:
            issues.append(name + ': ' + str(exc))
            return default
    metadata = read('environment.json', {})
    session = read('session.json', {})
    if not isinstance(metadata, dict):
        issues.append('environment.json: expected an object')
        metadata = {}
    if not isinstance(session, dict):
        issues.append('session.json: expected an object')
        session = {}
    entry_points = {}
    for key in ('proton', 'runtime_entry'):
        value = session.get(key)
        if isinstance(value, str):
            path = Path(value)
            entry_points[key] = {'path': value, 'exists': path.is_absolute() and path.is_file(),
                                 'executable': path.is_absolute() and path.is_file() and os.access(path, os.X_OK)}
    components = []
    for name in ('dependencies.json', 'archive-components.json'):
        records = read(name, [])
        if not isinstance(records, list):
            issues.append(name + ': expected an array')
            continue
        for item in records:
            if not isinstance(item, dict):
                issues.append(name + ': expected component objects')
                continue
            # URLs may contain credentials or tokens. Display only recorded
            # package labels and hashes, not download or authorization URLs.
            components.append({'record': name, 'package': item.get('package'),
                               'sha256': item.get('sha256')})
    return {'profile': metadata.get('recipe', session.get('recipe')),
            'runtime': metadata.get('runtime'),
            'helper_configured': bool(metadata.get('helper_launcher')),
            'ilok_manager_configured': bool(metadata.get('ilok_launcher')),
            'entry_points': entry_points, 'components': components, 'record_issues': issues,
            'limits': 'Recorded setup only; does not prove component health, authorization or plug-in compatibility.'}


def recorded_requirements(environment, config, lock):
    """Recheck saved evidence; absent evidence remains unknown, not satisfied."""
    issues = []
    complete = True
    for key in ('file_checks', 'bridge_checks'):
        if lock is None or key not in lock:
            complete = False
            continue
        try:
            checks = lock[key]
            if not isinstance(checks, list):
                raise ValueError('expected an array of checks')
            requirements = {}
            for item in checks:
                if not isinstance(item, dict):
                    raise ValueError('expected check objects')
                if key == 'file_checks':
                    scope, path = item['scope'], item['path']
                    target = requirements.setdefault(scope, {})
                    if path in target:
                        raise ValueError('duplicate required file')
                    target[path] = item['sha256']
                else:
                    module, hashes = item['module'], item['required_patches']
                    if not isinstance(hashes, list) or not hashes:
                        raise ValueError('expected required patch hashes')
                    # Reuse scoped path and hash validation for recorded modules.
                    for fingerprint in hashes:
                        file_requirements.validate({'prefix': {module: fingerprint}})
                    if module in requirements:
                        raise ValueError('duplicate required module')
                    requirements[module] = hashes
            if key == 'file_checks':
                observed = file_requirements.verify(config, file_requirements.validate(requirements))
            else:
                observed = bridge_requirements.verify(environment, requirements)
            if observed != checks:
                raise ValueError('component locations or build evidence changed since application')
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            issues.append(key + ': ' + str(exc))
    return {'requirements_match_record': False if issues else (True if complete else None),
            'requirement_issues': issues}


def status(environment):
    """Report provenance drift and incomplete application without writing state."""
    from . import licensing
    environment = Path(environment)
    session_bytes = (environment / 'session.json').read_bytes()
    current = hashlib.sha256(session_bytes).hexdigest()
    config = json.loads(session_bytes)
    lock_path = environment / 'recipe-lock.json'
    journal_path = environment / 'recipe-application.json'
    lock = json.loads(lock_path.read_text()) if lock_path.exists() else None
    journal = json.loads(journal_path.read_text()) if journal_path.exists() else None
    busy = False
    try:
        with (environment / 'graphics-policy.lock').open('r') as held:
            try:
                fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                busy = True
    except FileNotFoundError:
        pass
    return {**recorded_requirements(environment, config, lock),
            'licensing': licensing.status(environment),
            'recorded_setup': recorded_setup(environment), 'operation_busy': busy, 'environment': str(environment), 'recipe': lock.get('recipe') if lock else None,
            'configuration_matches_record': current == lock.get('applied_session_sha256') if lock else None,
            'application_status': journal.get('status') if journal else 'not-recorded',
            'needs_inspection': bool(journal and (journal.get('status') == 'needs-inspection' or
                                                (journal.get('status') == 'applying' and not busy)))}


def add_local(source):
    """Validate and add one local recipe; never replace an existing revision."""
    from . import core
    import tempfile
    source = Path(source)
    candidate = load(source)
    with source.open('rb') as stream:
        raw = stream.read(256 * 1024 + 1)
    if hashlib.sha256(raw).hexdigest() != candidate['sha256']:
        raise ValueError('Recipe changed while being read; try adding it again')
    ref = reference(candidate)
    if candidate['data']['id'].startswith(RESERVED):
        raise ValueError('The ' + RESERVED + ' namespace is reserved for recipes shipped with '
                         'Plugg. Use your own namespace, for example local.' +
                         candidate['data']['id'].split('.', 1)[-1])
    def validate_addition():
        records = catalogue(default_directories())
        existing = records.get(ref)
        if existing and existing['sha256'] != candidate['sha256']:
            raise ValueError('This recipe revision already exists with different contents: ' + ref + '. Use a new revision.')
        records[ref] = candidate
        check(records)
        return existing
    existing = validate_addition()
    if existing:
        return {'reference': ref, 'added': False, 'path': str(existing['source'])}
    directory = default_directories()[-1]
    directory.mkdir(parents=True, exist_ok=True)
    with core.lock(directory / '.add-recipe.lock'):
        existing = validate_addition()
        if existing:
            return {'reference': ref, 'added': False, 'path': str(existing['source'])}
        target = directory / (ref + '.toml')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, prefix='.recipe-', suffix='.tmp', delete=False) as output:
                temporary = Path(output.name)
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            # Atomic, no replacement even if an external editor raced the lock.
            os.link(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return {'reference': ref, 'added': True, 'path': str(target)}


def remove_local(ref):
    """Delete one recipe the user added.

    Only from their own directory: what ships with the application is not
    theirs to delete, and one that another recipe depends on is refused rather
    than leaving the catalogue unusable. An installation this recipe already
    produced keeps working — a finished job holds its own compiled copy of the
    graph and never reads this directory again.
    """
    from . import core
    directory = default_directories()[-1]
    record = catalogue(default_directories()).get(ref)
    if record is None:
        raise ValueError('No such recipe: ' + ref)
    source = Path(record['source']).resolve()
    if source.parent != directory.resolve():
        raise ValueError('Only a recipe you added can be removed. ' + ref +
                         ' is part of the application.')
    with core.lock(directory / '.add-recipe.lock'):
        remaining = {key: value for key, value in catalogue(default_directories()).items()
                     if key != ref}
        check(remaining)
        source.unlink(missing_ok=True)
    return {'reference': ref, 'removed': True, 'path': str(source)}
