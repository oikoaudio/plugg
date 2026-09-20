"""Exact file requirements for existing runtime and prefix components."""
import hashlib
from pathlib import Path
import re


def validate(data):
    if not isinstance(data, dict) or set(data) - {'runtime', 'prefix'}:
        raise ValueError('required_files supports runtime and prefix scopes only')
    for scope, files in data.items():
        if not isinstance(files, dict):
            raise ValueError('Required files must map relative paths to SHA-256 hashes')
        for path, fingerprint in files.items():
            if (not isinstance(path, str) or not path or path.startswith('/') or ':' in path
                    or '\\' in path or '\0' in path or any(p in ('', '.', '..') for p in path.split('/'))):
                raise ValueError('Required file path must stay beneath its scope root')
            if not isinstance(fingerprint, str) or not re.fullmatch('[0-9a-f]{64}', fingerprint):
                raise ValueError('Required file needs an exact SHA-256')
    return data


def resolve(ordered):
    merged = {}
    for record in ordered:
        for scope, files in record['data'].get('required_files', {}).items():
            for path, fingerprint in files.items():
                target = merged.setdefault(scope, {})
                if path in target and target[path] != fingerprint:
                    raise ValueError('Conflicting required file versions: ' + scope + ':' + path)
                target[path] = fingerprint
    return merged


def verify(config, requirements):
    checked = []
    for scope, files in sorted(requirements.items()):
        key = 'proton' if scope == 'runtime' else 'prefix'
        value = config.get(key)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError('Required files need a configured absolute ' + key + ' path')
        root = (Path(value).parent if scope == 'runtime' else Path(value) / 'drive_c').resolve()
        for relative, expected in sorted(files.items()):
            path = root / relative
            actual = path.resolve()
            if not actual.is_relative_to(root) or not actual.is_file():
                raise ValueError('Required component file is missing or escapes its root: ' + scope + ':' + relative)
            digest = hashlib.sha256()
            with actual.open('rb') as source:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(block)
            if digest.hexdigest() != expected:
                raise ValueError('Required component file differs: ' + scope + ':' + relative)
            checked.append({'scope': scope, 'path': relative, 'root': str(root), 'sha256': expected})
    return checked
