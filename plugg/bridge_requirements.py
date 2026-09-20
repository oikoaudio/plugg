"""Verify required bridge fixes against actual per-module publication links."""
import hashlib
import json
from pathlib import Path

ARTIFACTS = ('libyabridge-vst3.so', 'yabridge-host.exe', 'yabridge-host.exe.so')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(environment, requirements):
    try:
        return _verify(environment, requirements)
    except (OSError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError('Cannot verify recorded bridge deployment: ' + str(exc)) from exc


def _verify(environment, requirements):
    if not requirements:
        return []
    environment = Path(environment)
    drive = (environment / 'prefix/drive_c').resolve()
    record = environment / 'bridge-deployment.json'
    if not record.is_file():
        raise ValueError('Bridge requirements need a recorded deployment for this environment')
    deployment = json.loads(record.read_text())
    publications = [Path(item['publication']) for item in deployment.get('plugins', [])]
    checked = []
    for relative, hashes in sorted(requirements.items()):
        module = drive / relative
        target = module.resolve()
        if not target.exists():
            raise ValueError('Required bridge module is not installed: ' + relative)
        if not target.is_relative_to(drive):
            raise ValueError('Required module escapes its environment: ' + relative)
        matches = []
        for publication in publications:
            windows = publication / 'Contents/x86_64-win'
            if not windows.is_dir():
                continue
            actual = [path.resolve() for path in windows.iterdir()]
            if target in actual or (target.is_dir() and any(path.is_relative_to(target) for path in actual)):
                matches.append(publication)
        if len(matches) != 1:
            raise ValueError('Need exactly one recorded publication for required module: ' + relative)
        publication = matches[0]
        native = publication / 'Contents/x86_64-linux'
        if not (native / '.plugg-managed').is_file():
            raise ValueError('Publication is not marked as managed: ' + relative)
        release = (native / ARTIFACTS[0]).resolve().parent
        manifest_path = release / 'build.json'
        manifest = json.loads(manifest_path.read_text())
        applied = set(manifest.get('patches', {}).values())
        if not set(hashes).issubset(applied):
            raise ValueError('Required bridge patch is missing for ' + relative)
        verified = {}
        for name in ARTIFACTS:
            artifact = native / name
            if artifact.resolve().parent != release or digest(artifact) != manifest['files'].get(name):
                raise ValueError('Bridge artifact does not match its build record: ' + relative + ': ' + name)
            verified[name] = manifest['files'][name]
        proxy = native / (publication.stem + '.so')
        if digest(proxy) != manifest['files'].get('libyabridge-chainloader-vst3.so'):
            raise ValueError('Bridge chainloader does not match its build record: ' + relative)
        verified['libyabridge-chainloader-vst3.so'] = digest(proxy)
        checked.append({'module': relative, 'publication': str(publication), 'release': str(release),
                        'manifest_sha256': digest(manifest_path), 'files': verified,
                        'required_patches': sorted(hashes)})
    return checked
