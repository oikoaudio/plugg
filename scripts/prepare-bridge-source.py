"""Verify the exact recorded patch series before changing or building vendored source."""
from pathlib import Path
import json, os, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
source = root / 'vendor/yabridge'
names = json.loads((root / 'patches/yabridge-series.json').read_text())
if not names or len(names) != len(set(names)) or any(Path(name).name != name or not name.endswith('.patch') for name in names):
    raise SystemExit('Invalid yabridge patch series')
patches = [root / 'patches' / name for name in names]
def git(*args, env=None):
    return subprocess.check_output(['git', '-C', str(source), *args], env=env)
actual = git('diff', 'HEAD', '--binary')
with tempfile.TemporaryDirectory() as temp:
    env = dict(os.environ, GIT_INDEX_FILE=str(Path(temp) / 'index'))
    git('read-tree', 'HEAD', env=env)
    states = [b'']
    for patch in patches:
        git('apply', '--cached', str(patch), env=env)
        states.append(git('diff', '--cached', '--binary', env=env))
    if actual not in states:
        raise SystemExit('Vendored changes differ from the recorded patch series; review before building.')
    applied = states.index(actual)
    for patch in patches[applied:]:
        git('apply', '--check', str(patch))
        git('apply', str(patch))
    if git('diff', 'HEAD', '--binary') != states[-1]:
        raise SystemExit('Patch series verification failed')
print('Verified bridge patch series:', ', '.join(p.name for p in patches))
