#!/usr/bin/env python3
"""Run contributor checks without inheriting local recipe or library state."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--recipe-dir', type=Path, action='append', default=[])
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
directories = [str(path.resolve()) for path in args.recipe_dir]
with tempfile.TemporaryDirectory(prefix='plugg-check-') as temporary:
    env = dict(os.environ, XDG_CONFIG_HOME=temporary + '/config', XDG_DATA_HOME=temporary + '/data',
               PYTHONDONTWRITEBYTECODE='1')
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
                   cwd=root, env=env, check=True)
    command = [sys.executable, '-m', 'plugg', 'recipe', 'check']
    for directory in directories:
        command += ['--recipe-dir', directory]
    subprocess.run(command, cwd=root, env=env, check=True)
