#!/usr/bin/env python3
"""Load Plugg's published test plug-ins in a real host and check what a DAW would see.

Carla is the host, driven through its Python API with the dummy audio
engine, on a private headless display. Everything happens in a disposable
library (--library, default .test-carla/library) that holds only Plugg's own
fixtures: nothing here reads or changes a library with vendor software or
activations in it.

The fixtures come from scripts/build-fixture.sh:

  Plugg Test Editor  a gain with an edit controller and a Win32 editor that
                     reports each left click, in its own coordinates, through
                     its parameters
  Plugg Test Crash   the same plug-in, ending the host's main thread in
                     initialize(), as a stack overflow in a plug-in does

The checks:

  load       two instances load side by side, each with its three parameters
  editor     the editor opens, and clicks at known points arrive at those
             points, so it is where the host's frame is and input is not
             offset; repeated over several open/close cycles
  crash      a plug-in that kills its host fails to load within seconds
             instead of hanging the host, and the other instance still answers
  teardown   removing everything and closing the engine returns, and no host
             process is left behind

The display is a headless weston with Xwayland, the way Hyprland and other
Wayland compositors run a DAW's X11 windows. Two monitors side by side,
which is what shifts an editor off its frame when the bridge gets its
position wrong, are not covered yet: weston 15's headless backend creates
only one output, and --outputs 2 refuses to run.

    scripts/build-fixture.sh
    python3 scripts/test-carla.py
    python3 scripts/test-carla.py --json .test-carla/carla.json

Needs Carla (with its Python API in /usr/share/carla), weston and xdotool.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import argparse, json, os, re, shutil, signal, subprocess, sys, tempfile, time

ROOT = Path(__file__).resolve().parents[1]
CARLA_PYTHON = Path('/usr/share/carla')
CARLA_LIBRARY = Path('/usr/lib/carla/libcarla_standalone2.so')
EDITOR, CRASH = 'Plugg Test Editor', 'Plugg Test Crash'
# Where the editor fixture is clicked, in its 400x300 client area.
POINTS = ((40, 30), (200, 150), (360, 270), (13, 287))


# ---------------------------------------------------------------- the host side

def probe(publication, cycles):
    """Runs in its own process, so a host that crashes cannot take the harness with it."""
    sys.path.insert(0, str(CARLA_PYTHON))
    from carla_backend import (BINARY_NATIVE, ENGINE_OPTION_PATH_BINARIES, ENGINE_OPTION_PROCESS_MODE,
                               ENGINE_OPTION_TRANSPORT_MODE, ENGINE_PROCESS_MODE_CONTINUOUS_RACK,
                               ENGINE_TRANSPORT_MODE_INTERNAL, PLUGIN_VST3, CarlaHostDLL)
    results = {}

    def say(name, passed, **details):
        results[name] = {'passed': bool(passed), **details}
        print(json.dumps({name: results[name]}), flush=True)

    host = CarlaHostDLL(str(CARLA_LIBRARY), False)
    host.set_engine_option(ENGINE_OPTION_PROCESS_MODE, ENGINE_PROCESS_MODE_CONTINUOUS_RACK, '')
    host.set_engine_option(ENGINE_OPTION_TRANSPORT_MODE, ENGINE_TRANSPORT_MODE_INTERNAL, '')
    host.set_engine_option(ENGINE_OPTION_PATH_BINARIES, 0, str(CARLA_LIBRARY.parent))
    if not host.engine_init('Dummy', 'plugg-test-carla'):
        say('engine', False, error=host.get_last_error())
        return 1

    def idle(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            host.engine_idle()
            time.sleep(0.02)

    def add(name):
        started = time.monotonic()
        ok = host.add_plugin(BINARY_NATIVE, PLUGIN_VST3, str(publication / f'{name}.vst3'), '', '', 0, None, 0)
        return ok, round(time.monotonic() - started, 2), '' if ok else host.get_last_error()

    def reported(plugin):
        values = [host.get_current_parameter_value(plugin, i) for i in range(3)]
        return round(values[0] * 4096), round(values[1] * 4096), round(values[2] * 1000)

    # load
    loads = [add(EDITOR), add(EDITOR)]
    counts = [host.get_parameter_count(i) for i in range(host.get_current_plugin_count())]
    say('load', all(ok for ok, _, _ in loads) and counts == [3, 3],
        seconds=[s for _, s, _ in loads], parameters=counts, errors=[e for _, _, e in loads if e])
    if not all(ok for ok, _, _ in loads):
        host.engine_close()
        return 1
    idle(0.5)

    # editor
    clicks, geometry, expected_count = [], [], 0
    for cycle in range(cycles):
        host.show_custom_ui(0, True)
        window = None
        for _ in range(100):
            idle(0.1)
            found = run(['xdotool', 'search', '--onlyvisible', '--name', EDITOR]).stdout.split()
            if found:
                window = found[-1]
                break
        if window is None:
            say('editor', False, cycle=cycle, error='no editor window appeared', clicks=clicks)
            break
        idle(1)
        geometry.append(run(['xdotool', 'getwindowgeometry', window]).stdout.strip().replace('\n', '; '))
        for x, y in POINTS:
            run(['xdotool', 'mousemove', '--window', window, str(x), str(y), 'click', '1'])
            expected_count += 1
            got = None
            for _ in range(50):
                idle(0.05)
                got = reported(0)
                if got[2] == expected_count:
                    break
            clicks.append({'cycle': cycle, 'at': [x, y], 'reported': list(got[:2]),
                           'arrived': got[2] == expected_count})
            if got[2] != expected_count:
                expected_count = got[2]
        host.show_custom_ui(0, False)
        idle(0.5)
    else:
        missed = [c for c in clicks if not c['arrived']]
        offset = [c for c in clicks if c['arrived'] and (abs(c['reported'][0] - c['at'][0]) > 1
                                                          or abs(c['reported'][1] - c['at'][1]) > 1)]
        say('editor', not missed and not offset, cycles=cycles, clicks=len(clicks),
            missed=missed, offset=offset, windows=geometry[:1])

    # crash
    before = host.get_current_plugin_count()
    ok, seconds, error = add(CRASH)
    survivor = host.get_parameter_count(0) if host.get_current_plugin_count() else None
    say('crash', not ok and seconds < 30 and survivor == 3 and host.get_current_plugin_count() == before,
        loaded=ok, seconds=seconds, error=error, other_instance_parameters=survivor)

    # teardown
    started = time.monotonic()
    removed = host.remove_all_plugins()
    closed = host.engine_close()
    say('teardown', removed and closed, seconds=round(time.monotonic() - started, 2))
    return 0 if all(r['passed'] for r in results.values()) else 1


# ---------------------------------------------------------------- the harness side

def run(argv, **kwargs):
    kwargs.setdefault('timeout', 30)
    return subprocess.run(argv, capture_output=True, text=True, check=False, **kwargs)


def plugg(library, publication, *args):
    return run([str(ROOT / 'bin' / 'plugg'), '--data', str(library), '--publish-dir', str(publication), *args],
               timeout=600)


def prepare(library, publication):
    """Build and install the fixtures unless they are already published here."""
    wanted = {EDITOR, CRASH}
    if not all((ROOT / 'build' / 'fixtures' / f'{name}.vst3').is_file() for name in wanted):
        subprocess.run([str(ROOT / 'scripts' / 'build-fixture.sh')], check=True)
    for name in sorted(wanted):
        if not (publication / f'{name}.vst3').exists():
            print(f'Installing {name} into {library}', flush=True)
            said = plugg(library, publication, 'install', str(ROOT / 'build' / 'fixtures' / f'{name}.vst3'))
            if not (publication / f'{name}.vst3').exists():
                raise SystemExit(f'Could not install {name}:\n{said.stdout}{said.stderr}')


class Display:
    """A headless weston with Xwayland, held open for the whole run."""

    def __init__(self, scratch, outputs, width, height):
        self.log = scratch / 'weston.log'
        env = {k: v for k, v in os.environ.items() if k not in ('DISPLAY', 'WAYLAND_DISPLAY')}
        env.setdefault('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
        argv = ['weston', '--backend=headless', f'--width={width}', f'--height={height}', '--xwayland',
                f'--socket=plugg-test-{os.getpid()}', f'--log={self.log}']
        if outputs > 1:
            # weston 15's headless backend has no option for more outputs.
            # Finding another way to lay out two monitors is still open.
            raise SystemExit('--outputs 2 is not implemented yet: weston 15 headless creates one output')
        self.compositor = subprocess.Popen(argv, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           start_new_session=True)
        self.name = self.announced()
        # Xwayland is started on demand and leaves with its last client, so
        # one client stays connected until the run ends.
        self.anchor = subprocess.Popen(['xprop', '-display', self.name, '-root', '-spy', '_NET_ACTIVE_WINDOW'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def announced(self):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.compositor.poll() is not None:
                break
            found = re.search(r'xserver listening on display (:\d+)', self.log.read_text(errors='replace')
                              if self.log.exists() else '')
            if found:
                return found.group(1)
            time.sleep(0.2)
        said = self.log.read_text(errors='replace')[-2000:] if self.log.exists() else '(no log)'
        raise SystemExit('weston did not announce an X display:\n' + said)

    def close(self):
        for process in (self.anchor, self.compositor):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM) if process is self.compositor else process.terminate()
                    process.wait(timeout=10)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    process.kill()


class Existing:
    """An X display someone else runs. It needs a window manager: Carla's
    JUCE window code sets properties with atoms only a window manager
    creates, and on a bare X server it dies of BadAtom or waits forever."""

    def __init__(self, name):
        self.name = name

    def close(self):
        pass


def leftover_hosts(library):
    """Bridge host processes still running a fixture of this library."""
    marker = str(library / 'environments').encode()
    found = []
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():
            continue
        try:
            cmdline = (p / 'cmdline').read_bytes()
        except OSError:
            continue
        if b'yabridge-host' in cmdline.split(b'\0', 1)[0] and marker in cmdline:
            found.append(int(p.name))
    return found


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'probe':
        return probe(Path(sys.argv[2]), int(sys.argv[3]))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--library', type=Path, default=ROOT / '.test-carla' / 'library')
    ap.add_argument('--publish-dir', type=Path, help='default: published/ beside the library')
    ap.add_argument('--outputs', type=int, choices=(1, 2), default=1, help='monitors side by side')
    ap.add_argument('--cycles', type=int, default=3, help='editor open/close cycles')
    ap.add_argument('--json', type=Path, help='also write the results here')
    ap.add_argument('--x-display', help='use this running X display, which must have a window manager, instead of a private weston')
    a = ap.parse_args()
    library = a.library.resolve()
    publication = (a.publish_dir or library.parent / 'published').resolve()
    for tool in ('xdotool', 'xprop') + (() if a.x_display else ('weston',)):
        if not shutil.which(tool):
            raise SystemExit(f'{tool} is needed for this test')
    if not (CARLA_PYTHON / 'carla_backend.py').is_file() or not CARLA_LIBRARY.is_file():
        raise SystemExit('Carla with its Python API is needed for this test')
    prepare(library, publication)
    scratch = Path(tempfile.mkdtemp(prefix='plugg-carla-'))
    display = Existing(a.x_display) if a.x_display else Display(scratch, a.outputs, 1920, 1080)
    results, status = {}, 1
    try:
        env = dict(os.environ, DISPLAY=display.name)
        env.pop('WAYLAND_DISPLAY', None)
        print(f'Carla on {display.name} ({a.outputs} output{"s" if a.outputs > 1 else ""})', flush=True)
        try:
            child = subprocess.run([sys.executable, __file__, 'probe', str(publication), str(a.cycles)], env=env,
                                   capture_output=True, text=True, timeout=300 + 60 * a.cycles)
            output, code = child.stdout, child.returncode
            (scratch / 'carla.log').write_text(child.stderr)
        except subprocess.TimeoutExpired as expired:
            said = expired.stdout or ''
            output, code = said.decode(errors='replace') if isinstance(said, bytes) else said, None
        for line in output.splitlines():
            if line.startswith('{'):
                results.update(json.loads(line))
        if code is None:
            results['host'] = {'passed': False, 'error': 'Carla did not finish: something is waiting forever'}
        elif code < 0:
            results['host'] = {'passed': False, 'error': f'Carla died with signal {-code}'}
        for check in ('load', 'editor', 'crash', 'teardown'):
            if check not in results:
                results[check] = {'passed': False, 'error': f'did not run; Carla exited with {code} (see carla.log)'}
        deadline = time.monotonic() + 15
        while (left := leftover_hosts(library)) and time.monotonic() < deadline:
            time.sleep(0.5)
        results['no leftover hosts'] = {'passed': not left, 'pids': left}
        for name, result in results.items():
            details = {k: v for k, v in result.items() if k != 'passed' and v not in ([], None, '')}
            print(f'  {"pass" if result["passed"] else "FAIL"}  {name}  {json.dumps(details) if details else ""}')
        status = 0 if all(r['passed'] for r in results.values()) else 1
        if a.json:
            a.json.write_text(json.dumps({'display': display.name, 'outputs': a.outputs, 'results': results},
                                         indent=2) + '\n')
        if status:
            print('Logs kept in', scratch)
    finally:
        display.close()
        if not status:
            shutil.rmtree(scratch, ignore_errors=True)
    return status


if __name__ == '__main__':
    sys.exit(main())
