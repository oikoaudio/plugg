#!/usr/bin/env python3
"""Build and install an AUR package with makepkg -si in a clean Arch Linux container.

Everything comes from this checkout's HEAD. For the release package `plugg`,
HEAD becomes a source archive laid out as GitHub lays out a tag archive
(plugg-<version>/...), and the PKGBUILD gets that version and the archive's
SHA-256 through scripts/update-aur.py's own rewrite, so the release recipe is
proven before there is a tag. makepkg finds the archive next to the PKGBUILD
and downloads nothing for it. `plugg-git` is built from a bare copy of HEAD
through the PKGBUILD's PLUGG_SOURCE override. yabridge comes from GitHub at
the pinned commit and is checked against the PKGBUILD's checksum.

In the container, as root: packages come from the Arch Linux Archive at a
fixed date (or the live mirrors with --live). As the unprivileged user
builder: the committed .SRCINFO files must equal makepkg --printsrcinfo, then
makepkg -si builds, runs the unit suite in check() and installs. As a second
ordinary user with an empty home: packaging/aur-check.py (plugg doctor, the
bridge, the PowerShell forwarder) and packaging/container-check.py (native
libraries, the scanner, a GTK window under Xvfb). namcap's findings are logged
and do not fail the test.

No host mounts. Only this invocation's container is removed. Existing
containers, images, networks and volumes are never cleaned up or reconfigured.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('update_aur', REPO / 'scripts/update-aur.py')
update_aur = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update_aur)

IMAGE = update_aur.ARCH_IMAGE
LABEL_KEY, LABEL_VALUE = 'plugg.test', 'aur'
# The Arch Linux Archive snapshot the container's packages come from. Moving
# it moves the compiler, Wine, Python and GTK the package is tested with.
ARCHIVE_DATE = '2026/09/27'
TOOLS = 'base-devel git sudo namcap xorg-server-xvfb xorg-xauth'


def git(*args, **kwargs):
    return subprocess.run(['git', '-C', str(REPO), *args], check=True, **kwargs)


def head_file(path):
    return git('show', 'HEAD:' + path, capture_output=True).stdout


def stage(package, staging):
    """Write what the container needs into `staging`; return the build's environment and a summary."""
    commit = git('rev-parse', 'HEAD', capture_output=True, text=True).stdout.strip()
    version = re.search(rb'^__version__ = "(.*)"$', head_file('plugg/__init__.py'), re.MULTILINE).group(1).decode()
    for name in update_aur.PACKAGES:
        for file in ('PKGBUILD', '.SRCINFO'):
            target = staging / 'aur' / name / file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(head_file(f'packaging/aur/{name}/{file}'))
    for name in ('aur-check.py', 'container-check.py'):
        target = staging / 'checks' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(head_file('packaging/' + name))
    build = staging / 'pkg'
    build.mkdir()
    pkgbuild = head_file(f'packaging/aur/{package}/PKGBUILD').decode()
    summary = dict(package=package, commit=commit, version=version, image=IMAGE)
    environment = {}
    if package == 'plugg':
        archive = build / f'plugg-{version}.tar.gz'
        git('archive', '--format=tar.gz', f'--prefix=plugg-{version}/', '-o', str(archive), 'HEAD')
        update_aur.check_archive(archive, version)
        summary['archive_sha256'] = update_aur.sha256_file(archive)
        pkgbuild = update_aur.rewrite(pkgbuild, version, summary['archive_sha256'], '1')
    else:
        bare = staging / 'plugg.git'
        subprocess.run(['git', 'init', '--quiet', '--bare', str(bare)], check=True)
        subprocess.run(['git', '-C', str(bare), 'fetch', '--quiet', str(REPO), 'HEAD:refs/heads/main'], check=True)
        fetched = subprocess.run(['git', '-C', str(bare), 'rev-parse', 'main'], check=True,
                                 capture_output=True, text=True).stdout.strip()
        if fetched != commit:
            raise RuntimeError('The bare copy is not at HEAD')
        environment['PLUGG_SOURCE'] = 'git+file:///home/builder/plugg.git#branch=main'
    (build / 'PKGBUILD').write_text(pkgbuild)
    return environment, summary


