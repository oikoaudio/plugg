"""Good bug reports, made easy; nothing else made easy.

Plugg has no helpdesk. What it wants is reports someone can act on: what was
done, what happened, what was expected, how often, and the facts about the
setup that nobody should have to dig for. This collects the person's answers,
refuses to go further until the essential ones are there, and fills GitHub's
issue form with them. The person reviews the form, ticks its checks and
submits it themselves. Nothing is sent from here.

The setup summary leaves out what the templates forbid: licence files,
serials, account data and the licensing records' contents. Only whether an
environment is protected, and how strictly, is said. The home folder is
written as ~, so nothing carries a user name.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import json
import os
import platform

ISSUES = 'https://github.com/oikoaudio/plugg/issues/new'
TEMPLATES = {'bug': 'bug.yml', 'compatibility': 'compatibility-report.yml'}
FREQUENCY = ('Every time', 'Sometimes', 'Once so far')
STAGES = ('Installation', 'Authorization', 'Audio', 'Editor opens', 'Editor close and reopen',
          'Multiple instances', 'Project saved and recalled')
#: Per field, so the whole address stays well inside what browsers and GitHub accept.
FIELD_LIMIT = 1800


def private(text):
    """The text with the home folder, and so the user name, written as ~."""
    home = str(Path.home())
    return (text or '').replace(home, '~') if home and home != '/' else (text or '')


def _system():
    lines = []
    try:
        for line in Path('/etc/os-release').read_text().splitlines():
            if line.startswith('PRETTY_NAME='):
                lines.append('System: ' + line.split('=', 1)[1].strip('"'))
    except OSError:
        pass
    lines.append('Kernel: ' + platform.release())
    desktop = os.environ.get('XDG_CURRENT_DESKTOP') or 'unknown'
    session = os.environ.get('XDG_SESSION_TYPE') or 'unknown'
    lines.append('Desktop: %s (%s)' % (desktop, session))
    return lines


def version():
    from . import __version__
    return __version__


def _plugg(store):
    lines = ['Plugg: ' + version()]
    try:
        build = json.loads((store.bridge() / 'build.json').read_text())
        lines.append('Bridge: yabridge ' + str(build.get('revision', 'unknown'))[:12]
                     + (' with ' + ', '.join(Path(p).stem for p in build.get('patches', [])) if build.get('patches') else ''))
    except Exception:
        lines.append('Bridge: not found')
    try:
        settings = json.loads((Path(store.root) / 'settings.json').read_text())
        lines.append('New environments use: ' + settings.get('new_environment_runtime', 'UMU-Proton-10.0-4'))
    except (OSError, ValueError):
        pass
    return lines


def _environments(records, setups, jobs, focus=None):
    lines = []
    env_of = {j['id']: j['env_id'] for j in jobs}
    status = {}
    for setup in setups:
        env = env_of.get(setup['job'])
        if env and setup.get('message'):
            status[env] = setup['message']
    from .environments import summarize
    for record in records:
        if focus and record['id'] != focus:
            continue
        protected = ('protected (' + (record.get('severity') or 'unknown') + ')' if record.get('protected')
                     else 'licensing note unreadable' if record.get('protected') is None else 'not protected')
        lines.append('- %s: %s, %d plug-in%s in the DAW, %s' % (
            summarize(record), record.get('runtime') or 'runtime not recorded', len(record['plugins']),
            '' if len(record['plugins']) == 1 else 's', protected))
        if record['plugins']:
            lines.append('  Plug-ins: ' + ', '.join(record['plugins']))
        if status.get(record['id']):
            lines.append('  Last helper status: ' + status[record['id']])
    return lines


def setup_summary(store, records, setups, jobs, focus=None, daw=''):
    """The facts every report needs, which nobody should have to dig for."""
    failed = [j for j in jobs if j.get('status') in ('failed', 'needs_attention') and not j.get('archived')]
    lines = _plugg(store) + _system()
    if daw:
        lines.append('DAW: ' + daw)
    environments = _environments(records, setups, jobs, focus)
    if environments:
        lines += ['', 'Environment:' if focus else 'Environments:'] + environments
    if failed:
        lines += ['', 'Installations that did not finish:']
        lines += ['- %s: %s' % (j['name'], j.get('message') or j.get('status')) for j in failed[:10]]
    return private('\n'.join(lines))


def fields(kind, answers, summary):
    """The issue form's fields, by their ids in .github/ISSUE_TEMPLATE, filled from the answers."""
    clean = {key: private(value).strip() for key, value in answers.items() if isinstance(value, str)}
    if kind == 'bug':
        filled = {'what': clean.get('what', ''), 'steps': clean.get('steps', ''),
                  'frequency': clean.get('frequency', ''), 'version': version(),
                  'daw': clean.get('daw', ''), 'setup': summary}
    else:
        stages = answers.get('stages') or {}
        observed = '\n'.join('- %s: %s' % (stage, stages.get(stage, '')) for stage in STAGES)
        filled = {'product': clean.get('product', ''), 'observed': observed,
                  'setup': summary + ('\nDAW: ' + clean['daw'] if clean.get('daw') and 'DAW:' not in summary else ''),
                  'reproduction': clean.get('steps', ''), 'tried': clean.get('tried', '')}
    return {key: value[:FIELD_LIMIT] for key, value in filled.items() if value}


def missing(kind, answers):
    """What a report still needs before it is worth sending. Empty when it is ready."""
    needed = ({'what': 'what happened and what you expected', 'steps': 'the steps that make it happen',
               'frequency': 'how often it happens', 'daw': 'your DAW and its version'}
              if kind == 'bug' else
              {'product': 'the product and its exact version', 'steps': 'the smallest way to reproduce it',
               'daw': 'your DAW and its version'})
    gaps = [said for key, said in needed.items() if len((answers.get(key) or '').strip()) < (3 if key in ('frequency', 'daw') else 15)]
    if kind == 'bug' and answers.get('frequency') not in FREQUENCY:
        gaps = [g for g in gaps if g != 'how often it happens'] + ['how often it happens']
    if kind != 'bug' and not any((answers.get('stages') or {}).values()):
        gaps.append('how far it got at each stage')
    return list(dict.fromkeys(gaps))


def issue_url(kind, filled):
    """The GitHub issue form for this kind of report, with the fields filled in.

    GitHub fills a form's fields from query parameters named after their ids.
    The person still reviews it, ticks the checks and submits it there.
    """
    from urllib.parse import urlencode
    return ISSUES + '?' + urlencode({'template': TEMPLATES.get(kind, TEMPLATES['bug']), **filled})
