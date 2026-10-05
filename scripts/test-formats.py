#!/usr/bin/env python3
"""Install the test gain as VST3, VST2 and CLAP, publish all three, and play audio through each.

Then import the VST2 .dll and the CLAP .clap directly, as a drop on the
window does, into a second library that publishes VST3 only: a plug-in
someone drops is published in its own format whatever the setting says.
With a bridge that has the 32-bit host, the 32-bit build of the VST2 gain is
imported and played the same way.

Runs in a new library under .test-formats/, with its own publication folders,
never the user's library or DAW folders. It needs a bridge built with VST2 and
CLAP (scripts/build-bridge.sh) and the fixtures (scripts/build-fixture.sh).
Pass --runtime-from with a development library that already has the Proton
runtime to copy it instead of downloading it.

The audio check loads each published plug-in through the path a DAW would
use, so the chainloader, the bridge, the Wine host and the Windows module all
take part, and requires 1000 blocks of exactly halved output.

SPDX-License-Identifier: GPL-3.0-or-later
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from plugg import bridge_bundle, core, formats  # noqa: E402


def audio(store, run, plugin, kind):
    """Play 1000 blocks through a published plug-in, loaded the way a DAW loads it."""
    link = Path(plugin['publication'])
    output = run / (kind + '-audio.json')
    flag = [] if kind == 'vst3' else ['--' + kind]
    env = os.environ.copy()
    env.pop('WINEPREFIX', None)
    result = subprocess.run([store.bridge() / 'plugg-scan', *flag, formats.loader(link, kind), output, '--audio'],
                            env=env, capture_output=True, text=True, timeout=120)
    if result.returncode or not json.loads(output.read_text()).get('audio_fixture_passed'):
        (run / (kind + '-audio.log')).write_text(result.stdout + result.stderr)
        raise SystemExit(formats.LABELS[kind] + ' audio check failed (exit %d); see %s'
                         % (result.returncode, run / (kind + '-audio.log')))
    print(formats.LABELS[kind], 'published at', link, 'and processed audio', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--bridge', type=Path, required=True, help='A bridge build with VST2 and CLAP')
    parser.add_argument('--runtime-from', type=Path, help='A development library whose runtimes/ to copy')
    args = parser.parse_args()
    fixture = ROOT / 'build/fixtures/Install-Test-Formats.exe'
    if not fixture.is_file():
        parser.error('Build the fixtures first: scripts/build-fixture.sh')
    run = ROOT / '.test-formats' / uuid.uuid4().hex
    library = run / 'library'
    if args.runtime_from:
        shutil.copytree(args.runtime_from.resolve() / 'runtimes', library / 'runtimes', symlinks=True)
    store = core.Store(library, run / 'home/.vst3/plugg', args.bridge.resolve())
    formats.apply(store, set(formats.FORMATS))
    print('Library', library, flush=True)
    job = store.ingest(fixture)
    core.work(store, job)
    status = store.job(job)
    if status['status'] != 'ready':
        raise SystemExit('Installation did not finish: ' + status['message'])
    published = {formats.of(p['metadata']): p for p in store.plugins() if p['status'] == 'ready'}
    if set(published) != set(formats.FORMATS):
        raise SystemExit('Expected one publication per format, found ' + ', '.join(sorted(published)))
    vst2 = json.loads(published['vst2']['metadata'])['classes'][0]
    if vst2.get('code') != 'PgG2':
        raise SystemExit('The VST2 unique ID did not survive: ' + json.dumps(vst2))
    for kind in formats.FORMATS:
        audio(store, run, published[kind], kind)
    dropped = core.Store(run / 'dropped', run / 'dropped-home/.vst3/plugg', args.bridge.resolve())
    if args.runtime_from:
        shutil.copytree(args.runtime_from.resolve() / 'runtimes', dropped.root / 'runtimes', symlinks=True)
    drops = [(dropped, 'Plugg Test Gain 2.dll', 'vst2'), (dropped, 'Plugg Test Gain.clap', 'clap')]
    if bridge_bundle.has_bitbridge(args.bridge):
        # A library of its own: it has the same VST2 unique ID as the 64-bit gain.
        old = core.Store(run / 'dropped-32', run / 'dropped-32-home/.vst3/plugg', args.bridge.resolve())
        if args.runtime_from:
            shutil.copytree(args.runtime_from.resolve() / 'runtimes', old.root / 'runtimes', symlinks=True)
        drops.append((old, 'Plugg Test Gain 2 (32-bit).dll', 'vst2'))
    for library, name, kind in drops:
        job = library.ingest(ROOT / 'build/fixtures' / name)
        core.work(library, job)
        if library.job(job)['status'] != 'ready':
            raise SystemExit('Direct import of ' + name + ' failed: ' + library.job(job)['message'])
        plugin = next(p for p in library.plugins() if p['env_id'] == library.job(job)['env_id'])
        audio(library, run, plugin, kind)
    print('OK')


if __name__ == '__main__':
    main()
