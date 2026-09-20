#!/usr/bin/env python3
"""Native negative test: missing managed mapping must never invoke system Wine."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plugg.core import make_bundle

parser = argparse.ArgumentParser()
parser.add_argument('--bridge', type=Path, required=True)
parser.add_argument('--fixture', type=Path, required=True)
args = parser.parse_args()
bridge, fixture = args.bridge.resolve(), args.fixture.resolve()
if not fixture.is_file():
    parser.error('Build the synthetic gain fixture first')
with tempfile.TemporaryDirectory(prefix='plugg-loader-') as temporary:
    root = Path(temporary)
    prefix = root / 'prefix'
    module = prefix / 'drive_c/Program Files/Common Files/VST3/Gain.vst3'
    module.parent.mkdir(parents=True)
    shutil.copy2(fixture, module)
    native = make_bundle(SimpleNamespace(bridge=lambda: bridge), module, root / 'Managed.vst3')
    receipt = root / 'unwanted-wine-call'
    trap = root / 'wine-trap'
    trap.write_text('#!/bin/sh\nprintf called > "$PLUGG_TEST_RECEIPT"\nexit 99\n')
    trap.chmod(0o700)
    env = dict(os.environ, WINELOADER=str(trap), WINESERVER=str(trap),
               PLUGG_TEST_RECEIPT=str(receipt),
               DBUS_SESSION_BUS_ADDRESS='unix:path=/nonexistent')
    marker = prefix / '.plugg-runtime'
    for kind, contents, expected in (
        ('absent', None, 'environment mapping is missing'),
        ('empty', '', 'runtime is missing'),
        ('invalid', str(root / 'missing-launcher') + '\n', 'runtime is missing'),
    ):
        if contents is not None:
            marker.write_text(contents)
        result = subprocess.run([str(bridge / 'plugg-scan'), str(native), str(root / 'result.json')],
                                env=env, text=True, capture_output=True, timeout=15)
        if result.returncode == 0 or expected not in result.stdout + result.stderr:
            raise SystemExit(f'{kind}: did not get expected mapping failure\n{result.stdout}\n{result.stderr}')
        if receipt.exists():
            raise SystemExit(f'{kind}: managed publication called unrelated Wine')
        print(f'{kind}: expected error, no system Wine invocation')
