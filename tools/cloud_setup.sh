#!/usr/bin/env bash
# Prepare this checkout without provider keys, private data, worktrees or model CLIs.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
umask 077
mkdir -p .cache/tools artifacts/public artifacts/private
python3 - <<'PY'
import shutil, subprocess, sys
if sys.version_info < (3, 12):
    sys.exit('Python 3.12+ is required to bootstrap uv.')
for name in ('node', 'npm', 'git'):
    if not shutil.which(name): sys.exit(f'{name} is required; see docs/cloud.md')
major, minor, *_ = map(int, subprocess.check_output(['node','--version'], text=True).strip().lstrip('v').split('.'))
if major < 22 or (major == 22 and minor < 12): sys.exit('Node 22.12+ is required; Node 24 is recommended.')
PY
if [ "${VOICE_TEACHER_INSTALL_RCLONE:-1}" = 1 ]; then
  python3 tools/cloud/install_rclone.py
fi
export PATH="$PWD/.cache/tools/bin:$PATH"
# A task-owned bootstrap env avoids changing global/user installations.
if [ ! -x .cache/tools/venv/bin/uv ]; then
  python3 -m venv .cache/tools/venv
  .cache/tools/venv/bin/python -m pip install --disable-pip-version-check 'uv==0.12.18'
fi
.cache/tools/venv/bin/uv sync --locked --python "${VOICE_TEACHER_PYTHON_VERSION:-3.14}"
# Resume only reinstalls npm packages if its inputs changed or binaries are absent.
if [ ! -x apps/web/node_modules/.bin/vite ] || ! sha256sum --check --status .cache/npm-inputs.sha256 2>/dev/null; then
  npm --prefix apps/web ci
  sha256sum tools/cloud_setup.sh apps/web/package.json apps/web/package-lock.json > .cache/npm-inputs.sha256
fi
if [ "${VOICE_TEACHER_INSTALL_BROWSER:-1}" = 1 ]; then
  if [ "${VOICE_TEACHER_INSTALL_BROWSER_DEPS:-0}" = 1 ]; then
    node apps/web/node_modules/@playwright/test/cli.js install --with-deps chromium
  else
    node apps/web/node_modules/@playwright/test/cli.js install chromium
  fi
fi
# Persist only non-secret project paths. Hooks can source these on every resume.
python3 - <<'PY'
from pathlib import Path
import shlex
root=Path.cwd()
values={'VOICE_TEACHER_TEST_PYTHON':str(root/'.venv/bin/python')}
paths=str(root/".venv/bin")+":"+str(root/".cache/tools/bin")
lines=[f'export PATH={shlex.quote(paths)}:"$PATH"']
lines += [f'export {key}={shlex.quote(value)}' for key,value in values.items()]
Path('.cache/cloud.env').write_text('\n'.join(lines)+'\n')
PY
printf '%s\n' 'Ready: source .cache/cloud.env. Private files and live providers are opt-in; see docs/cloud.md.'
