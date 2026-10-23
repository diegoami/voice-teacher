#!/usr/bin/env bash
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-false}" = true ] || exit 0
cd "${CLAUDE_PROJECT_DIR:?Claude must supply the project directory}"
bash tools/cloud_setup.sh
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  cat .cache/cloud.env >> "$CLAUDE_ENV_FILE"
fi
