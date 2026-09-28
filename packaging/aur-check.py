#!/usr/bin/env python3
"""Checks of an installed Arch package, run by packaging/test-aur.py.

Runs as an ordinary user with the system Python. packaging/container-check.py
runs after it for native library loading, the scanner and the GTK window.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BRIDGE = Path('/usr/lib/plugg/bridge')
FORWARDER = Path('/usr/lib/plugg/powershell-forwarder')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


assert os.getuid() != 0, 'run the checks as an ordinary user'
import plugg
from plugg import bridge_bundle, powershell_component
assert Path(plugg.__file__).is_relative_to('/usr/lib'), plugg.__file__

# plugg doctor, from the installed command and a new, empty home.
doctor = json.loads(subprocess.check_output(['/usr/bin/plugg', 'doctor'], text=True))
assert doctor['bridge_directory'] == str(BRIDGE), doctor['bridge_directory']
assert doctor['bridge_error'] is None, doctor['bridge_error']
missing = [name for name, item in doctor['bridge'].items() if not item['present']]
assert not missing, 'bridge files missing: ' + ', '.join(missing)
for name, item in doctor['bridge'].items():
    assert item['sha256'] == digest(BRIDGE / name), name
# Every file matches the build manifest, and the Windows host was built
# without -march flags.
bridge_bundle.inspect(BRIDGE)
built = json.loads((BRIDGE / 'build.json').read_text())

# The PowerShell forwarder, found where the app looks and matching the source
# the app accepts.
assert powershell_component.forwarder_directory() == FORWARDER
forwarder = json.loads((FORWARDER / 'build.json').read_text())
assert forwarder['source_sha256'] == powershell_component.FORWARDER_SOURCE_SHA256
for name in ('powershell32.exe', 'powershell64.exe', 'LICENSE.forwarder', 'LICENSE.Go'):
    assert digest(FORWARDER / name) == forwarder['files'][name], name
for name in ('powershell32.exe', 'powershell64.exe'):
    assert (FORWARDER / name).read_bytes()[:2] == b'MZ', name

assert Path('/usr/share/applications/com.oikoaudio.Plugg.desktop').is_file()
result = dict(passed=True, python=sys.version, installed_module=plugg.__file__, version=doctor['version'],
              bridge_directory=doctor['bridge_directory'], bridge_error=doctor['bridge_error'],
              bridge_revision=built['revision'], forwarder=str(FORWARDER),
              forwarder_compiler=forwarder['compiler'])
(Path.home() / 'aur-result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
