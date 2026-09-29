#!/usr/bin/env python3
"""Installed-package checks inside the ordinary packaging test container."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bridge', type=Path, required=True)
args = parser.parse_args()
assert os.getuid() != 0
from plugg import core
assert 'site-packages' in Path(core.__file__).parts
catalogue = json.loads(subprocess.check_output(
    [sys.executable, '-I', '-m', 'plugg', 'recipe', 'check'], text=True))
assert catalogue
for fmt in ('vst3', 'vst2', 'clap'):
    ctypes.CDLL(str(args.bridge / ('libyabridge-' + fmt + '.so')))
    ctypes.CDLL(str(args.bridge / ('libyabridge-chainloader-' + fmt + '.so')))
scanner = subprocess.run([str(args.bridge / 'plugg-scan')], capture_output=True)
assert scanner.returncode == 64, scanner.stderr.decode(errors='replace')

from plugg.gui import Manager
from gi.repository import GLib
app = Manager(core.Store(Path.home() / 'gui-library', Path.home() / 'gui-published',
                         bridge_dir=args.bridge))
windows = []
def finish():
    windows.extend(app.get_windows())
    app.quit()
    return False
GLib.timeout_add_seconds(2, finish)
assert app.run(['plugg']) == 0
assert windows, 'Installed manager did not create a window'
result = dict(passed=True, python=sys.version, installed_module=core.__file__,
              builtin_recipes=len(catalogue), native_libraries_load=True,
              scanner_starts=True, gtk_window_created=True,
              audio_tested=False, vendor_software_used=False)
(Path.home() / 'package-result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
