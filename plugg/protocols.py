"""Desktop authentication handoff. Never print or persist callback URLs.
SPDX-License-Identifier: GPL-3.0-or-later
"""
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit


def validate_uri(uri):
    if not isinstance(uri, str) or len(uri) > 16384 or any(ord(c) < 32 for c in uri):
        raise ValueError('Invalid callback')
    if urlsplit(uri).scheme.lower() != 'native-access':
        raise ValueError('Unsupported callback protocol')


def dispatch(config_path, uri):
    validate_uri(uri)
    config = json.loads(Path(config_path).read_text())
    launcher = Path(config['launcher'])
    if not launcher.is_absolute() or not launcher.is_file():
        raise ValueError('Callback launcher is unavailable')
    # Pass the original URI unchanged as one argument. No shell, logging or
    # output capture: vendor output can include authentication information.
    return subprocess.Popen([str(launcher), config['application'], uri],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)


def main():
    try:
        # Started by the desktop, from wherever it likes; Proton needs a usable working directory.
        os.chdir(Path.home())
        if len(sys.argv) != 3:
            return 1
        dispatch(sys.argv[1], sys.argv[2])
        return 0
    except Exception:
        # Do not expose callback contents through exception diagnostics.
        return 1


if __name__ == '__main__':
    sys.exit(main())
