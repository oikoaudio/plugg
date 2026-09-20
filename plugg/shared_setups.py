"""Explicit code-owned adapters for existing licensed environments.

Recipes name an adapter, never a command, Python module, registry edit or URL.
Fresh provisioning remains a separate operation. New adapters need code review.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
from . import recipe_engine as engine, recipe_report

ROOT_FIELDS = {'schema', 'id', 'revision', 'kind', 'name', 'vendor', 'requires',
               'notes', 'documentation_only', 'existing_setup'}
SOFTUBE_COMPONENTS = {'plugg.pace-license-support@1',
                      'plugg.graphics-dxvk@1',
                      'plugg.softube-helper-compatibility@1',
                      'plugg.powershell@1'}
#: Revision 2 adds the Visual C++ runtime Softube's product installers need.
SOFTUBE_COMPONENTS_2 = {'plugg.pace-license-support@1',
                        'plugg.graphics-dxvk@1',
                        'plugg.softube-helper-compatibility@2',
                        'plugg.powershell@1',
                        'plugg.vc2022-x64@1'}

UA_COMPONENTS = {'plugg.pace-license-support@1', 'plugg.windows-archive-tools@2',
                 'plugg.ua-helper-compatibility@1', 'plugg.ole32-foreign-window-guard@1'}


def validate(records, reference):
    ordered = engine.resolve(records, reference)
    root = records[reference]
    adapter = root['data'].get('existing_setup')
    if adapter not in ('softube', 'ua-connect'):
        raise ValueError('This recipe has no existing-environment setup adapter.')
    if set(root['data']) - ROOT_FIELDS:
        raise ValueError('Existing-environment setup cannot silently ignore other recipe operations.')
    report = recipe_report.report(records, reference)
    if report['exceeds_tier']:
        raise ValueError('This recipe tier cannot set up shared licensing environments.')
    dependencies = {engine.reference(item): item for item in ordered[:-1]}
    expected = (UA_COMPONENTS,) if adapter != 'softube' else (SOFTUBE_COMPONENTS, SOFTUBE_COMPONENTS_2)
    if set(dependencies) not in expected:
        raise ValueError('Existing setup requires its reviewed component graph.')
    shipped = engine.catalogue([Path(__file__).parent / 'recipes/community'])
    for ref, item in dependencies.items():
        if item['sha256'] != shipped[ref]['sha256']:
            raise ValueError('Shared setup component differs from its reviewed implementation: ' + ref)
    return {'reference': reference, 'sha256': root['sha256'], 'adapter': adapter,
            'components': [{'reference': ref, 'sha256': item['sha256']} for ref, item in sorted(dependencies.items())],
            'vc_assets': [item['data']['vc_runtime'] for item in ordered[:-1] if 'vc_runtime' in item['data']]}


def execute(records, reference, installer, environment, *, allow_electron_no_sandbox=False):
    provenance = validate(records, reference)
    if provenance['adapter'] == 'ua-connect':
        from . import ua_setup
        return {**ua_setup.join(installer, environment, allow_electron_no_sandbox=allow_electron_no_sandbox), 'recipe': provenance}
    from . import softube_setup
    return {**softube_setup.join(installer, environment, vc_assets=provenance['vc_assets']), 'recipe': provenance}
