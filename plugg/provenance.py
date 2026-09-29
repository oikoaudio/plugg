"""Read-only source and setup attribution for library details."""
import json
from pathlib import Path

from .formats import FORMATS


def installation_source(plugin, jobs, setups):
    """Resolve current management separately from exact file provenance."""
    candidates = [job for job in jobs if job['env_id'] == plugin['env_id']]
    exact = [job for job in candidates if job['kind'] in FORMATS and job['hash'] == plugin['hash']]
    if len(exact) == 1:
        return 'Installed from: ' + Path(exact[0]['installer']).name, exact[0]
    by_id = {job['id']: job for job in candidates}
    for setup in setups:
        if setup['job'] in by_id:
            if setup['recipe'] == 'pace-service-experiment':
                try:
                    metadata = json.loads(plugin.get('metadata', '{}'))
                    if not isinstance(metadata, dict):
                        metadata = {}
                except (ValueError, TypeError):
                    metadata = {}
                vendor = str(metadata.get('vendor', '')).strip().casefold()
                if not vendor:
                    vendor = next((str(c.get('vendor', '')).strip().casefold() for c in metadata.get('classes', []) if c.get('vendor')), '')
                owner = by_id[setup['job']] if vendor in ('universal audio', 'universal audio, inc.', 'universal audio (uadx)') else None
                return 'Licensing: shared iLok environment', owner
            helper = {'klevgrand': 'Klevgrand Helper',
                      'native-instruments-experiment': 'Native Access'}.get(setup['recipe'], setup['name'])
            return 'Managed by: ' + helper, by_id[setup['job']]
    exact = [job for job in candidates if job['kind'] in FORMATS and job['hash'] == plugin['hash']]
    installers = [job for job in candidates if job['kind'] not in FORMATS]
    matches = exact or (installers if len(installers) == 1 else [])
    if matches:
        job = matches[0]
        prefix = 'Installed from: ' if exact else 'Installer for this environment: '
        return prefix + Path(job['installer']).name, job
    return 'Installation source not recorded', None



def import_recipe_summary(root, job):
    """Show recorded import intent only for its matching input, never live recipes."""
    if job.get('kind') not in FORMATS:
        return []
    path = Path(root) / 'jobs' / job['id'] / 'recipe-lock.json'
    try:
        with path.open('rb') as stream:
            raw = stream.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            return ['Setup record is too large to display.']
        record = json.loads(raw)
        if not isinstance(record, dict):
            return ['Setup record could not be read.']
        if record.get('operation') != 'import_vst3' or record.get('input_sha256') != job['hash']:
            return ['Setup record does not match this import.']
        selected = next(r['resolved'] for r in record['recipes'] if r['reference'] == record['recipe'])
        dependency = next(r['resolved'] for r in record['recipes'] if r['reference'] == record['dependency']['reference'])
        return [f"Setup recipe: {selected['name']} (revision {selected['revision']})",
                f"Required component: {dependency['name']}"]
    except FileNotFoundError:
        return []
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return ['Setup record could not be read.']


def setup_recipe_summary(root, job):
    if job.get('kind') in FORMATS:
        return import_recipe_summary(root, job)
    path = Path(root) / 'jobs' / job['id'] / 'helper-recipe.json'
    try:
        with path.open('rb') as stream:
            raw = stream.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            return ['Setup record is too large to display.']
        record = json.loads(raw)
        if record['helper']['installer_sha256'] != job['hash']:
            return ['Setup record does not match this installer.']
        selected = next(item['resolved'] for item in record['recipes'] if item['reference'] == record['reference'])
        return [f"Setup recipe: {selected['name']} (revision {selected['revision']})"]
    except FileNotFoundError:
        return []
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return ['Setup record could not be read.']


def installation_progress(root, job):
    """Describe the last saved stage, without treating it as live process state."""
    filename = 'import-state.json' if job.get('kind') in FORMATS else 'helper-setup.json'
    path = Path(root) / 'jobs' / job['id'] / filename
    stages = {
        'preparing-runtime': 'Preparing Windows support',
        'preparing-environment': 'Preparing the installation environment',
        'preparing-vc-runtime': 'Installing Microsoft runtime components',
        'installing-helper': 'Running the vendor installer',
        'preparing-components': 'Preparing supporting components',
        'installing-files': 'Installing plug-in files',
        'scanning': 'Checking plug-ins for your DAW',
        'complete': 'Setup completed',
    }
    try:
        with path.open('rb') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError('Oversized stage record')
        record = json.loads(raw)
        if not isinstance(record, dict) or not isinstance(record.get('stage'), str):
            raise ValueError('Invalid stage record')
        stage = record['stage']
        result = ['Last recorded step: ' + stages.get(stage, 'Unrecognized setup step')]
        if stage != 'complete' and job.get('status') in ('failed', 'cancelled', 'needs_attention'):
            result.append('Setup stopped before completion. Keep this environment and its files while investigating; it may already contain installation or activation data.')
        return result
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        return ['The saved setup progress could not be read. Installation files have been preserved.']


def licensing_summary(root, env_id):
    """State plainly whether this environment holds activations worth protecting.

    Read-only. Says what would be lost and whether the environment still looks
    like the machine those activations were issued to. It never names a serial
    number or credential, because none are recorded.
    """
    from . import core, licensing
    environment = Path(root) / 'environments' / str(env_id)
    try:
        state = licensing.status(environment)
    except (OSError, ValueError, core.HostError):
        return ['The licensing record for this environment could not be read. '
                'Treat it as holding activations until you have checked.']
    if not state['protected']:
        return []
    products = ', '.join(item['name'] for item in state['products']) or 'recorded products'
    lines = ['Holds activations for: ' + products + '.']
    if state['severity'] in ('limited-activations', 'unknown'):
        lines.append('At least one of these cannot be recovered by deactivating. '
                     'Do not recreate, move or re-run setup in this environment.')
    elif state['severity'] == 'deactivate-first':
        lines.append('Deactivate these products in their own manager before recreating '
                     'or moving this environment.')
    if state.get('machine_identity_is_this_computer') is False:
        lines.append('This environment reports a machine identity of its own rather than this '
                     'computer\'s, so a vendor counting machines may treat it as a separate one.')
    if state['matches_recorded_identity'] is False:
        changed = ', '.join(item['value'] for item in state['drift']) or 'unreadable identity'
        lines.append('Warning: this environment no longer matches the identity recorded when '
                     'its licences were activated (' + changed + ').')
    return lines
