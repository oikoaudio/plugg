"""Desktop callback routing to the one live managed Native Access session.

Only session metadata is persisted. Login URLs are never recorded.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from . import core, protocols, vendors

DESKTOP = 'plugg-native-access-router.desktop'


def state_path():
    root = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / ('plugg-' + str(os.getuid()))
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != os.getuid():
        raise core.HostError('Unsafe Native Access callback directory.')
    root.chmod(0o700)
    return root / 'native-access-session.json'


def process_identity(pid):
    try:
        return (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def live(record):
    identity = process_identity(record.get('pid'))
    return identity is not None and identity == record.get('process_start')


def install_handler():
    apps = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'applications'
    apps.mkdir(parents=True, exist_ok=True)
    def quoted(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
    content = ('[Desktop Entry]\nType=Application\nName=Native Access login (Plugg)\n'
               'NoDisplay=true\nTerminal=false\nExec=env ' + quoted('PYTHONPATH=' + str(core.REPO)) + ' '
               + quoted(sys.executable) + ' -m plugg.native_access_routing %u\n'
               'MimeType=x-scheme-handler/native-access;\n')
    desktop = apps / DESKTOP
    if not desktop.exists() or desktop.read_text() != content:
        desktop.write_text(content)
    subprocess.run(['xdg-mime', 'default', DESKTOP, 'x-scheme-handler/native-access'],
                   check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def claim(config_path, owner_pid):
    state = state_path()
    token = uuid.uuid4().hex
    with core.lock(state.with_suffix('.lock'), blocking=False):
        if state.exists():
            previous = json.loads(state.read_text())
            if live(previous):
                if previous.get('pid') == owner_pid and previous.get('config') == str(Path(config_path).resolve()):
                    return previous['token']
                raise core.HostError('Another Native Access session already owns browser sign-in.')
        install_handler()
        core.atomic_json(state, {'pid': owner_pid, 'process_start': process_identity(owner_pid),
                                 'config': str(Path(config_path).resolve()), 'token': token})
    return token


@contextmanager
def active(config_path):
    state = state_path()
    token = claim(config_path, os.getpid())
    try:
        yield
    finally:
        with core.lock(state.with_suffix('.lock'), blocking=True):
            if state.exists() and json.loads(state.read_text()).get('token') == token:
                state.unlink()


def route(uri):
    protocols.validate_uri(uri)
    state = state_path()
    with core.lock(state.with_suffix('.lock'), blocking=False):
        record = json.loads(state.read_text())
        if not live(record):
            raise core.HostError('Open Native Access from Plugg before signing in.')
        config = Path(record['config'])
        if not any(name.casefold() == 'native access.exe' for _, name in vendors.running_programs(config.parent / 'prefix')):
            raise core.HostError('The Native Access session has closed. Start a new login.')
        return protocols.dispatch(config, uri)


def main():
    try:
        # Started by the desktop, from wherever it likes; Proton needs a usable working directory.
        os.chdir(Path.home())
        if len(sys.argv) != 2:
            return 1
        route(sys.argv[1])
        return 0
    except Exception:
        # Never pass exception text or the callback to desktop notifications.
        subprocess.run(['notify-send', 'Native Access sign-in',
                        'Open Native Access from Plugg and try signing in again.'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
