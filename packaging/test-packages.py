#!/usr/bin/env python3
"""Install Plugg's .deb and .rpm in clean distribution containers and check them.

For each distribution: start a digest-pinned container, install the package
with the distribution's package manager (so it resolves the dependencies the
package declares, and nothing else is preinstalled), then check it as an
ordinary user with packaging/package-check.py:

  cli    before any test tool is installed: plugg --help, plugg doctor (the
         bridge at /usr/lib/plugg/bridge, no bridge error), the recipe
         catalogue, the bridge manifest, loading the bridge libraries,
         starting the scanner, finding the PowerShell forwarder, GTK >= 4.10
         through PyGObject, the desktop entry and the byte-compiled app.
  gui    after installing Xvfb and a few X tools: the app's GTK window under
         Xvfb, and the installed launcher's `plugg gui` window.

Then it checks that the distribution orders the converted package versions as
PEP 440 does, removes the package and checks that nothing is left in
/usr/lib/plugg.

No host mounts: files go in with docker cp. Every container carries the
label plugg.test=distribution-packages, and only the container this run
created is removed, after checking that label. Other containers, images,
networks and volumes are never touched. Logs and results go into --output,
which must be new.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
LABEL_KEY, LABEL_VALUE = 'plugg.test', 'distribution-packages'

DEB_TOOLS = 'xvfb xauth dbus-daemon x11-utils desktop-file-utils'
RPM_TOOLS = 'xorg-x11-server-Xvfb xauth dbus-daemon xwininfo desktop-file-utils'
DISTRIBUTIONS = {
    'ubuntu-24.04': {
        'image': 'ubuntu@sha256:224a1869083a311ef3f13648a154ba79832fbef6364d31493642ca03082da254',
        'format': 'deb'},
    'debian-13': {
        'image': 'debian@sha256:9cc080028c43b27d2074d63a5f9caf7166d731494965616c1a6d2827a004585c',
        'format': 'deb'},
    'fedora-42': {
        'image': 'fedora@sha256:99e203b80b1c3d8f7e161ec10a68fd02b081ef83a3963553e513c82846b97814',
        'format': 'rpm'},
    'fedora-44': {
        'image': 'fedora@sha256:43b29f65a41eb9c35e1cd5323e3bdf3b655c2357a9f4f1ff2f9c2798e5045d80',
        'format': 'rpm'},
}
FORMATS = {
    'deb': {
        'install': 'apt-get update -q && DEBIAN_FRONTEND=noninteractive '
                   'apt-get install -y --no-install-recommends {package}',
        'tools': 'DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ' + DEB_TOOLS,
        'version': "dpkg-query -W -f '${{Version}}' plugg",
        'depends': "dpkg-query -W -f '${{Depends}}' plugg",
        'files': 'dpkg -L plugg',
        'remove': 'DEBIAN_FRONTEND=noninteractive apt-get remove -y plugg',
        'older': 'dpkg --compare-versions {older} lt {newer}',
    },
    'rpm': {
        'install': 'dnf install -y --setopt=install_weak_deps=False {package}',
        'tools': 'dnf install -y --setopt=install_weak_deps=False ' + RPM_TOOLS,
        'version': "rpm -q --qf '%{{VERSION}}-%{{RELEASE}}' plugg",
        'depends': 'rpm -q --requires plugg',
        'files': 'rpm -ql plugg',
        'remove': 'dnf remove -y plugg',
        'older': 'test "$(rpm --eval \'%{{lua: print(rpm.vercmp("{older}", "{newer}"))}}\')" = -1',
    },
}
#: PEP 440 versions in ascending order; each distribution must agree after conversion.
ORDERED = ['0.1.0.dev0', '0.1.0a1.dev0', '0.1.0a1', '0.1.0b1', '0.1.0rc1.dev1', '0.1.0rc1',
           '0.1.0rc1.post1', '0.1.0', '0.1.0.post1.dev0', '0.1.0.post1', '0.1.1.dev0', '0.1.1', '0.2.0']


def build_script():
    spec = importlib.util.spec_from_file_location('build_release_packages', REPO / 'scripts/build-release-packages.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Container:
    """One labelled test container, removed only by its own ID and label."""

    def __init__(self, name, image, output):
        self.output = output
        self.id = subprocess.check_output(
            ['docker', 'run', '-d', '--name', name, '--label', LABEL_KEY + '=' + LABEL_VALUE,
             '--cpus=2', '--memory=3g', '--pids-limit=1024', '--shm-size=256m', image, 'sleep', 'infinity'],
            text=True).strip()
        (output / 'container.json').write_text(json.dumps(
            {'id': self.id, 'name': name, 'image': image, 'host_mounts': False}, indent=2) + '\n')

    def sh(self, script, log, user=None, check=True):
        """Run a shell script and return its standard output; both streams go to log."""
        command = ['docker', 'exec'] + (['-u', user, '-w', '/home/' + user] if user else []) + [self.id, 'sh', '-c', script]
        result = subprocess.run(command, capture_output=True, text=True)
        with (self.output / log).open('a') as stream:
            stream.write('$ ' + script + '\n' + result.stdout)
            stream.write(('[stderr]\n' + result.stderr if result.stderr else '') + '[exit %d]\n\n' % result.returncode)
        if check and result.returncode:
            raise RuntimeError('%s failed (exit %d), see %s:\n%s' % (script, result.returncode, log,
                                                                   (result.stdout + result.stderr)[-3000:]))
        return result.stdout

    def copy_in(self, source, target):
        subprocess.run(['docker', 'cp', str(source), self.id + ':' + target], check=True)

    def remove(self):
        label = subprocess.check_output(['docker', 'inspect', '--format',
                                         '{{ index .Config.Labels "' + LABEL_KEY + '" }}', self.id], text=True).strip()
        if label != LABEL_VALUE:
            raise RuntimeError('Container ownership label changed; refusing to remove ' + self.id)
        subprocess.run(['docker', 'rm', '-f', self.id], check=True, stdout=subprocess.DEVNULL)


def test(name, packages, version, output):
    distribution = DISTRIBUTIONS[name]
    kind = FORMATS[distribution['format']]
    build = build_script()
    converted = build.package_version(version)
    package = (packages / ('plugg_' + version + '_amd64.deb') if distribution['format'] == 'deb'
               else packages / ('plugg-' + version + '-1.x86_64.rpm')).resolve(strict=True)
    output.mkdir()
    result = {'distribution': name, 'image': distribution['image'], 'package': package.name, 'passed': False}
    container = Container('plugg-packages-' + name + '-' + uuid.uuid4().hex[:8], distribution['image'], output)
    try:
        container.sh('mkdir -p /tmp/plugg-test', 'setup.log')
        container.copy_in(package, '/tmp/plugg-test/' + package.name)
        container.copy_in(REPO / 'packaging/package-check.py', '/tmp/plugg-test/package-check.py')
        container.sh('head -2 /etc/os-release', 'setup.log')
        print(name + ': installing ' + package.name, flush=True)
        container.sh(kind['install'].format(package='/tmp/plugg-test/' + package.name), 'install.log')
        installed = container.sh(kind['version'].format(), 'install.log').strip()
        if installed != converted + '-1':
            raise RuntimeError('Installed version is %s, expected %s-1' % (installed, converted))
        result['installed_version'] = installed
        result['declared_dependencies'] = container.sh(kind['depends'].format(), 'install.log').strip()
        result['files'] = len(container.sh(kind['files'], 'install.log').split())
        container.sh('useradd -m musician', 'setup.log')
        check = '/usr/bin/python3 -I /tmp/plugg-test/package-check.py {phase} --version ' + shlex.quote(version)
        print(name + ': checking as an ordinary user', flush=True)
        container.sh(check.format(phase='cli'), 'check-cli.log', user='musician')
        result['cli'] = json.loads(container.sh('cat package-check-cli.json', 'check-cli.log', user='musician'))
        print(name + ': installing test tools and checking the GUI', flush=True)
        container.sh(kind['tools'], 'tools.log')
        container.sh('desktop-file-validate /usr/share/applications/com.oikoaudio.Plugg.desktop', 'check-gui.log')
        result['desktop_entry_valid'] = True
        container.sh('xvfb-run -a dbus-run-session -- ' + check.format(phase='gui'), 'check-gui.log', user='musician')
        result['gui'] = json.loads(container.sh('cat package-check-gui.json', 'check-gui.log', user='musician'))
        for older, newer in zip(ORDERED, ORDERED[1:]):
            container.sh(kind['older'].format(older=build.package_version(older),
                                              newer=build.package_version(newer)), 'versions.log')
        result['version_order_agrees'] = ORDERED
        print(name + ': removing the package', flush=True)
        container.sh(kind['remove'], 'remove.log')
        container.sh('test ! -e /usr/lib/plugg && test ! -e /usr/bin/plugg '
                     '&& test ! -e /usr/share/applications/com.oikoaudio.Plugg.desktop', 'remove.log')
        result['removed_cleanly'] = True
        result['passed'] = True
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        container.remove()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('packages', type=Path, help='Directory holding the built .deb and .rpm')
    parser.add_argument('--output', type=Path, required=True, help='New directory for logs and results')
    parser.add_argument('--distribution', action='append', choices=sorted(DISTRIBUTIONS),
                        help='Test only this distribution (repeatable; default: all)')
    args = parser.parse_args()
    version = build_script().declared_version()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    results = [test(name, args.packages, version, output / name) for name in args.distribution or DISTRIBUTIONS]
    summary = [{key: result.get(key) for key in ('distribution', 'installed_version', 'passed', 'error')}
               for result in results]
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    for result in results:
        print(result['distribution'] + ': ' + ('passed' if result['passed'] else 'FAILED: ' + result['error']))
    return 0 if all(result['passed'] for result in results) else 1


if __name__ == '__main__':
    sys.exit(main())
