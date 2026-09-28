#!/usr/bin/env python3
"""Ask each Proton runtime whether the Wine bugs Plugg patches are still there.

Plugg carries Wine patches in its runtimes (plugg/recipes/runtime-overlays.json)
and one of them also in the bridge's guarded runtime. Each exists because a
stock build fails a specific way, and each has an own-code probe in
diagnostics/ that shows that failure without any vendor software. This script
runs every probe in a fresh, disposable prefix on every runtime given, and
reports per patch:

  still needed   the runtime does not carry the patch and the bug is there
  can retire?    the runtime does not carry the patch and the bug is gone:
                 upstream fixed it, so check that release and drop the patch
  works          the runtime carries the patch and the bug is gone
  REGRESSION     the runtime carries the patch and the bug is still there

Runtimes default to every Proton build in the library's runtimes directory.
Never point --library at a library holding activations: the probes create
prefixes of their own, but the rule is that experiments stay out of
licensed libraries altogether.

    for b in diagnostics/*/build.sh; do sh "$b"; done
    python3 scripts/test-runtime-patches.py --library .test-carla/library

Exit status: 0 when every result is expected, 1 on a regression or an
inconclusive probe, 2 when a patch may be retired.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile

ROOT = Path(__file__).resolve().parents[1]
PROBES = ROOT / 'build' / 'diagnostics'
OVERLAYS = ROOT / 'plugg' / 'recipes' / 'runtime-overlays.json'


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def text(prefix, name):
    try:
        return (prefix / 'drive_c' / name).read_bytes().decode('utf-8', 'replace')
    except OSError:
        return ''


def clear(prefix, *names):
    for name in names:
        (prefix / 'drive_c' / name).unlink(missing_ok=True)


# Each probe: the patch it justifies, how to run it, and how to read the result.
# A reader returns True when the bug is there, False when it is gone, and None
# when the probe did not get far enough to say.
def ole32(run, prefix):
    clear(prefix, 'fixture-parent.txt', 'fixture-child.txt')
    run(['dragdrop.exe', '--foreign'])
    parent = text(prefix, 'fixture-parent.txt')
    if 'normal register/revoke cycles passed' not in parent or 'child exit' not in parent:
        return None, parent
    return 'child exit: 0x0\r\n' not in parent, parent


def services(run, prefix):
    said = []
    for exe in ('service-config64.exe', 'service-config32.exe'):
        clear(prefix, 'service-config.txt')
        run([exe])
        said.append(text(prefix, 'service-config.txt'))
    if not all('query level 2: ' in s for s in said):
        return None, '\n'.join(said)
    return any('query level 2: FAILED' in s for s in said), '\n'.join(said)


def rundll32(run, prefix):
    said = []
    for bits, system in (('64', 'system32'), ('32', 'syswow64')):
        clear(prefix, f'rundll32-version{bits}.txt')
        run([f'C:\\windows\\{system}\\rundll32.exe', f'C:\\plugg-probes\\version-probe{bits}.dll,Probe'])
        said.append(text(prefix, f'rundll32-version{bits}.txt'))
    if not all('GetVersionEx=' in s for s in said):
        return None, '\n'.join(said)
    return any('GetVersionEx=6.' in s for s in said), '\n'.join(said)


def unwind(run, prefix):
    clear(prefix, 'unwind-probe.txt')
    run(['unwind-probe.exe'])
    said = text(prefix, 'unwind-probe.txt')
    if 'started' not in said or 'no unwind data' in said:
        return None, said
    return 'survived' not in said, said


PROBE_TABLE = [
    ('ole32 foreign RevokeDragDrop', 'patches/0004-ole32-revoke-foreign-drop-target.patch', ['dragdrop.exe'], ole32),
    ('services failure actions', 'patches/wine/0002-services-Store-and-report-service-failure-actions.patch',
     ['service-config64.exe', 'service-config32.exe'], services),
    ('rundll32 Windows version', 'patches/wine/0001-rundll32-Declare-supported-Windows-versions-in-a-man.patch',
     ['version-probe64.dll', 'version-probe32.dll'], rundll32),
    ('RtlVirtualUnwind2 NULL write', 'patches/wine/0003-ntdll-Do-not-crash-in-RtlVirtualUnwind2-on-NULL-outp.patch',
     ['unwind-probe.exe'], unwind),
]


def patched_modules():
    """Every module file any overlay replaces, by the patch it carries."""
    found = {}
    for overlay in json.loads(OVERLAYS.read_text()).get('overlays', []):
        for module, record in overlay.get('files', {}).items():
            found.setdefault(record['patch'], set()).add((module, record['sha256']))
    return found


def carries(runtime, modules):
    wine = runtime / 'files' / 'lib' / 'wine'
    return any((wine / module).is_file() and sha256(wine / module) == digest for module, digest in modules)


def umu_for(library):
    """The umu launcher and Steam runtime every runtime in a library shares."""
    for base in sorted((library / 'runtimes').glob('proton-*/')):
        if (base / 'umu' / 'umu-run').is_file() and (base / 'runtime').is_dir():
            return base / 'umu' / 'umu-run', base / 'runtime'
    raise SystemExit('No umu launcher in this library; install something into it first.')


def proton_builds(library):
    for proton in sorted((library / 'runtimes').glob('*/proton')) + sorted((library / 'runtimes').glob('*/*/proton')):
        yield proton.parent


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--library', type=Path, default=ROOT / '.test-carla' / 'library')
    ap.add_argument('--runtime', type=Path, action='append', help='A Proton directory; repeatable')
    ap.add_argument('--keep', action='store_true', help='Keep the probe prefixes')
    ap.add_argument('--json', type=Path, help='Also write the results here')
    a = ap.parse_args()
    library = a.library.resolve()
    missing = [n for _, _, names, _ in PROBE_TABLE for n in names if not (PROBES / n).is_file()]
    if missing:
        raise SystemExit('Build the probes first (sh diagnostics/*/build.sh); missing: ' + ', '.join(missing))
    umu, steam_runtime = umu_for(library)
    runtimes = [r.resolve() for r in a.runtime] if a.runtime else list(proton_builds(library))
    modules = patched_modules()
    scratch = Path(tempfile.mkdtemp(prefix='runtime-patches-', dir=ROOT / '.scratch' if (ROOT / '.scratch').is_dir() else None))
    results, status = [], 0
    try:
        for runtime in runtimes:
            name = runtime.parent.name if runtime.name.startswith('UMU-Proton') else runtime.name
            prefix = scratch / name / 'prefix'
            prefix.parent.mkdir(parents=True)
            env = {k: v for k, v in os.environ.items() if k not in (
                'WINELOADER', 'WINESERVER', 'WINEARCH', 'WINEDLLPATH', 'WINEDLLOVERRIDES', 'WAYLAND_DISPLAY', 'LD_PRELOAD')}
            env.update(UMU_FOLDERS_PATH=str(steam_runtime), XDG_CACHE_HOME=str(scratch / 'cache'), WINEPREFIX=str(prefix),
                       PROTONPATH=str(runtime), GAMEID='umu-default', PROTON_VERB='run', UMU_RUNTIME_UPDATE='0',
                       WINEDEBUG='-all', PROTON_LOG='0', PRESSURE_VESSEL_SHARE_PID='1')
            log = open(prefix.parent / 'probes.log', 'ab')

            def run(argv):
                program = argv[0] if argv[0].startswith('C:') else f'C:\\plugg-probes\\{argv[0]}'
                try:
                    subprocess.run([umu, program, *argv[1:]], env=env, stdout=log, stderr=log, timeout=120)
                except subprocess.TimeoutExpired:
                    log.write(f'timeout: {argv}\n'.encode())

            print(f'{name}: creating a disposable prefix', flush=True)
            subprocess.run([umu, 'wineboot', '-u'], env=env, stdout=log, stderr=log, timeout=300)
            (prefix / 'drive_c' / 'plugg-probes').mkdir(parents=True, exist_ok=True)
            for probe in PROBES.iterdir():
                if probe.suffix in ('.exe', '.dll'):
                    shutil.copy2(probe, prefix / 'drive_c' / 'plugg-probes' / probe.name)
            for title, patch, _, read in PROBE_TABLE:
                carried = carries(runtime, modules.get(patch, ()))
                bug, said = read(run, prefix)
                if bug is None:
                    verdict, status = 'INCONCLUSIVE', 1
                elif carried:
                    verdict = 'REGRESSION' if bug else 'works'
                    status = 1 if bug else status
                else:
                    verdict = 'still needed' if bug else 'can retire?'
                    status = status or (0 if bug else 2)
                print(f'  {verdict:13} {title}  ({"patched" if carried else "stock"} module)', flush=True)
                results.append({'runtime': str(runtime), 'probe': title, 'patch': patch, 'patched': carried,
                                'bug_present': bug, 'verdict': verdict, 'output': said.strip()})
            log.close()
    finally:
        if not a.keep:
            subprocess.run(['chmod', '-R', 'u+w', str(scratch)], check=False)
            shutil.rmtree(scratch, ignore_errors=True)
        else:
            print('Prefixes kept in', scratch)
    if a.json:
        a.json.write_text(json.dumps(results, indent=2) + '\n')
    return status


if __name__ == '__main__':
    sys.exit(main())
