"""What a recipe touches, and which of it is dangerous.

Recipes are meant to be shared, and a shared recipe is someone else's code
running against your licensed Windows environments. The defence is not review
effort: it is that a recipe is *data*, so everything it can do is computable
from the file. This module turns a resolved recipe graph into a fixed set of
capabilities, a plain-language summary, and flags for the moves that deserve a
person's attention — deterministically, so a review tool or CI job produces the
same answer every time and a human is only asked about what was flagged.

Capabilities also give contributions a ceiling. Where a recipe lives decides
what it is allowed to declare, so an unreviewed recipe cannot ask to run a
vendor installer at all: the check fails before anyone reads it.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import json

#: Everything a recipe can cause to happen, in the user's words.
CAPABILITIES = {
    'setup-ua-existing': 'Install verified UA Connect files, archive tools and its service in an existing PACE environment; requires prior Electron compatibility consent',
    'setup-softube-existing': 'Install verified Softube files and register its service in an existing protected PACE environment; preserve licensing and runtime',
    'install-ntk-daemon': 'Install the pinned bundled NTKDaemon service and start it with Native Access',
    'install-powershell': 'Install pinned Microsoft PowerShell and the source-built forwarding launcher',
    'native-access-session': 'Manage Native Access background services and its browser sign-in handoff',
    'configure-graphics': 'Change which graphics driver an environment uses',
    'create-environment': 'Create a new Windows environment',
    'join-environment': 'Install into a Windows environment that already exists',
    'import-module': 'Copy an exact Windows plug-in you already have into an environment',
    'claim-module': 'Recognize a plug-in file by hash and decide how it is installed',
    'claim-installer': 'Recognize an installer by hash and decide how it is run',
    'download-component': 'Download a pinned Microsoft runtime and run it',
    'run-vendor-installer': 'Run a Windows installer you supply, with arguments this recipe chooses',
    'prepare-archive-tools': 'Install the pinned archive utilities into an environment',
    'require-bridge-patch': 'Require a patched build of the audio bridge',
    'require-existing-files': 'Require specific files to already be present in an environment',
}

#: What each tier may declare. A recipe is refused if it exceeds its tier, so
#: the ceiling is enforced by the check rather than by whoever reads the diff.
TIERS = {
    # join-environment is inherent to importing a module: an import may reuse an
    # environment its own recipe already built. It is capped by two other
    # things, not by this ceiling — reuse is keyed on the owning recipe's
    # identity, and the licensing guard refuses a protected environment that no
    # longer matches what its activations were issued to.
    'community': {'configure-graphics', 'create-environment', 'join-environment',
                  'import-module', 'claim-module', 'download-component'},
    'reviewed': {'configure-graphics', 'create-environment', 'join-environment',
                 'import-module', 'claim-module', 'claim-installer',
                 'download-component', 'run-vendor-installer', 'prepare-archive-tools',
                 'install-powershell', 'native-access-session', 'install-ntk-daemon'},
    'shipped': set(CAPABILITIES),
    #: A recipe the user wrote for themselves. No ceiling; the report is still
    #: shown, because "I wrote it" and "I read it" are not the same thing.
    'local': set(CAPABILITIES),
}

TIER_ORDER = ('community', 'reviewed', 'shipped', 'local')

#: Severity of each flagged move. These are judgements about what a person
#: should look at, not a claim that flagged recipes are malicious.
LEVELS = ('note', 'caution', 'danger')


def tier_for(source, package_root=None):
    """Infer a recipe's tier from the directory that immediately contains it.

    Matching a tier name anywhere in the path would let a file at
    recipes/community/reviewed/x.toml claim the reviewed ceiling while a
    reviewer's eye reads "community". Only a direct child of recipes/<tier>
    counts, and anything else under recipes/ is refused rather than inferred.
    """
    path = Path(source).resolve()
    package = Path(package_root or Path(__file__).parent).resolve()
    if package in path.parents:
        return 'shipped'
    parts = path.parts
    if len(parts) >= 3 and parts[-3] == 'recipes' and parts[-2] in ('reviewed', 'community'):
        return parts[-2]
    if 'recipes' in parts[:-1] and {'reviewed', 'community'} & set(parts[:-1]):
        raise ValueError('A recipe under a tier directory must be a direct child of '
                         'recipes/community or recipes/reviewed, so that the directory a '
                         'reviewer reads is the one that decides its ceiling: ' + str(source))
    # A recipe anywhere else is the user's own, which has no ceiling to escape.
    return 'local'


def capabilities(ordered, record):
    """The fixed capability set a resolved graph declares.

    Every field is read from the whole graph, including the root, so a
    capability cannot be hidden one dependency deep. The engine refuses some of
    those graphs for other reasons; the report should still describe them
    honestly rather than rely on that refusal.
    """
    if record['data'].get('existing_setup'):
        action = 'setup-ua-existing' if record['data']['existing_setup'] == 'ua-connect' else 'setup-softube-existing'
        return {action, 'join-environment', 'require-existing-files'}
    found = set()
    for item in [*ordered, record]:
        declared = item['data']
        if declared.get('existing_setup'):
            found.update(('setup-softube-existing', 'join-environment'))
        if declared.get('ntk_daemon'):
            found.add('install-ntk-daemon')
        if declared.get('powershell'):
            found.add('install-powershell')
        if declared.get('helper_profile'):
            found.add('native-access-session')
        if declared.get('archive_tools'):
            found.add('prepare-archive-tools')
        if 'graphics' in declared:
            found.add('configure-graphics')
        if 'vc_runtime' in declared:
            found.add('download-component')
        if 'bridge_patch' in declared or 'bridge_requirements' in declared:
            found.add('require-bridge-patch')
        if 'required_files' in declared:
            found.add('require-existing-files')
        if 'modules' in declared:
            found.update({'import-module', 'claim-module', 'create-environment', 'join-environment'})
        if 'helper' in declared:
            found.update({'claim-installer', 'run-vendor-installer', 'create-environment'})
            if declared['helper'].get('archive_tools'):
                found.add('prepare-archive-tools')
    return found


def component_evidence(record):
    """Historical evidence belongs to exact recipe bytes, not a familiar name."""
    from . import recipe_engine as engine
    path = Path(__file__).parent / 'recipes/component-evidence.json'
    try:
        entries = json.loads(path.read_text())
        evidence = entries.get(engine.reference(record))
        if evidence and evidence['recipe_sha256'] == record['sha256']:
            return evidence
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def revision_note(records, ref):
    """Describe shared graphics settings and added dependencies, without implying a patch revision."""
    from . import recipe_engine as engine
    data = records[ref]['data']
    previous = [item for item in records.values()
                if item['data']['id'] == data['id']
                and item['data']['revision'] < data['revision']]
    if not previous or data['kind'] != 'vendor':
        return None
    earlier = max(previous, key=lambda item: item['data']['revision'])
    before = engine.graphics_requirements(engine.resolve(records, engine.reference(earlier)), require_default=False)
    after = engine.graphics_requirements(engine.resolve(records, ref), require_default=False)
    if not data.get('graphics') or before != after:
        return None
    added = sorted(set(data['requires']) - set(earlier['data']['requires']))
    if not added:
        return None
    names = ', '.join(records[item]['data']['name'] for item in added)
    return ('Same graphics settings as recipe revision %s. Adds a requirement for: %s.'
            % (earlier['data']['revision'], names))


def runtime_description(ordered, record):
    """Describe provisioning or recorded evidence, never infer a live environment."""
    if record['data']['kind'] != 'vendor':
        return None
    if record['data'].get('existing_setup'):
        return {'summary': 'Uses the selected environment’s existing Proton runtime',
                'details': [('Requires existing PACE and the recorded OLE32 editor fix.' if record['data']['existing_setup'] == 'ua-connect' else 'Requires existing PACE, PowerShell and DXVK.') + ' Does not install or replace the runtime or licensing components.'],
                'assets': []}
    if any(item['data'].get('documentation_only') for item in ordered):
        recorded = [component_evidence(item) for item in ordered
                    if item['data']['kind'] == 'component']
        names = sorted({item['runtime'] for item in recorded if item and item.get('runtime')})
        return {'summary': (', '.join(names) if names else 'Not specified') + ' · fresh setup not automated',
                'details': [('Recorded from the working local setup. ' if names else '') +
                            'Fresh automated provisioning is not implemented; this recipe does not install a runtime.'],
                'assets': []}
    if 'helper' in record['data'] or 'modules' in record['data']:
        from . import recipes
        from urllib.parse import urlsplit
        assets = recipes.recipe()['runtimes']
        # Use the same shipped pins as the provisioner, not a parallel version label.
        tag = urlsplit(assets[0]['url']).path.split('/releases/download/', 1)[1].split('/')[0]
        name = tag.replace('UMU-Proton-', 'UMU-Proton ', 1)
        return {'summary': name + ' · pinned for new installations',
                'details': ['Proton build supplied by Open Wine Components (UMU-Proton).',
                            'These are the setup defaults, not an inspection of an installed environment.'],
                'assets': assets}
    return {'summary': 'Uses the selected environment’s runtime',
            'details': ['Changes settings or checks requirements without selecting or replacing the runtime.'],
            'assets': []}


def report(records, ref, source=None, tier=None):
    """Describe one recipe: what it touches, and what deserves attention."""
    from . import recipe_engine as engine
    record = records[ref]
    data = record['data']
    ordered = engine.resolve(records, ref)
    declared = capabilities(ordered, record)
    tier = tier or tier_for(source or record['source'])
    allowed = TIERS.get(tier, set())
    downloads = [{'component': engine.reference(item), 'url': item['data']['vc_runtime']['url'],
                  'sha256': item['data']['vc_runtime']['sha256'],
                  'documented_at': item['data']['vc_runtime']['source']}
                 for item in ordered if 'vc_runtime' in item['data']]
    for item in ordered:
        if item['data'].get('powershell'):
            from . import powershell_component
            downloads.append({'component': engine.reference(item), **powershell_component.ASSET})
    if data.get('existing_setup'):
        downloads = []
    graphics = engine.graphics_requirements(ordered, require_default=False)
    result = {
        'schema': 1,
        'reference': ref,
        'name': data['name'],
        'vendor': data.get('vendor'),
        'kind': data['kind'],
        'existing_setup': data.get('existing_setup'),
        'documentation_only': any(item['data'].get('documentation_only') for item in ordered),
        'evidence': component_evidence(record) if data['kind'] == 'component' else None,
        'tier': tier,
        'source': str(source or record['source']),
        'sha256': record['sha256'],
        'notes': data.get('notes'),
        'revision_note': revision_note(records, ref),
        'runtime': runtime_description(ordered, record),
        'components': [{'reference': engine.reference(item), 'name': item['data']['name'],
                        'purpose': item['data'].get('purpose')}
                       for item in ordered if engine.reference(item) != ref],
        'capabilities': sorted(declared),
        'capability_descriptions': {name: CAPABILITIES[name] for name in sorted(declared)},
        'downloads': downloads,
        'graphics': graphics,
        'claims': claims(data),
        'runs': runs(data),
        'exceeds_tier': sorted(declared - allowed),
    }
    result['flags'] = flags(result)
    result['verdict'] = verdict(result)
    return result


def claims(data):
    """Artifacts this recipe recognizes by hash but does not ship."""
    found = [{'kind': 'module', 'sha256': fingerprint, 'name': module['name']}
             for fingerprint, module in sorted(data.get('modules', {}).items())]
    if 'helper' in data:
        found.append({'kind': 'installer', 'sha256': data['helper']['installer_sha256'],
                      'name': data['helper']['name']})
    return found


def runs(data):
    """Every executable this recipe causes to run, with its exact arguments."""
    if 'helper' not in data:
        return []
    helper = data['helper']
    return [{'what': 'the installer you supply', 'identified_by': helper['installer_sha256'],
             'arguments': list(helper['arguments']),
             'then_opens': helper['executable']}]


def flags(result):
    """The moves a person should look at, worst first."""
    found = []

    def flag(level, code, message):
        found.append({'level': level, 'code': code, 'message': message})

    if result['exceeds_tier']:
        flag('danger', 'exceeds-tier',
             'Declares more than a %s recipe may: %s.' % (result['tier'], ', '.join(result['exceeds_tier'])))
    for run in result['runs']:
        flag('danger', 'runs-vendor-installer',
             'Runs %s with arguments this recipe chooses: %s' %
             (run['what'], ' '.join(run['arguments']) or '(none)'))
        if any(character in argument for argument in run['arguments'] for character in '\\/='):
            flag('caution', 'arguments-name-locations',
                 'Installer arguments contain paths or assignments; check where they point: ' +
                 ' '.join(argument for argument in run['arguments']
                          if any(character in argument for character in '\\/=')))
    for claim in result['claims']:
        if claim['kind'] == 'installer':
            flag('caution', 'claims-third-party-installer',
                 'Binds itself to an installer it does not ship (%s…). If you obtain that installer '
                 'yourself, this recipe decides how it runs.' % claim['sha256'][:12])
    for download in result['downloads']:
        flag('caution', 'downloads-and-runs',
             'Downloads and runs %s (pinned %s…).' % (download['url'], download['sha256'][:12]))
    if 'require-bridge-patch' in result['capabilities']:
        flag('danger', 'requires-bridge-patch',
             'Checks for the required audio bridge patches. Does not install or replace the bridge.')
    if 'require-existing-files' in result['capabilities']:
        flag('caution', 'requires-existing-files',
             'Requires specific files to already be present in the environment.')
    if 'join-environment' in result['capabilities']:
        flag('caution', 'joins-existing-environment',
             'May install into an environment that already exists, which can be one holding your activations.')
    overrides = result['graphics'].get('plugins') or {}
    if not result.get('existing_setup') and (result['graphics'].get('default') or overrides):
        flag('note', 'configures-graphics',
             'Sets the graphics driver%s.' % (' for %d module(s)' % len(overrides) if overrides else ''))
    if len(result['components']) > 6:
        flag('note', 'many-components',
             'Pulls in %d components.' % len(result['components']))
    order = {level: index for index, level in enumerate(reversed(LEVELS))}
    return sorted(found, key=lambda item: order[item['level']])


def verdict(result):
    if result['exceeds_tier']:
        return 'refused'
    if any(item['level'] == 'danger' for item in result['flags']):
        return 'needs-review'
    if any(item['level'] == 'caution' for item in result['flags']):
        return 'check-the-details'
    return 'routine'


VERDICTS = {
    'refused': 'Refused: declares more than its tier allows.',
    'needs-review': 'Needs a person to look at it.',
    'check-the-details': 'Ordinary for this kind of recipe; check the details below.',
    'routine': 'Changes settings only.',
}


def render(result, markdown=False):
    """A bird's-eye view, for a terminal or a pull request comment."""
    bullet = '- ' if markdown else '  • '
    heading = (lambda text: '### ' + text) if markdown else (lambda text: text)
    lines = [heading('%s (%s)' % (result['name'], result['reference'])),
             '%s · tier: %s · %s' % (result['kind'], result['tier'], VERDICTS[result['verdict']])]
    if result.get('existing_setup'):
        lines.append('Existing-environment setup is available through recipe setup-existing with your installer. Fresh PACE provisioning is not automated.')
    elif result.get('documentation_only'):
        lines.append('Documentation only. Automatic setup is unavailable; existing installations are not changed.')
    if result['notes']:
        lines.append(result['notes'])
    lines.append('')
    lines.append(heading('What it can do'))
    for name in result['capabilities']:
        lines.append(bullet + CAPABILITIES[name])
    if not result['capabilities']:
        lines.append(bullet + 'Nothing on its own; it is a building block for other recipes.')
    if result['flags']:
        lines.append('')
        lines.append(heading('Worth looking at'))
        for item in result['flags']:
            mark = {'danger': '!!', 'caution': '! ', 'note': '  '}[item['level']]
            lines.append(bullet + mark + ' ' + item['message'])
    if result['components']:
        lines.append('')
        lines.append(heading('Built from'))
        for item in result['components']:
            lines.append(bullet + item['reference'] + (' — ' + item['purpose'] if item['purpose'] else ''))
    if result['claims']:
        lines.append('')
        lines.append(heading('Recognizes by hash'))
        for claim in result['claims']:
            lines.append(bullet + '%s %s (%s…)' % (claim['kind'], claim['name'], claim['sha256'][:12]))
    return '\n'.join(lines)


