"""Typed Windows helper entry point for existing managed environments.

Callers own environment selection, locking, job state and licensing policy.
"""
from pathlib import Path
import shlex
import os

from . import core, licensing


def validate(spec):
    if not isinstance(spec, dict) or set(spec) != {'name', 'executable', 'archive_tools'}:
        raise ValueError('Helper requires name, executable and archive_tools')
    if not isinstance(spec['name'], str) or not spec['name'].strip():
        raise ValueError('Helper name must be nonempty text')
    path = spec['executable']
    if (not isinstance(path, str) or not path.lower().endswith('.exe') or
            any(char in path for char in '\\:%!^&|<>"\r\n\0') or
            any(part in ('', '.', '..') for part in path.split('/'))):
        raise ValueError('Helper executable must be a literal relative Windows EXE path')
    if type(spec['archive_tools']) is not bool:
        raise ValueError('Helper archive_tools must be true or false')
    return spec


def installed_binary(prefix, spec):
    validate(spec)
    drive = (Path(prefix) / 'drive_c').resolve()
    binary = drive / spec['executable']
    if not binary.resolve().is_relative_to(drive) or not binary.is_file():
        raise core.HostError('Helper was not found inside its environment after installation.')
    return binary


def configure(prefix, full_launcher, spec):
    validate(spec)
    prefix = Path(prefix)
    licensing.guard(prefix.parent, 'install_helper')
    batch = prefix / 'drive_c/Plugg/launch-helper.cmd'
    if not batch.resolve().is_relative_to((prefix / 'drive_c').resolve()):
        raise core.HostError('Helper launcher escapes its environment')
    batch.parent.mkdir(parents=True, exist_ok=True)
    path = 'C:\\' + spec['executable'].replace('/', '\\')
    lines = ['@echo off', 'set "SteamAppId="']
    if spec['archive_tools']:
        lines.append('set "PATH=C:\\Plugg\\Tools\\Archive;%PATH%"')
    lines.append('"' + path + '"')
    batch.write_text('\n'.join(lines) + '\n')
    launcher = prefix.parent / 'launch-helper'
    launcher.write_text('#!/bin/sh\nexec ' + shlex.join([
        str(full_launcher), 'cmd.exe', '/c', r'C:\Plugg\launch-helper.cmd']) + '\n')
    launcher.chmod(0o700)
    return launcher


def install(job, prefix, full_launcher, spec, arguments, check):
    """Run a saved installer; the adapter holds job/environment locks."""
    validate(spec)
    licensing.guard(Path(prefix).parent, 'install_helper')
    # The policy belongs at the point of use: every caller passing a list of
    # arguments to a vendor installer is subject to it, not only recipe loading.
    from . import helper_recipes
    helper_recipes.validate_arguments(list(arguments))
    check()
    core.verify_installer(job)
    installer = Path(job['installer'])
    # Output can contain account information. UI/progress belongs to the adapter.
    result = core.run_process([full_launcher, str(installer), *arguments],
                              os.environ.copy(), Path(os.devnull), check, 7200,
                              cwd=installer.parent)
    if result:
        raise core.HostError(spec['name'] + ' installation did not finish successfully (exit ' + str(result) + ').')
    check()
    return installed_binary(prefix, spec)
