#!/usr/bin/env python3
"""Experimental full Proton probe, kept separate from the usable manager backend.

Downloads only public runtimes and runs our self-authored fixture. Results are
retained under .test-proton; no vendor accounts or user plug-in locations used.
SPDX-License-Identifier: GPL-3.0-or-later
"""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import shlex
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from plugg import core

ASSETS = (
    ('https://github.com/Open-Wine-Components/umu-proton/releases/download/UMU-Proton-10.0-4/UMU-Proton-10.0-4.tar.gz',
     '62e99e029a18fa313e6fa63d42390918101730a940e3491c54d9d58cab887c69', 'UMU-Proton-10.0-4/proton'),
    ('https://github.com/Open-Wine-Components/umu-launcher/releases/download/1.4.4/umu-launcher-1.4.4-zipapp.tar',
     'eb590691841f7fad3fc3ad8fd5db4ccb87849fe7948e62b28ece7a4ee48cc851', 'umu/umu-run'),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rounds', type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 10:
        parser.error('Choose between 1 and 10 rounds')
    test = ROOT / '.test-proton'
    test.mkdir(exist_ok=True)
    for url, sha, marker in ASSETS:
        archive = test / url.rsplit('/', 1)[1]
        if not archive.exists():
            print('Downloading', archive.name, flush=True)
            partial = archive.with_suffix('.partial')
            with urllib.request.urlopen(url, timeout=30) as response, partial.open('wb') as out:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > 600 * 1024**2:
                        raise core.HostError('Experimental runtime archive exceeds size limit')
                    out.write(chunk)
            if core.digest(partial) != sha:
                raise core.HostError('Experimental runtime download verification failed')
            partial.rename(archive)
        if core.digest(archive) != sha:
            raise core.HostError('Experimental runtime archive checksum mismatch')
        if not (test / marker).is_file():
            core.safe_extract(archive, test)
    prefix = test / 'prefix'
    exports = {
        'UMU_FOLDERS_PATH': str(test/'runtime'), 'XDG_CACHE_HOME': str(test/'cache'),
        'WINEPREFIX': str(prefix), 'PROTONPATH': str(test/'UMU-Proton-10.0-4'),
        'GAMEID': 'umu-default', 'PROTON_VERB': 'run', 'UMU_RUNTIME_UPDATE': '0',
        'WINEDEBUG': '-all', 'PROTON_LOG': '0', 'PRESSURE_VESSEL_SHARE_PID': '1',
        'PRESSURE_VESSEL_COPY_RUNTIME': '0',
    }
    env = os.environ.copy()
    for key in ('WINELOADER', 'WINESERVER', 'WINEARCH', 'WINEDLLPATH', 'WINEPREFIX', 'WAYLAND_DISPLAY', 'LD_PRELOAD'):
        env.pop(key, None)
    env.update(exports)
    fixture = ROOT / 'build/fixtures/Install-Test-Gain.exe'
    if not fixture.exists():
        raise core.HostError('Run scripts/build-fixture.sh first')
    rc = core.run_process([test/'umu/umu-run', fixture], env, test/'installer.log', timeout=300)
    if rc:
        raise core.HostError(f'Test installer failed with exit {rc}; see .test-proton/installer.log')
    launcher = test / 'launch-proton'
    launcher.write_text('#!/bin/sh\nset -eu\n'
        'unset WINELOADER WINESERVER WINEARCH WINEDLLPATH WAYLAND_DISPLAY LD_PRELOAD\n'
        'if [ "${1:-}" = "--version" ]; then printf "%s\\n" "UMU-Proton-10.0-4"; exit 0; fi\n'
        + ''.join('export '+k+'='+shlex.quote(v)+'\n' for k,v in exports.items())
        + 'exec '+shlex.quote(str(test/'umu/umu-run'))+' "$@"\n')
    launcher.chmod(0o700)
    (prefix/'.plugg-runtime').write_text(str(launcher)+'\n')
    store = core.Store(test/'library', test/'published-unused')
    bundle = test/'ph-probe.vst3'
    module = prefix/'drive_c/Program Files/Common Files/VST3/Plugg Test Gain.vst3'
    native = (bundle/'Contents/x86_64-linux/ph-probe.so') if bundle.exists() else core.make_bundle(store,module,bundle)
    # pressure-vessel shares /dev/shm; no disk-backed hot audio transport.
    ipc = Path('/dev/shm') / ('ph-test-'+str(os.getuid()))
    ipc.mkdir(mode=0o700, exist_ok=True)
    stat = ipc.lstat()
    if ipc.is_symlink() or stat.st_uid != os.getuid() or stat.st_mode & 0o077:
        raise core.HostError('The experimental IPC directory is not private')
    def audio(number):
        output = test/f'repeat-{number}.json'
        output.unlink(missing_ok=True)
        child_env = os.environ.copy()
        child_env['YABRIDGE_TEMP_DIR'] = str(ipc)
        try:
            code = core.run_process([store.bridge()/'plugg-scan',native,output,'--audio'],
                                   child_env,test/f'repeat-{number}.log',timeout=30)
            data = json.loads(output.read_text()) if output.exists() and output.stat().st_size else {}
            return {'instance': number, 'exit': code, 'audio': data,
                    'passed': code == 0 and data.get('audio_fixture_passed',False)}
        except Exception as exc:
            return {'instance': number, 'passed': False, 'error': str(exc)}
    results = []
    for trial in range(args.rounds):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results.extend(pool.map(audio, (trial*2,trial*2+1)))
    report = {'backend': 'UMU-Proton-10.0-4', 'umu': '1.4.4',
              'experimental': True, 'passed': all(x['passed'] for x in results), 'instances': results,
              'runtime_versions': (test/'runtime/umu/steamrt3/VERSIONS.txt').read_text(),
              'caveats': ['No real Bitwig or vendor plug-in validation',
                          'UMU still performs startup network checks despite update suppression',
                          'Repeated container/process lifecycle reliability remains a release gate']}
    core.atomic_json(test/'results.json',report)
    print(json.dumps(report,indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
