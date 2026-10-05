"""Validate a native bridge build without executing it, and keep the releases bundles link to."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

ARTIFACTS = ('libyabridge-vst3.so', 'libyabridge-chainloader-vst3.so',
             'yabridge-host.exe', 'yabridge-host.exe.so', 'plugg-scan', 'COPYING.yabridge')
#: What a build that also bridges VST2 and CLAP adds. Builds from before
#: then have none of these and still work for VST3.
FORMAT_ARTIFACTS = ('libyabridge-vst2.so', 'libyabridge-chainloader-vst2.so',
                    'libyabridge-clap.so', 'libyabridge-chainloader-clap.so')
#: The 32-bit host, which loads 32-bit VST2 plug-ins. Only builds made with
#: 32-bit Winelib support have it (scripts/build-bridge.sh, PLUGG_BITBRIDGE).
BITBRIDGE_ARTIFACTS = ('yabridge-host-32.exe', 'yabridge-host-32.exe.so')


def inspect(directory, expected_manifest=None):
    from .core import HostError, digest
    directory = Path(directory).expanduser().resolve(strict=True)
    try:
        with (directory / 'build.json').open('rb') as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('build manifest is too large')
        fingerprint = hashlib.sha256(raw).hexdigest()
        if expected_manifest is not None and fingerprint != expected_manifest:
            raise ValueError('build manifest changed since this library was created')
        manifest = json.loads(raw)
        files = manifest.get('files') if isinstance(manifest, dict) else None
        if not isinstance(files, dict) or set(files) not in (
                set(ARTIFACTS), set(ARTIFACTS + FORMAT_ARTIFACTS),
                set(ARTIFACTS + FORMAT_ARTIFACTS + BITBRIDGE_ARTIFACTS)):
            raise ValueError('build manifest must list the bridge artifacts')
        for name in files:
            expected = files[name]
            if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
                raise ValueError('invalid artifact hash: ' + name)
            path = directory / name
            if path.is_symlink() or not path.is_file() or digest(path) != expected:
                raise ValueError('missing, linked or changed artifact: ' + name)
        reject_host_target_flags(manifest)
        return {'directory': str(directory), 'manifest_sha256': fingerprint}
    except (OSError, ValueError) as exc:
        raise HostError('Cannot use native bridge at ' + str(directory) + ': ' + str(exc)) from exc


def reject_host_target_flags(manifest):
    """A Windows host built for anything above the x86-64 baseline is not usable.

    Built with `-march=native` on a packager's machine, the host overflows its
    stack while plug-ins initialise, and every bridged plug-in dies in the DAW
    with only a timeout to show for it (diagnostics/host-stack). The build
    script keeps such flags out; this keeps such a build out of a library.
    Manifests from before the arguments were recorded say nothing, and pass.
    """
    inputs = manifest.get('build_inputs') if isinstance(manifest, dict) else None
    arguments = inputs.get('arguments') if isinstance(inputs, dict) else None
    if not isinstance(arguments, dict):
        return
    for key, values in arguments.items():
        if not isinstance(key, str) or not key.startswith('host.') or not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, str) and value.startswith('-march='):
                raise ValueError('the Windows host was built with ' + value
                                 + '; the bridge must be built for the x86-64 baseline (see diagnostics/host-stack)')


#: What a release holds that something executes: the three files every
#: published bundle links to, the chainloader a bundle is copied from, and the
#: scanner. The release is named after these, and nothing else in it.
RELEASE_FILES = ('libyabridge-vst3.so', 'libyabridge-chainloader-vst3.so',
                 'yabridge-host.exe', 'yabridge-host.exe.so', 'plugg-scan')
#: The VST2 and CLAP files, part of a release when its build has them. They
#: are named after the VST3 ones, so a VST3-only build keeps the release name
#: it always had.
OPTIONAL_RELEASE_FILES = FORMAT_ARTIFACTS
#: Carried along for provenance and licence notice, not part of the identity.
RELEASE_NOTES = ('build.json', 'COPYING.yabridge')


def release_name(directory):
    """A release is named for the bytes it runs, so the same build is one release."""
    from .core import digest
    directory = Path(directory)
    lines = []
    for name in RELEASE_FILES:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('missing or linked bridge file: ' + name)
        lines.append(name + ' ' + digest(path))
    optional = [name for name in OPTIONAL_RELEASE_FILES if (directory / name).exists()]
    if optional and len(optional) != len(OPTIONAL_RELEASE_FILES):
        raise ValueError('incomplete VST2 and CLAP bridge files')
    # Named after the files above as well, so a build without the 32-bit
    # host keeps the release name it always had.
    bitbridge = [name for name in BITBRIDGE_ARTIFACTS if (directory / name).exists()]
    if bitbridge and (len(bitbridge) != len(BITBRIDGE_ARTIFACTS) or not optional):
        raise ValueError('incomplete 32-bit bridge files')
    for name in optional + bitbridge:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('linked bridge file: ' + name)
        lines.append(name + ' ' + digest(path))
    return hashlib.sha256('\n'.join(lines).encode()).hexdigest()[:16], dict(x.split(' ') for x in lines)


def has_bitbridge(directory):
    """Whether a bridge build or release can host 32-bit VST2 plug-ins."""
    return all((Path(directory) / name).is_file() for name in BITBRIDGE_ARTIFACTS)


def install_release(source, releases):
    """Copy a bridge build into the library, where published bundles can rely on it.

    A published bundle links its bridge files rather than copying them, so
    whatever it links to has to outlive the build it came from. A checkout
    gets moved, renamed or rebuilt in place while a DAW has the old files
    mapped; the library does not. Releases are never changed after they are
    made and never removed here: a bundle's link is the only record that
    something still needs one.
    """
    from .core import HostError, digest
    source = Path(source)
    releases = Path(releases)
    try:
        name, files = release_name(source)
    except (OSError, ValueError) as exc:
        raise HostError('Cannot use native bridge at ' + str(source) + ': ' + str(exc)) from exc
    target = releases / name
    if not target.exists():
        releases.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='.release-', dir=releases))
        try:
            for item in RELEASE_FILES + OPTIONAL_RELEASE_FILES + BITBRIDGE_ARTIFACTS + RELEASE_NOTES:
                if (source / item).is_file():
                    shutil.copy2(source / item, staging / item)
            os.chmod(staging, 0o755)
            os.rename(staging, target)
        except OSError:
            shutil.rmtree(staging, ignore_errors=True)
            # Someone else finished the same release first.
            if not target.is_dir():
                raise
    for item, expected in files.items():
        path = target / item
        if path.is_symlink() or not path.is_file() or digest(path) != expected:
            raise HostError('The library bridge release ' + str(target) + ' has been changed: ' + item)
    return target
