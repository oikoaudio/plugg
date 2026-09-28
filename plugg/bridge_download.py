"""The prebuilt bridge for an installed Plugg, downloaded once and checked by hash.

A release's Python package carries `recipes/bridge-release.json`, written by
the release workflow: the URL of the bridge built for that release and its
SHA-256. A checkout has no such file and builds its own bridge with
scripts/build-bridge.sh; a distribution package ships its own in
/usr/lib/plugg/bridge. Either of those is used first.

The archive comes only from this project's GitHub releases and is refused
unless it matches the pinned hash. Its files are then checked again against
the build manifest inside it, like any other bridge.
SPDX-License-Identifier: GPL-3.0-or-later
"""
import json
import os
from pathlib import Path
import re
import tempfile

from . import artifacts, bridge_bundle, core

PINNED = Path(__file__).parent / 'recipes/bridge-release.json'


def pinned():
    """The bridge this package was released with, or None for a checkout."""
    try:
        release = json.loads(PINNED.read_text())
    except FileNotFoundError:
        return None
    if (not isinstance(release, dict) or not isinstance(release.get('version'), str)
            or not re.fullmatch(r'[0-9A-Za-z.+-]+', release['version'])
            or not isinstance(release.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', release['sha256'])
            or not isinstance(release.get('url'), str)):
        raise core.HostError('The pinned bridge release in ' + str(PINNED) + ' is malformed.')
    return release


def location(release, data_home=None):
    """Where a downloaded bridge lives: per user, named by the archive's hash."""
    data_home = Path(data_home or os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    return (data_home / 'plugg/bridge-downloads' / release['sha256'][:16]
            / ('plugg-bridge-' + release['version'] + '-x86_64'))


def downloaded():
    """The downloaded bridge for this package, if it is there already."""
    release = pinned()
    if release is None:
        return None
    directory = location(release)
    return directory if (directory / 'build.json').is_file() else None


def provision(store, report=lambda _: None, check=lambda: None):
    """Download and unpack this package's bridge once; return its directory."""
    release = pinned()
    if release is None:
        raise core.HostError('The native bridge is missing. This is a checkout: build it with scripts/build-bridge.sh.')
    target = location(release)
    base = target.parent
    base.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with core.lock(base.parent / '.provision.lock'):
        if (target / 'build.json').is_file():
            bridge_bundle.inspect(target)
            return target
        report('Downloading the plug-in bridge')
        archive = artifacts.fetch(store, release, report, check, artifacts.RUNTIME_RELEASES)
        with tempfile.TemporaryDirectory(dir=base.parent, prefix='.prepare-bridge-') as tmp:
            stage = Path(tmp)
            report('Unpacking the plug-in bridge')
            core.safe_extract(archive, stage, check)
            unpacked = stage / target.name
            bridge_bundle.inspect(unpacked)
            base.mkdir(exist_ok=True)
            unpacked.rename(target)
        return target
