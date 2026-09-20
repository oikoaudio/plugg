"""Fixed vendor service registration, shared by reviewed setup adapters.

Service specifications come from adapter code, not recipes or installers.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import tempfile
import time
from . import core, licensing, ua_connect


@dataclass(frozen=True)
class Service:
    name: str
    display: str
    executable: str
    start: str = 'demand'

    def __post_init__(self):
        if (not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', self.name)
                or not re.fullmatch(r'[A-Za-z0-9 ()_-]+', self.display)
                or not re.fullmatch(r'[A-Za-z0-9 /()._-]+\.exe', self.executable)
                or self.executable.startswith('/') or '..' in self.executable.split('/')
                or self.start not in ('auto', 'demand')):
            raise ValueError('Invalid fixed service specification')

    @property
    def image(self):
        return '"C:\\' + self.executable.replace('/', '\\') + '"'


def status(environment, spec):
    section = 'System\\ControlSet001\\Services\\' + spec.name
    names = ('ImagePath', 'Start', 'Type', 'ObjectName')
    values = licensing._registry_values(Path(environment) / 'prefix/system.reg', {
        section: [(name, section, name) for name in names]})
    actual = {name: values.get((section.casefold(), name.casefold())) for name in names}
    if not any(value is not None for value in actual.values()):
        return 'absent'
    image = actual['ImagePath'] or ''
    if image.startswith('str(2):'):
        image = image[7:]
    expected = (licensing._normalize(image) == spec.image
                and actual['Start'] == ('dword:00000002' if spec.start == 'auto' else 'dword:00000003')
                and actual['Type'] == 'dword:00000010'
                and licensing._normalize(actual['ObjectName']) == 'LocalSystem')
    return 'matching' if expected else 'different'


def register(environment, spec, *, prepare, timeout=90):
    environment = Path(environment)
    licensing.guard(environment, 'install_component')
    current = status(environment, spec)
    if current == 'matching':
        return False
    if current != 'absent':
        raise core.HostError('Existing service differs; it has not been replaced: ' + spec.name)
    drive = environment / 'prefix/drive_c'
    folder = drive / 'Plugg'
    if (not drive.is_dir() or not drive.resolve().is_relative_to(environment.resolve())
            or not folder.resolve().is_relative_to(drive.resolve())):
        raise core.HostError('Service command path escapes the environment.')
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='service-', dir=folder) as temp:
        temp = Path(temp)
        result = temp / 'result.txt'
        win = 'C:\\Plugg\\' + temp.name
        command = ('sc.exe create ' + spec.name + ' binPath= "' + spec.image.replace('"', '\\"')
                   + '" start= ' + spec.start + ' type= own obj= LocalSystem DisplayName= "' + spec.display + '"')
        (temp / 'register.cmd').write_bytes(('@echo off\r\nset "SteamAppId="\r\n' + command
            + '\r\necho %errorlevel% > "' + win + '\\result.txt"\r\n').encode())
        child = subprocess.Popen([str(environment / 'launch-full-proton'), 'cmd.exe', '/c', win + '\\register.cmd'],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + timeout
        while not result.exists():
            if child.poll() is not None or time.monotonic() >= deadline:
                if child.poll() is None:
                    child.terminate()
                raise core.HostError('Service registration did not finish; inspect before retrying: ' + spec.name)
            time.sleep(.2)
        time.sleep(.5)
        prepare(environment, bootstrap_pids=ua_connect.descendants(child.pid))
        child.wait(timeout=20)
        if result.read_text().strip() != '0' or status(environment, spec) != 'matching':
            raise core.HostError('Service registration failed validation: ' + spec.name)
    return True