def component_index(records):
    """Every component a person can build their own recipe from.

    The point of a component catalogue is that you do not have to trust
    anyone's finished recipe: you can assemble one from parts that are already
    reviewed, each saying which problem it solves.
    """
    from . import recipe_engine as engine
    index = []
    users = {}
    for owner, record in records.items():
        if record['data']['kind'] != 'component':
            for dependency in engine.resolve(records, owner):
                users.setdefault(engine.reference(dependency), []).append(
                    {'reference': owner, 'name': record['data']['name']})
    for ref, record in sorted(records.items()):
        if record['data']['kind'] != 'component':
            continue
        ordered = engine.resolve(records, ref)
        index.append({'reference': ref, 'name': record['data']['name'],
                      'purpose': record['data'].get('purpose'),
                      'notes': record['data'].get('notes'),
                      'tier': tier_for(record['source']),
                      'capabilities': sorted(capabilities(ordered, record)),
                      'requires': list(record['data']['requires']),
                      'used_by': sorted(users.get(ref, []), key=lambda item: item['reference']),
                      'report': report(records, ref)})
    return index


def catalogue_badge(result):
    """Describe capabilities, not an unperformed security review.

    Presentation only: verdicts, trust ceilings and application checks stay intact.
    """
    if result['verdict'] == 'refused':
        return 'Blocked by recipe policy', 'danger'
    if result.get('existing_setup'):
        return 'Setup in existing iLok environment', None
    if result.get('documentation_only'):
        return 'Documented setup · not automated', None
    capabilities = set(result.get('capabilities', []))
    if result.get('runs'):
        return 'Runs an installer', None
    if 'require-bridge-patch' in capabilities:
        return 'Requires bridge patches', None
    if 'require-existing-files' in capabilities:
        return 'Requires runtime files', None
    if result.get('downloads') or capabilities & {'prepare-archive-tools', 'install-powershell', 'install-ntk-daemon'}:
        return 'Installs dependencies', None
    return 'Configures settings', None