class Container:
    def __init__(self, output, cpus, memory):
        self.output = output
        name = 'plugg-aur-' + uuid.uuid4().hex[:12]
        self.id = subprocess.check_output(
            ['docker', 'run', '-d', '--name', name, '--label', f'{LABEL_KEY}={LABEL_VALUE}',
             f'--cpus={cpus}', f'--memory={memory}', '--pids-limit=8192', '--shm-size=256m',
             IMAGE, 'sleep', 'infinity'], text=True).strip()
        (output / 'container.json').write_text(json.dumps(
            dict(id=self.id, name=name, image=IMAGE, host_mounts=False), indent=2) + '\n')

    def step(self, title, script, user='root', env=None):
        """Run a bash script in the container, its output in <output>/<title>.log."""
        log = self.output / (title + '.log')
        command = ['docker', 'exec', '-u', user, '-w', '/root' if user == 'root' else f'/home/{user}',
                   '-e', 'HOME=' + ('/root' if user == 'root' else f'/home/{user}')]
        for key, value in (env or {}).items():
            command += ['-e', f'{key}={value}']
        print(f'==> {title}', flush=True)
        with open(log, 'w') as stream:
            result = subprocess.run(command + [self.id, 'bash', '-euo', 'pipefail', '-c', script],
                                    stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            lines = log.read_text(errors='replace').splitlines()
            print('\n'.join(lines[-60:]), file=sys.stderr)
            raise RuntimeError(f'{title} failed; the full log is {log}')
        return log.read_text(errors='replace')

    def copy_out(self, source, target):
        if subprocess.run(['docker', 'exec', self.id, 'test', '-e', source], capture_output=True).returncode == 0:
            subprocess.run(['docker', 'cp', f'{self.id}:{source}', str(target)], check=False)

    def remove(self):
        label = subprocess.check_output(['docker', 'inspect', '--format',
                                         '{{ index .Config.Labels "%s" }}' % LABEL_KEY, self.id], text=True).strip()
        if label != LABEL_VALUE:
            raise RuntimeError('Container ownership label changed; refusing removal')
        subprocess.run(['docker', 'rm', '-f', self.id], check=True, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, required=True,
                        help='New directory for logs, results and the built package, on disk rather than tmpfs')
    parser.add_argument('--package', choices=update_aur.PACKAGES, default='plugg')
    parser.add_argument('--archive-date', default=ARCHIVE_DATE,
                        help='Arch Linux Archive date, YYYY/MM/DD (default %(default)s)')
    parser.add_argument('--live', action='store_true', help="use the image's live mirrors instead of the archive")
    parser.add_argument('--cpus', type=int, default=8)
    parser.add_argument('--memory', default='12g')
    args = parser.parse_args()
    if not re.fullmatch(r'\d{4}/\d{2}/\d{2}', args.archive_date):
        parser.error('--archive-date must be YYYY/MM/DD')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    dirty = git('status', '--porcelain', '--untracked-files=no', capture_output=True, text=True).stdout
    if dirty:
        print('Note: the test uses HEAD; uncommitted changes are not in it.', file=sys.stderr)
    staging = output / 'input'
    staging.mkdir()
    environment, summary = stage(args.package, staging)
    summary.update(passed=False, repositories='live' if args.live else 'https://archive.archlinux.org/repos/' + args.archive_date)
    container = Container(output, args.cpus, args.memory)
    try:
        subprocess.run(['docker', 'cp', str(staging) + '/.', container.id + ':/buildsrc'], check=True)
        mirror = '' if args.live else (
            "echo 'Server = https://archive.archlinux.org/repos/%s/$repo/os/$arch' > /etc/pacman.d/mirrorlist\n"
            % args.archive_date)
        container.step('01-system', mirror + f'''
pacman -Sy --noconfirm archlinux-keyring
pacman -Syyuu --noconfirm --needed {TOOLS}
useradd -m builder
useradd -m musician
echo 'builder ALL=(root) NOPASSWD: /usr/bin/pacman' > /etc/sudoers.d/builder
chmod 440 /etc/sudoers.d/builder
cp -a /buildsrc/pkg /home/builder/pkg
if [ -d /buildsrc/plugg.git ]; then cp -a /buildsrc/plugg.git /home/builder/plugg.git; fi
chown -R builder:builder /home/builder
pacman -Q pacman git python
''')
        container.step('02-srcinfo', '''
for package in plugg plugg-git; do
    work=$(mktemp -d)
    cp /buildsrc/aur/$package/PKGBUILD "$work/"
    (cd "$work" && env -u PLUGG_SOURCE makepkg --printsrcinfo) | diff -u /buildsrc/aur/$package/.SRCINFO -
    echo "$package: the committed .SRCINFO matches makepkg --printsrcinfo"
done
''', user='builder')
        container.step('03-makepkg', 'cd ~/pkg && makepkg -si --noconfirm', user='builder',
                       env=dict(environment, PLUGG_BUILD_JOBS=str(args.cpus)))
        installed = container.step('04-installed', f'''
pacman -Q {args.package} wine python gtk4 go meson
pacman -Qlq {args.package} | grep '^/usr/lib/plugg/'
namcap ~/pkg/PKGBUILD ~/pkg/*.pkg.tar.zst || true
''', user='builder')
        summary['installed'] = installed.splitlines()[0]
        container.step('05-aur-check', '/usr/bin/python -I /buildsrc/checks/aur-check.py', user='musician')
        container.step('06-container-check', 'xvfb-run -a dbus-run-session -- /usr/bin/python -I '
                       '/buildsrc/checks/container-check.py --bridge /usr/lib/plugg/bridge',
                       user='musician', env={'GSK_RENDERER': 'cairo'})
        summary['passed'] = True
    finally:
        # Even on failure, keep the results and the package, and remove only our container.
        packages = subprocess.run(['docker', 'exec', container.id, 'sh', '-c', 'ls /home/builder/pkg/*.pkg.tar.zst'],
                                  capture_output=True, text=True).stdout.split()
        for path in packages:
            container.copy_out(path, output / Path(path).name)
        for source, target in [('/home/musician/aur-result.json', 'aur-result.json'),
                               ('/home/musician/package-result.json', 'package-result.json')]:
            container.copy_out(source, output / target)
        (output / 'result.json').write_text(json.dumps(summary, indent=2) + '\n')
        container.remove()
    for path in sorted(output.glob('*.pkg.tar.zst')):
        print(f'{path.name} {hashlib.sha256(path.read_bytes()).hexdigest()}')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
