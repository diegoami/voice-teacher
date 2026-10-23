# Claude cloud environment

Owner migration, 2026-10-23. This configures development sessions, not the
always-on practice server or T28's stable phone HTTPS origin. The existing
T22 live integration and owner listening remain recorded in CLAUDE.md.

## Environment to create in Claude

At [claude.ai/code](https://claude.ai/code), before sending the first message,
open the environment selector under the composer → New environment. Use:

| Field | Value |
| --- | --- |
| Name | `voice-teacher` |
| Repository | `diegoami/voice-teacher` (attach it to the session/project) |
| Network | Custom; include the default common package-manager list |
| Allowed domains | Contents of `tools/cloud/allowed-domains.txt`, one per line |
| Environment variables | Contents of `tools/cloud/environment.env.example` |
| Setup script | Leave empty (or use `true`); project setup runs from SessionStart after checkout |

Do not put `bash tools/cloud_setup.sh` in the environment's early setup field:
that field may run where repository files are not yet available. This produced
exit 127 (`No such file or directory`) in the owner's first environment test.
The committed SessionStart hook resolves the actual checkout through
`CLAUDE_PROJECT_DIR` and runs project setup there. Select a branch containing
these hooks (the T38 branch until merged).

Save it and select it for this repository. The settings are account-side;
committing these files does not create an environment in Claude. Verify the
selected environment in a fresh cloud session rather than claiming success
from a local bootstrap. To select an existing environment for CLI cloud runs,
use `/remote-env`; that command does not create/edit environments.

The project setup installs rclone when absent, creates `.venv`, installs locked Python/web dependencies and Chromium,
and writes non-secret `.cache/cloud.env`. Node 24 and Python 3.14 match CI;
Python 3.12+ can bootstrap uv, which installs the selected Python. Node must
already be 22.12+ (24 recommended). Git, Python with venv/pip, npm and Node must
be on PATH. `gh` is needed for GitHub operations, rclone only for private Drive
transfers (setup installs a checksum-verified pinned binary without root). No OpenCode, Gemini/Agy CLI, systemd, bubblewrap, home skills or
sibling checkout is needed.

The committed SessionStart hook repeats the idempotent setup for remote
startup/resume and adds project paths to `CLAUDE_ENV_FILE`. Locally it exits
without changing the environment. In project threads or multi-repository
sessions where repository hooks are not loaded, ask Claude to run setup and
source cloud.env explicitly after checkout. Do not move a repository-relative
command back into the early environment setup field. Do not put secrets into a setup script or cached filesystem image.

## GitHub access

Prefer Claude's GitHub App/proxy connection; attach this repository and verify
`gh api repos/diegoami/voice-teacher --jq .full_name`. Use REST (`gh api`), not
GraphQL-based `gh pr` / `gh issue`. A proxy-injected token is not a missing
credential. If account access genuinely is absent, authorize the GitHub App;
only use a repository-scoped token if that connection requires one. Do not
copy local gh or SSH credentials into the checkout or setup script.

The normal loop uses the session's assigned branch; do not create worktrees.
Cloud PRs use a head-bound REST merge commit and fast-forward the session branch
after authorized merge. See [process](process.md).

## Network and optional secrets

Development needs package registries, Python distributions from GitHub and
Chromium downloads; the custom list supplies GitHub asset/CDN endpoints in
addition to Claude's default list. GitHub API operations may take the separate
GitHub proxy route. Respect injected proxy/CA settings; never disable TLS to
work around an allowlist failure.

The list also permits Google OAuth, Drive API and Drive downloads so optional
private files can be restored. Enable the Google Drive connector in Claude for
manual fetch/upload, or use rclone and provide these environment secrets:

- `VOICE_TEACHER_RCLONE_TOKEN`: complete OAuth token JSON including refresh_token.
- `RCLONE_DRIVE_CLIENT_ID` and `RCLONE_DRIVE_CLIENT_SECRET`: when the token uses
  your own OAuth client. Store as environment secrets, never in Git, logs or
  Drive archives. The artifact helper injects tokens through the child environment,
  without writing a config file or putting them in process arguments.

No provider keys are required for development/tests. The allowlist includes
`openrouter.ai` and `api.elevenlabs.io` for configured live operations; network
access alone does not start or authorize paid calls. For an explicitly
authorized live check, supply `OPENROUTER_API_KEY`, `ELEVENLABS_API_KEY`,
`VOICE_TEACHER_OPERATOR_TOKEN` plus an explicitly selected `TEACHER_MODEL`.
Optional dialogue/feedback selection uses `VOICE_TEACHER_DIALOGUE_MODEL`,
`VOICE_TEACHER_FEEDBACK_MODEL`, `VOICE_TEACHER_FREE_REASONING_EFFORT` and
`VOICE_TEACHER_DIALOGUE_REPLY_TOKENS`. Do not auto-start a server or paid probe.
The prior T22 six-turn authorization is consumed; setup does not renew it.
An authenticated proxy secret is only suitable if the client supports that
proxy/header scheme; this app's current adapters require explicit key inputs.

## Verify a new session

```bash
bash tools/cloud_setup.sh
source .cache/cloud.env
uv run --locked pytest -q
npm --prefix apps/web run build
npm --prefix apps/web test -- --run
python tools/cloud/check_setup.py
npm --prefix apps/web run test:e2e -- --workers=2
python tools/artifacts.py where
```

If Chromium lacks system libraries, provision them once in the Ubuntu VM with
`node apps/web/node_modules/@playwright/test/cli.js install-deps chromium`
(root/sudo), or set `VOICE_TEACHER_INSTALL_BROWSER_DEPS=1` for setup. Keep an
install failure visible; do not mark skipped browser checks passed. To skip
browser installation for a backend-only run set `VOICE_TEACHER_INSTALL_BROWSER=0`.

A local/fresh-directory run proves portability, not that the account-side
Claude environment was saved. Record the first real cloud run separately.
Private runtime operations may reject a data directory inside a Git checkout.
Use an explicitly selected private directory outside the checkout for those
operations; `.cache/private/` is a download staging area, not the live server
store. Upload approved private outputs before the ephemeral session ends.

The cloud browser is headless Chromium with Android emulation; actual phone
microphone, permission persistence and human conversation gates stay separate.

Configuration reference: [Anthropic cloud environments](https://code.claude.com/docs/en/cloud-environments).

For local authorization and transferring the working login into Claude, follow
[the rclone setup guide](rclone.md). Never paste OAuth credentials into chat.

## Recorded cloud verification

The owner relayed a successful actual Claude cloud run on 2026-10-23: all ten
development checks passed, including Drive download/hash, build, nine tooling
tests, five web unit tests and sixteen catalogue browser checks. See the
[acceptance record](acceptance/cloud-development.md) for provenance, exact scope
and remaining checks. The report did not include a tested SHA/session URL or an
automatic cloud hook trace; those are not inferred.
