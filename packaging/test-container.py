#!/usr/bin/env python3
"""Build and check a wheel plus native bridge in a dedicated Ubuntu container.

No host mounts. Only this invocation's container is removed. Existing containers,
images, networks and volumes are never cleaned up or reconfigured.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

BASE = 'ubuntu@sha256:224a1869083a311ef3f13648a154ba79832fbef6364d31493642ca03082da254'
LABEL = 'plugg.test=packaging'
REPO = Path(__file__).resolve().parents[1]
PACKAGES = '''python3-venv python3-pip python3-gi gir1.2-gtk-4.0 libgtk-4-bin
binutils file xvfb xauth dbus-x11 libasound2t64 libpulse0 libxrandr2 libxinerama1
libxcursor1 libvulkan1 libgl1 libegl1 libfontconfig1 ca-certificates curl xz-utils
zstd libarchive-tools bubblewrap git patch meson ninja-build g++ pkg-config cmake
libxcb1-dev libdbus-1-dev wine wine64 wine64-tools libwine-dev clang lld'''.split()

def run(*command):
    subprocess.run([str(v) for v in command], check=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    parser.add_argument('--output', type=Path, required=True,
                        help='New artifact directory, preferably on disk rather than tmpfs')
    parser.add_argument('--runtime-smoke', action='store_true',
                        help='Also try UMU and synthetic audio; Docker namespace restrictions may prevent startup')
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    run(sys.executable, REPO / 'scripts/test-python-package.py', wheel)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    staging = output / 'input'
    staging.mkdir()
    for relative in ['scripts/build-bridge.sh', 'scripts/prepare-bridge-source.py',
                     'scripts/bridge-manifest.py', 'scripts/build-fixture.sh',
                     'native/scan.cpp', 'patches/yabridge-series.json',
                     'packaging/container-check.py', 'packaging/container-smoke.py',
                     'tests/fixtures/gain.cpp', 'tests/fixtures/installer.c',
                     'tests/fixtures/helper-installer.c']:
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / relative, target)
    for name in json.loads((REPO / 'patches/yabridge-series.json').read_text()):
        if Path(name).name != name or not name.endswith('.patch'):
            raise ValueError('Invalid bridge patch name')
        shutil.copy2(REPO / 'patches' / name, staging / 'patches' / name)
    shutil.copy2(wheel, staging / wheel.name)
    name = 'plugg-package-' + uuid.uuid4().hex[:12]
    container = subprocess.check_output(['docker', 'run', '-d', '--name', name,
        '--label', LABEL, '--cpus=2', '--memory=3g', '--pids-limit=512',
        '--shm-size=256m', BASE, 'sleep', 'infinity'], text=True).strip()
    (output / 'container.json').write_text(json.dumps(
        dict(id=container, name=name, base=BASE, host_mounts=False), indent=2) + '\n')
    try:
        run('docker', 'exec', container, 'mkdir', '-p', '/buildsrc', '/opt/plugg')
        run('docker', 'cp', str(staging) + '/.', container + ':/buildsrc')
        run('docker', 'exec', container, 'sh', '-ec',
            'apt-get update > /var/log/plugg-packages.log 2>&1; '
            'DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends '
            + ' '.join(PACKAGES) + ' >> /var/log/plugg-packages.log 2>&1')
        run('docker', 'exec', container, 'sh', '-ec',
            'useradd -m -s /bin/bash musician; '
            'python3 -m venv --system-site-packages /opt/plugg/venv; '
            '/opt/plugg/venv/bin/pip install --no-index --no-deps /buildsrc/*.whl; '
            'for tool in winegcc wineg++ winebuild; do '
            'for candidate in /usr/bin/$tool-stable /usr/lib/wine/$tool; do '
            'if [ -x "$candidate" ]; then ln -s "$candidate" /usr/local/bin/$tool; break; fi; '
            'done; command -v $tool; done; '
            'cd /buildsrc; PLUGG_BUILD_JOBS=2 PLUGG_BRIDGE_OUTPUT=/opt/plugg/bridge '
            'sh scripts/build-bridge.sh > /var/log/plugg-native-build.log 2>&1; '
            'WINE_KERNEL32_IMPORT_LIB=/usr/lib/x86_64-linux-gnu/wine/x86_64-windows/libkernel32.a '
            'sh scripts/build-fixture.sh > /var/log/plugg-fixture-build.log 2>&1')
        run('docker', 'exec', '-u', 'musician', '-e', 'GSK_RENDERER=cairo', container,
            'xvfb-run', '-a', 'dbus-run-session', '--', '/opt/plugg/venv/bin/python', '-I',
            '/buildsrc/packaging/container-check.py', '--bridge', '/opt/plugg/bridge')
        if args.runtime_smoke:
            run('docker', 'exec', '-u', 'musician', container, 'xvfb-run', '-a',
                '/opt/plugg/venv/bin/python', '-I', '/buildsrc/packaging/container-smoke.py',
                '--bridge', '/opt/plugg/bridge', '--installer',
                '/buildsrc/build/fixtures/Install-Test-Helper.exe', '--root', '/home/musician/smoke')
    finally:
        # Even on test failure, retain logs/results and remove only our exact ID.
        for source, target in [('/var/log/plugg-packages.log', 'packages.log'),
                               ('/var/log/plugg-native-build.log', 'native-build.log'),
                               ('/var/log/plugg-fixture-build.log', 'fixture-build.log'),
                               ('/buildsrc/build/meson-logs/meson-log.txt', 'meson.log'),
                               ('/opt/plugg/bridge', 'bridge'),
                               ('/home/musician/package-result.json', 'package-result.json'),
                               ('/home/musician/smoke/result.json', 'runtime-result.json')]:
            exists = subprocess.run(['docker', 'exec', container, 'test', '-e', source],
                                    capture_output=True)
            if exists.returncode == 0:
                subprocess.run(['docker', 'cp', container + ':' + source, str(output / target)],
                               check=False)
        label = subprocess.check_output(['docker', 'inspect', '--format',
            '{{ index .Config.Labels "plugg.test" }}', container], text=True).strip()
        if label != 'packaging':
            raise RuntimeError('Container ownership label changed; refusing removal')
        run('docker', 'rm', '-f', container)

if __name__ == '__main__':
    main()
