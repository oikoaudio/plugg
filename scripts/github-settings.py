#!/usr/bin/env python3
"""Keep the GitHub repository's settings and rulesets as .github/repository.json says.

    python3 scripts/github-settings.py           report every difference, change nothing
    python3 scripts/github-settings.py --apply   make GitHub match the file

Exits 1 when GitHub differs from the file (after --apply, when it still
does), so it can also run as a check. Only the settings and ruleset fields
the file names are compared; GitHub's own defaults for the rest are left
alone. Rulesets are matched by name. A ruleset on GitHub that the file does
not name is reported and left in place, not deleted.

Rulesets need a public repository (or a paid plan). While the repository is
private, the script says so and checks only the repository settings.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
DESIRED = REPO / '.github/repository.json'


def gh_api(path, method='GET', body=None):
    command = ['gh', 'api', '--method', method, path]
    if body is not None:
        command += ['--input', '-']
    result = subprocess.run(command, input=json.dumps(body) if body is not None else None,
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError((result.stdout or result.stderr).strip())
    return json.loads(result.stdout) if result.stdout.strip() else None


def repository_name():
    url = subprocess.check_output(['git', '-C', str(REPO), 'remote', 'get-url', 'origin'], text=True).strip()
    return url.split('github.com')[-1].lstrip(':/').removesuffix('.git')


def differences(want, have, path=''):
    """Where `have` does not contain `want`: dictionaries by key, lists as wholes (rules by type)."""
    if isinstance(want, dict) and isinstance(have, dict):
        found = []
        for key, value in want.items():
            found += differences(value, have.get(key), path + '.' + key if path else key)
        return found
    if isinstance(want, list) and all(isinstance(v, dict) and 'type' in v for v in want):
        have = {v.get('type'): v for v in have or [] if isinstance(v, dict)}
        found = []
        for rule in want:
            found += differences(rule, have.get(rule['type']), f'{path}[{rule["type"]}]')
        extra = sorted(set(have) - {r['type'] for r in want})
        return found + [f'{path}: GitHub also has {", ".join(extra)}'] if extra else found
    if isinstance(want, list) and isinstance(have, list) and all(isinstance(v, dict) for v in want):
        # Such as required status checks: the same entries in any order,
        # each compared on the fields the file names.
        fields = sorted({k for v in want for k in v})
        key = lambda v: json.dumps({k: v.get(k) for k in fields}, sort_keys=True)  # noqa: E731
        return [] if sorted(map(key, want)) == sorted(map(key, have)) else [f'{path}: {have} should be {want}']
    if isinstance(want, list) and isinstance(have, list):
        return [] if sorted(want) == sorted(have) else [f'{path}: {have} should be {want}']
    return [] if want == have else [f'{path}: {have!r} should be {want!r}']


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--apply', action='store_true', help='change GitHub to match the file')
    args = parser.parse_args()
    desired = json.loads(DESIRED.read_text())
    name = repository_name()
    drift = False

    settings = dict(desired['repository'])
    topics = settings.pop('topics', None)
    current = gh_api(f'repos/{name}')
    found = differences(settings, current)
    if topics is not None:
        found += differences({'topics': topics}, {'topics': current.get('topics', [])})
    for line in found:
        print('repository', line)
    if found and args.apply:
        gh_api(f'repos/{name}', 'PATCH', settings)
        if topics is not None:
            gh_api(f'repos/{name}/topics', 'PUT', {'names': topics})
        print('repository settings updated')
    drift |= bool(found) and not args.apply

    try:
        listed = gh_api(f'repos/{name}/rulesets')
    except RuntimeError as error:
        if current.get('private') and 'Upgrade' in str(error):
            print('rulesets: not available while the repository is private; run this again once it is public')
            return 1 if drift else 0
        raise
    by_name = {r['name']: r['id'] for r in listed}
    for ruleset in desired['rulesets']:
        rid = by_name.get(ruleset['name'])
        have = gh_api(f'repos/{name}/rulesets/{rid}') if rid else None
        found = ['missing'] if have is None else differences(ruleset, have)
        for line in found:
            print(f'ruleset "{ruleset["name"]}"', line)
        if found and args.apply:
            if rid:
                gh_api(f'repos/{name}/rulesets/{rid}', 'PUT', ruleset)
            else:
                gh_api(f'repos/{name}/rulesets', 'POST', ruleset)
            print(f'ruleset "{ruleset["name"]}" {"updated" if rid else "created"}')
        drift |= bool(found) and not args.apply
    for other in sorted(set(by_name) - {r['name'] for r in desired['rulesets']}):
        print(f'ruleset "{other}" is on GitHub but not in {DESIRED.relative_to(REPO)}; left in place')
        drift = True

    if args.apply:
        # Read back: what GitHub stored is the only proof it took.
        sys.stdout.flush()
        return subprocess.run([sys.executable, __file__]).returncode
    if not drift:
        print('GitHub matches', DESIRED.relative_to(REPO))
    return 1 if drift else 0


if __name__ == '__main__':
    sys.exit(main())
