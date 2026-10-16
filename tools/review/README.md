# Supervised OpenCode adapter

T01 establishes the CLI and OS boundary. T02 will add watched execution,
structured verdict validation, exact-head publication and GitHub integration.
`smoke.mjs` deliberately does not approve, publish or merge a PR.

Supported: Linux, bubblewrap with working unprivileged user/network/PID
namespaces, Python 3, Node, socat and OpenCode **2.0.28**. Other CLI versions
fail closed pending a compatibility check. Run:

```bash
node --test tests/review/cli.test.mjs
python3 tests/review/egress.test.py
```

The model is a required input, never a fallback. Family recognition supports
OpenAI, Anthropic, Google and MiniMax naming conventions; unknown names fail.
The CLI catalogue must contain the exact provider/model. Variants are refused
until separately verified. The implementer family is also explicit. The live
provider-only egress path currently supports MiniMax; other providers require
a reviewed broker change, even if their family is recognized.

## Trusted preparation

The main session prepares a new private run directory outside every candidate
checkout. Copy the verified `cli.mjs`, `sandbox.mjs`, `smoke.mjs`, `egress.py`
and `policy.json` there from an accepted revision. For the bootstrap, inspect
these files and test the boundary directly before using them. Record their
commit/hash; do not execute the candidate's copy of the adapter or policy.

Create an independent Git clone, with its own `.git` directory, at the pinned
PR head and containing the base commit. Do not pass a linked worktree whose
`.git` points outside the namespace. Disable Git hooks during preparation and
use `--no-local` when cloning from a local path so objects are independent.
Verify the base/head and clean checkout before dispatch. T02 automates this.

Create a fresh empty `runtime` directory outside the clone and trusted files.
Never reuse a runtime after a model job for a different review: it contains
writable process state. The brief is a trusted external file containing the
task, base/head, full diff or diff instructions, and verification evidence.
Candidate configuration remains available for review in the Git diff even
though executable configuration is masked at its filesystem paths.

A JSON spec contains only operator-verified absolute paths and identities:

```json
{
  "workspace": "/tmp/private-review/candidate",
  "runtime": "/tmp/private-review/runtime",
  "binary": "/home/diego/.opencode/bin/opencode",
  "policy": "/tmp/private-review/trusted/policy.json",
  "brief": "/tmp/private-review/brief.md",
  "proxySocket": "/tmp/private-review/egress.sock",
  "model": "minimax-coding-plan/MiniMax-M3",
  "implementerFamily": "openai"
}
```

Use a newly created run directory with mode 0700. Start the trusted broker
outside the review namespace, retaining its process identity:

```bash
python3 /tmp/private-review/trusted/egress.py /tmp/private-review/egress.sock
```

In another supervised shell, with the existing `MINIMAX_API_KEY` available
through the environment, run the trusted adapter. Never put a key in a spec,
brief, command argument or committed artifact:

```bash
node /tmp/private-review/trusted/smoke.mjs config /tmp/private-review/spec.json
node /tmp/private-review/trusted/smoke.mjs preflight /tmp/private-review/spec.json
node /tmp/private-review/trusted/smoke.mjs review /tmp/private-review/spec.json
```

Confirm `debug config` lists the trusted `/etc/opencode/opencode.json`, with
the expected reviewer system instructions and permissions, and no candidate
configuration. Confirm the recorded session agent/model match the request.
On this CLI, `debug agents` alone did not show the effective configured agent;
the successful session record and configuration source are the evidence.
The brief is always mapped to `/brief.md`, regardless of its host path.

`probe` is a separate non-billed check. Its synthetic candidate must contain
`probe-target.txt` holding `original` and a newline. Seed an attempted policy
override/plugin in `opencode.json` and `.opencode/`; verify the plugin does
not run and the trusted policy remains loaded. Then run `probe`, inspect its
denials and the unchanged target, and run a live model smoke brief asking
for direct/subprocess writes and GitHub-auth checks. See the
[compatibility evidence](../../docs/reference/opencode-compatibility.md).

Retain stdout JSONL, unique failure diagnostics and runtime session records
in the private run directory. Inspect/redact before publishing. Failure
diagnostics replace the selected key with `[REDACTED]`; this is not a general
secret scanner. Stop only the broker process belonging to this run afterward;
preserve review evidence. An exit of zero is not an approving review.

## Enforced boundary and limits

Bubblewrap starts with an empty filesystem view and isolated user, PID,
network, IPC and UTS namespaces. Only system tools/libraries, minimal DNS/TLS
files, the read-only candidate, trusted binary/config/brief and one fresh
writable runtime are mounted. Temporary output goes in a private `/scratch`.
No host home, `/run`, Windows mount, SSH agent, GitHub configuration or tokens
enter. Host environment inheritance is replaced with an explicit allowlist;
only the selected MiniMax credential is passed, through environment rather
than arguments. No authentication databases are copied.

Executable root project configs and `.opencode`, `.agents`, `.claude` are
masked; config symlinks are refused. Native V2 permissions deny all actions
except read/glob/grep/shell/external-directory access. Source writes through
shells, scripts and indirect tools are blocked by the read-only mount.
Scratch/runtime writes are permitted. Managed policy is mounted read-only
outside the candidate; shell-text deny lists are not the boundary.

The isolated network reaches only its own loopback and the Unix broker.
The broker permits HTTPS CONNECT to `api.minimax.io:443` and
`models.dev:443`, rejects private resolved addresses, and provides no general
HTTP proxy. A socat relay exposes it on the namespace's loopback. Direct
network connections, GitHub and host services are unavailable. The broker
does not log payloads or read credentials. TLS remains end to end.

This is not a VM or a resource-exhaustion sandbox: tools share the host
kernel and mounted system binaries; CPU/memory cgroups are not configured.
The reviewer can see its selected provider credential and use that provider.
Do not use with unrelated secrets in the candidate or runtime. Arbitrary
test prerequisites are not installed or fetched automatically; report checks
that need more tools or external services as unverified. Missing namespaces,
mount failures or broker failures never trigger an unsandboxed retry.

The supervised adapter closes stdin, bounds individual checks and caps a
model invocation at ten minutes. It retains failures, but it is not T02's
startup/idle watcher, parser or publisher. If execution fails, diagnose it;
do not silently switch providers, versions or models.
