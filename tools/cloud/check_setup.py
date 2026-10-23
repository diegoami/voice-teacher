#!/usr/bin/env python3
"""Offline smoke for the prepared development environment (no private/live calls)."""
import importlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[2]
for name in ('voice_teacher','fastapi','httpx2','jsonschema','pytest'):
    importlib.import_module(name)
assert shutil.which('node') and shutil.which('git')
assert (ROOT/'apps/web/node_modules/.bin/vite').exists()
assert (ROOT/'apps/web/dist/index.html').exists(), 'Build web assets first'
json.loads((ROOT/'.claude/settings.json').read_text())
subprocess.run(['node','--version'],check=True)
print('Cloud development smoke passed; no provider key, private input or reviewer CLI used.')
