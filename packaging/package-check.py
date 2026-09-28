#!/usr/bin/env python3
"""Check an installed Plugg .deb or .rpm, as an ordinary user, in a test container.

packaging/test-packages.py runs this with the system Python (/usr/bin/python3 -I)
inside a clean distribution container after installing the package. The `cli`
phase needs no display and runs before any test tool is installed, so it sees
only what the package's own dependencies brought in. The `gui` phase runs
under Xvfb once the test tools are there. Each phase writes its result to
~/package-check-<phase>.json and exits non-zero on the first failed check.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

APP = Path('/usr/lib/plugg/app')
BRIDGE = Path('/usr/lib/plugg/bridge')
FORWARDER = Path('/usr/lib/plugg/powershell-forwarder')
DESKTOP = Path('/usr/share/applications/com.oikoaudio.Plugg.desktop')


def check(condition, message):
    if not condition:
        raise SystemExit('FAILED: ' + message)


def run(*command, timeout=120):
    return subprocess.run([str(part) for part in command], capture_output=True, text=True, timeout=timeout)


def installed_package():
    """The package's own modules, never a checkout's."""
    sys.path.insert(0, str(APP))
    import plugg
    check(Path(plugg.__file__).resolve().parent == APP / 'plugg', 'plugg imported from ' + plugg.__file__)
    return plugg


def cli(version):
    result = {'phase': 'cli', 'uid': os.getuid(), 'python': sys.version.split()[0]}
    check(os.getuid() != 0, 'run as an ordinary user')
    # Fedora's /usr/sbin is a link to /usr/bin and comes first on PATH.
    found = shutil.which('plugg')
    check(found and os.path.samefile(found, '/usr/bin/plugg'), 'plugg on PATH is ' + str(found))
    shown = run('plugg', '--help')
    check(shown.returncode == 0 and 'doctor' in shown.stdout, 'plugg --help: ' + shown.stderr)
    doctor = run('plugg', 'doctor')
    check(doctor.returncode == 0, 'plugg doctor: ' + doctor.stderr)
    report = json.loads(doctor.stdout)
    check(report['version'] == version, 'doctor reports version ' + report['version'])
    check(report['bridge_directory'] == str(BRIDGE), 'doctor reports the bridge at ' + report['bridge_directory'])
    check(report['bridge_error'] is None, 'doctor reports a bridge error: ' + str(report['bridge_error']))
    check(all(item['present'] for item in report['bridge'].values()), 'doctor misses bridge files')
    result['doctor'] = {key: report[key] for key in ('version', 'data', 'bridge_directory', 'bridge_error')}
    recipes = run('plugg', 'recipe', 'check')
    check(recipes.returncode == 0 and json.loads(recipes.stdout), 'plugg recipe check: ' + recipes.stderr)
    result['builtin_recipes'] = len(json.loads(recipes.stdout))

    installed_package()
    from plugg import bridge_bundle, core, powershell_component
    check(core.default_bridge_directory() == BRIDGE, 'default bridge is ' + str(core.default_bridge_directory()))
    bridge_bundle.inspect(BRIDGE)
    found = powershell_component.forwarder_directory()
    check(found == FORWARDER, 'forwarder found at ' + str(found))
    built = json.loads((FORWARDER / 'build.json').read_text())
    check(built['source_sha256'] == powershell_component.FORWARDER_SOURCE_SHA256, 'forwarder built from other source')
    for name in ('powershell32.exe', 'powershell64.exe', 'LICENSE.forwarder', 'LICENSE.Go'):
        check(core.digest(FORWARDER / name) == built['files'].get(name), 'forwarder file changed: ' + name)
    result['forwarder'] = {'directory': str(found), 'compiler': built['compiler']}

    ctypes.CDLL(str(BRIDGE / 'libyabridge-vst3.so'))
    ctypes.CDLL(str(BRIDGE / 'libyabridge-chainloader-vst3.so'))
    scanner = run(BRIDGE / 'plugg-scan')
    check(scanner.returncode == 64, 'plugg-scan exited with %d: %s' % (scanner.returncode, scanner.stderr))
    result['bridge'] = {'inspected': True, 'libraries_load': True, 'scanner_starts': True}

    gtk = run(sys.executable, '-I', '-c', 'import gi; gi.require_version("Gtk", "4.0"); '
              'from gi.repository import Gtk; print(Gtk.get_major_version(), Gtk.get_minor_version(), '
              'Gtk.get_micro_version())')
    check(gtk.returncode == 0, 'GTK 4 import: ' + gtk.stderr)
    major, minor, micro = map(int, gtk.stdout.split())
    check((major, minor) >= (4, 10), 'GTK is %d.%d' % (major, minor))
    result['gtk'] = '%d.%d.%d' % (major, minor, micro)

    entry = DESKTOP.read_text()
    check('\nExec=plugg gui\n' in entry, 'desktop entry does not run plugg gui')
    check(not os.access(APP / 'plugg', os.W_OK), 'the app directory is writable by the user')
    compiled = sorted((APP / 'plugg/__pycache__').glob('core.*.pyc'))
    check(compiled, 'postinstall did not compile the app')
    result['compiled'] = compiled[0].name
    result['passed'] = True
    return result


def gui():
    result = {'phase': 'gui'}
    installed_package()
    from plugg import core
    from plugg.gui import Manager
    from gi.repository import GLib
    # A library without --bridge-dir picks the packaged bridge.
    store = core.Store(Path.home() / 'gui-library', Path.home() / 'gui-published')
    check(store.bridge_directory() == BRIDGE, 'new library uses the bridge at ' + str(store.bridge_directory()))
    app = Manager(store)
    windows = []

    def finish():
        windows.extend(app.get_windows())
        app.quit()
        return False
    GLib.timeout_add_seconds(3, finish)
    check(app.run(['plugg']) == 0, 'the GTK application exited with an error')
    check(windows, 'the app created no window')
    result['window_created'] = True

    # The installed launcher itself: its window must appear on the display.
    launched = subprocess.Popen(['plugg', '--data', str(Path.home() / 'launcher-library'),
                                 '--publish-dir', str(Path.home() / 'launcher-published'), 'gui'],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.monotonic() + 30
    seen = False
    while time.monotonic() < deadline and launched.poll() is None and not seen:
        time.sleep(1)
        seen = '"Plugg"' in run('xwininfo', '-root', '-tree').stdout
    exited = launched.poll()
    launched.terminate()
    output = launched.communicate(timeout=30)[0]
    check(exited is None, 'plugg gui exited with %s: %s' % (exited, output))
    check(seen, 'plugg gui showed no window named Plugg')
    result['launcher_window'] = True
    result['passed'] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('phase', choices=('cli', 'gui'))
    parser.add_argument('--version', required=True, help='The version plugg/__init__.py declares')
    args = parser.parse_args()
    result = cli(args.version) if args.phase == 'cli' else gui()
    # Also as a file: xvfb-run mixes GTK's warnings into standard output.
    text = json.dumps(result, indent=2) + '\n'
    (Path.home() / ('package-check-' + args.phase + '.json')).write_text(text)
    print(text, end='', flush=True)


if __name__ == '__main__':
    main()
