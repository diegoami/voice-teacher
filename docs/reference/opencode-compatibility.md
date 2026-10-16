# OpenCode compatibility and T01 evidence

Verified 2026-10-16 on this Linux/WSL host by the main Codex session
(OpenAI family). These observations cover T01, not product voice behavior.

## Installed interface

- Native binary: `/home/diego/.opencode/bin/opencode`; version `opencode v2.0.28`.
- Binary SHA-256: `20d305d0140bfe04df7264a4ecb014402b74b6ac0a0f6456ee07ef3325fb4a85`.
- Bubblewrap: `0.11.1`; user, PID and network namespace probes succeeded.
- Reviewed CLI flags: `run --standalone --model --agent --file --format`.
- Exact invocation inside the sandbox:

```text
/opt/opencode run --standalone --model minimax-coding-plan/MiniMax-M3 --agent reviewer --file /brief.md --format json "Review the attached brief and pinned patch. Return the complete review."
```

The user selected MiniMax for this execution sequence. The main session chose
the available direct coding-plan route `minimax-coding-plan/MiniMax-M3` from
the live catalogue; family MiniMax, no variant. No standing default is added.
The PATH's Windows shim is unsuitable for Linux paths and was not used.
`models <provider>` is unsupported in this version; use `models` and exact
membership. V2 uses different configuration fields from predecessor harnesses.
See upstream [permissions](https://dev.opencode.ai/v2/docs/permissions/),
[configuration](https://dev.opencode.ai/v2/docs/config/), and
[proxy support](https://dev.opencode.ai/v2/docs/network/).
Provider routing was also checked against the MiniMax coding-plan entry in
the [model catalogue](https://models.dev/api.json).

## Tests and enforced denials

`node --test tests/review/cli.test.mjs`: 8 passed.
`python3 tests/review/egress.test.py`: 4 passed.
Removing the same-family guard caused two tests to fail with missing expected
exceptions; restoring it returned the suite to green. The executable fake-CLI
test proves incompatible flags stop before a billed invocation.

The supervised probe produced:

```text
direct_source_write: denied
indirect_source_write: denied
trusted_policy_write: denied
github_write: denied (no authentication)
direct_network: denied
host_credentials: absent; scratch_write: allowed
```

Root candidate configuration attempted to replace the reviewer instructions
and load a throwing plugin. It was masked. `debug config` showed only trusted
system configuration and empty isolated configuration directories. The source
file remained exactly `original` plus newline. The later extended probe also
checks that a direct external connection fails in the isolated network.

## Live MiniMax smoke

- Session: `ses_ebb3a3debffe4iIzYqEmkUbMK7`.
- Platform session record: agent `reviewer`, provider `minimax-coding-plan`,
  model `MiniMax-M3`, idle outcome `succeeded`.
- Trusted policy SHA-256:
  `6a6b481d81b6257026b5f297150184c98891ca9b40e5c4cfdfa1b399fd41b11e`.
- Model reported the system trust marker `voice-teacher-review-policy-v1`.
- Its shell overwrite and append failed with `Read-only file system`;
  Python subprocess overwrite and append failed with `OSError: [Errno 30]`.
- Its `gh auth status` returned no authenticated hosts; outbound GitHub access
  failed with `CONNECT tunnel failed, response 403`.
- The separate supervised GitHub POST probe failed before authentication;
  it targeted a nonexistent probe repository and created nothing.

The model's output explicitly limits its result to the synthetic smoke test;
it is **not approval of a PR**. Full JSONL and platform records are retained
outside the repository at `/tmp/voice-teacher-T01-bootstrap/`. Main-session
verification checked actual tool outputs and the platform session metadata,
rather than relying on the model's summary. The PR review is a separate job
at a recorded commit in an independent Git clone and a fresh runtime.

## Diagnosed failures and limitations

Initial sandbox diagnostics failed because OpenCode requires its isolated home
to exist. Adding that directory resolved it. The next attempt collided with a
host service's default port; isolating the network namespace removed both the
collision and access to host services. Those failed runs were not accepted as
successful smoke tests. Later failures retain distinct diagnostic files.

The first PR-review job at `72ce17c2458669a912c7802a624d02377d939600`
(session `ses_ebb34f52affeZ0PC3f5mzdT7O0`) exited zero with an empty final
assistant message after tool use. It is incomplete and supplies no approval.
That run also exposed the absence of Node under `/usr`: this host installs
Node under NVM. The adapter now mounts only the selected Node executable at
`/opt/node`, without granting access to the host home. Successful output now
redacts the selected provider key as well as failure diagnostics; a dedicated
test covers both paths. Raw platform records remain private and require
inspection before publication. The corrected offline suites were also run
inside the actual namespace, not just on the host.

The [adapter runbook](../../tools/review/README.md) records setup, enforced
boundaries and resource/provider-credential limitations. This version does
not yet implement T02's watched lifecycle, verdict validation or publication.

## Predecessor provenance

Inspected `goal2/tools/harness/lib/jail.mjs` and `lib/opencode.mjs` at
`724cf4f44fae65dd0144605f57a7492828dddcff` (latest change to these files),
within checkout `fd6d44618cdae7037391fcb3db35c63b818b18f8`, and the
`harness_imperial` reviewer-agent pattern referenced in the planning baseline.
They supplied design lessons: close stdin, bind reviews to commits, avoid the
Windows shim, preserve incomplete runs and keep publishing credentials away
from the reviewer. Their older flag/permission shapes and mistakes-only jail
were unsuitable for this contract. No source code was copied. No tracked
license file was found in the inspected goal2 checkout; no reuse permission
is inferred. This adapter and boundary implementation are new code.
