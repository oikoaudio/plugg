#!/usr/bin/env python3
"""Review recipe files the way a maintainer would, without a maintainer.

Recipes are data, so what one can do is computable. This prints the same
bird's-eye view a user sees before applying a recipe, and fails when a recipe
declares more than its directory allows. The point is that review effort scales
with the number of *flagged* recipes, not with the number submitted.

    python3 scripts/review-recipe.py recipes/community/local.example.toml
    python3 scripts/review-recipe.py --changed origin/main

SPDX-License-Identifier: GPL-3.0-or-later
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plugg import recipe_engine as engine, recipe_report  # noqa: E402


#: A shared recipe must sit directly in one of these, so that the directory a
#: reviewer sees in the diff is the directory that decides its ceiling.
TIER_DIRECTORIES = ('recipes/community', 'recipes/reviewed')


def changed_recipes(base):
    """Recipe files a branch adds or changes, relative to the repository root."""
    diff = subprocess.run(['git', 'diff', '--name-only', '--diff-filter=d', base + '...HEAD'],
                          cwd=ROOT, capture_output=True, text=True, check=True)
    return [ROOT / name for name in diff.stdout.split() if name.startswith('recipes/')]


def misplaced(path):
    """Anything under recipes/ that is not a direct child of a tier directory."""
    try:
        relative = path.relative_to(ROOT).as_posix()
    except ValueError:
        return None
    if not relative.startswith('recipes/'):
        return None
    if not relative.endswith('.toml'):
        return 'Only .toml recipes belong under recipes/.'
    if relative.rsplit('/', 1)[0] not in TIER_DIRECTORIES:
        return ('A shared recipe must be a direct child of ' + ' or '.join(TIER_DIRECTORIES) +
                '. A nested directory would let the file claim a tier that the path a '
                'reviewer reads does not match.')
    return None


def review(paths):
    """Load each recipe beside the shipped catalogue and describe it."""
    shipped = engine.catalogue([Path(engine.__file__).parent / 'recipes/community'])
    reviewed = ROOT / 'recipes/reviewed'
    community = ROOT / 'recipes/community'
    published, _ = engine._catalogue([reviewed, community], tolerant=True)
    results = []
    for path in paths:
        entry = {'path': str(path.relative_to(ROOT) if ROOT in path.parents else path)}
        wrong = misplaced(path)
        if wrong:
            entry['error'] = wrong
            results.append(entry)
            continue
        try:
            record = engine.load(path)
            reference = engine.reference(record)
            records = {**shipped, **published, reference: record}
            entry['report'] = recipe_report.report(records, reference, source=path)
        except (OSError, ValueError, RuntimeError) as exc:
            entry['error'] = str(exc)
        results.append(entry)
    return results


def render(results, markdown):
    lines = []
    for entry in results:
        if 'error' in entry:
            lines.append(('### ' if markdown else '') + entry['path'])
            lines.append('This recipe could not be read, so it cannot be accepted:')
            lines.append(('    ' if not markdown else '\n    ') + entry['error'])
            lines.append('')
            continue
        lines.append(recipe_report.render(entry['report'], markdown=markdown))
        lines.append('')
    if not results:
        lines.append('No recipe files changed.')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='*', type=Path)
    parser.add_argument('--changed', metavar='BASE', help='Review recipes changed since BASE')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--markdown', action='store_true')
    parser.add_argument('--summary', type=Path, help='Also append the report to this file')
    args = parser.parse_args()
    paths = list(args.paths)
    if args.changed:
        paths += changed_recipes(args.changed)
    results = review([Path(path).resolve() for path in paths])
    text = json.dumps(results, indent=2) if args.json else render(results, args.markdown)
    print(text)
    summary = args.summary or (Path(os.environ['GITHUB_STEP_SUMMARY'])
                               if os.environ.get('GITHUB_STEP_SUMMARY') else None)
    if summary is not None and not args.json:
        with summary.open('a') as stream:
            stream.write('## Recipe review\n\n' + render(results, markdown=True) + '\n')
    refused = [entry for entry in results
               if 'error' in entry or entry['report']['verdict'] == 'refused']
    needs_review = [entry for entry in results
                    if 'report' in entry and entry['report']['verdict'] == 'needs-review']
    if refused:
        print('\nRefused: %d recipe(s) declare more than their directory allows, are in the wrong '
              'place, or could not be read.' % len(refused), file=sys.stderr)
        return 1
    if needs_review:
        # A recipe that runs a vendor installer with arguments it chooses should
        # not present as a green check. Passing it is a person's decision.
        print('\n%d recipe(s) need a maintainer to look at the flagged items above. Approving '
              'them is a human decision, so this check does not pass on its own.' % len(needs_review),
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
