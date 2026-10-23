# Supplemental reviews with agy

> Historical, optional local tooling. Since the owner's 2026-10-23 cloud-workflow
> change, this is not a required review/merge gate. Its own safety boundaries
> still apply when explicitly invoked. Current process: [docs/process.md](../process.md).


T34 adds an opt-in static second opinion through the authenticated Antigravity
CLI. The owner requested Sonnet; the trial used `claude-sonnet-5-5-medium` from
the live `agy models` catalogue. Provider route: Antigravity; requested underlying
family: Anthropic; variant: medium. The implementer is main Codex, OpenAI family.

This path never creates merge approval. Existing OpenCode review, current-head
approval, required checks and main-session authorized merge remain mandatory.
A successful CLI envelope and a requested model ID do not establish native
underlying-model attestation. Full alternative reviewer eligibility is future
work and must be separately validated before changing the gate.

## Run a static second opinion

Use accepted tooling outside candidate-controlled code. Authenticate interactively
with `agy` first. Select the model explicitly; this first adapter supports Sonnet
IDs and rejects same-family implementers, absent models and fallback selection.
The [official headless reference](https://antigravity.google/docs/cli/headless/)
describes cached authentication, JSON/structured output and explicit model IDs.
Installed `agy --help` and the live catalogue are also checked before invocation.

Create a private operator spec, containing paths and public task identities only:

```json
{
  "task": "T33",
  "source": "/absolute/trusted/code-checkout",
  "base": "05610a1630e3cf61cba833764989171f96db2811",
  "head": "140889a88ddb471944864477e02a731aeceb15ec",
  "artifacts": "/tmp/unique-private-agy-review",
  "model": "claude-sonnet-5-5-medium",
  "implementerFamily": "openai"
}
```

```bash
node tools/review/agy.mjs prepare /private/operator-spec.json
node tools/review/agy.mjs run /tmp/unique-private-agy-review \
  ~/.local/bin/agy ~/.gemini/antigravity-cli/antigravity-oauth-token
```

Native sandbox permission is required for the owned broker/namespace. The helper
reads only the selected OAuth credential file into a new private runtime; it does
not copy account conversations, settings, plugins or the host home. Specs never
contain credential values. Artifacts are rejected inside Git checkouts, including aliases through symlinked
parents. The selected CLI and credential must also be outside Git checkouts and
outside the source/artifact directories.
The packet contains committed changed text files, task and full patch; uncommitted
work and Git metadata are excluded. The helper verifies packet hashes before and
after execution. Symlink entries and oversized prompts are refused.

The invocation closes stdin, uses `--sandbox`, disables slash-command expansion,
pins the model, requests schema output and bounds print time to 240 seconds with
an outer 300-second process limit and 4 MiB per-stream output cap. It does not use permission
bypass or candidate shell execution. A separate authenticated catalogue call is
bounded to 60 seconds. Failure retains diagnostics and refuses runtime reuse.

## Enforced boundaries and limits

The accepted Linux bwrap boundary mounts the packet read-only, hides host home,
GitHub authentication and unrelated credentials, and creates an isolated PID and
network namespace. Only the observed provider/login hosts may use the CONNECT
broker: `daily-cloudcode-pa.googleapis.com`, `oauth2.googleapis.com`,
`www.googleapis.com`, and `lh3.googleusercontent.com`, all port 443. Account
eligibility initialization requires userinfo and a profile image, even in print
mode. Arbitrary web, local services and GitHub are denied. The broker exits after
its parent disappears. Existing MiniMax egress policy is unchanged.

A fresh agy policy permits packet reads and denies file writes, shell commands,
permission escape, MCP and web tools. This is additional protection; agy's
terminal sandbox alone does not enforce read-only file tools. The
[permission reference](https://antigravity.google/docs/permissions/) documents
default workspace writes and the action-specific allow/deny rules.

A successful supplemental result always has `eligible:false` and
`modelIdentityVerified:false`. Reports must name the exact base/head and disclose
tests not run. Inspect all findings and limitations before sharing. Do not print
account initialization logs: they can contain private account URLs. Diagnostics
are private and selected credential strings are redacted. Original CLI JSON,
response, invocation, binary hash, catalogue and process status are retained.

The observed CLI can add `toolAction` and `toolSummary` display strings to the
free-text `response` while returning a clean `structured_output`. The adapter
uses the documented structured result only when it agrees exactly with the raw
response apart from these two strings. It never rewrites the original response.
Mismatches, malformed findings, failures and missing test disclosures fail closed.

## Trial on T33 / PR71 (2026-10-17)

The successful corrected adapter run requested `claude-sonnet-5-5-medium` and
returned `SUCCESS`, one turn, conversation
`b518e7c4-9b88-45e2-807e-2be541fbc91a`, 36.56 seconds, 40846 input tokens and 4311
output tokens (provider-reported usage; no cost claim). The native language-server
log identifies 1.4.0; binary SHA256:
`60e72242f07c131f75afcd9a9e425d6ee097a1a1b3190ea98ae78fa4180bbfa8`.
The requested model was present in the live catalogue. Underlying model identity
is not independently attested. T33's original MiniMax approval remains its gate.

The [original Sonnet response](agy-sonnet-T33.json) is preserved unchanged.
Main-session reconciliation:

- The pending-choice recovery gap is actionable: permanent non-409 rejection
  retains the local journal and disables every completion/reopen button, with no
  discard control. Source inspection confirms this; browser reproduction and
  the fix remain incomplete in [issue #73](https://github.com/diegoami/voice-teacher/issues/73).
- The broken-checkout explanation is unsupported. `SourceRegistry.active` reads
  a persisted validated snapshot from SQLite, not the checkout filesystem.
  Extra per-request catalogue reads are real; no performance failure was proved.
- New content hashes intentionally use separate streams, as T33's pinned-identity
  contract, documentation and isolation tests require. Automatic inheritance
  would need an explicit product decision. The UI could explain historical
  versus active revisions better; this is not a demonstrated contract failure.

Sonnet did not run tests, inspect every unchanged dependency or perform real-phone
acceptance. The report lists those limits. No task criterion becomes independently
verified merely from the main implementer's earlier test results.

The first attempt stopped at help handling; the next two stopped during account
initialization with zero model turns. The first actual Sonnet response succeeded,
but the adapter rejected its display metadata. That failed result and original
response remain unchanged; an offline validation is separately labelled. A fresh
final run verified the corrected adapter end to end. No failed attempt was
converted into approval. Native boundary probes confirmed write denial, absent
host home/GitHub credentials, denied GitHub CONNECT and writable scratch.

## Checks

```bash
node --test tests/review/agy.test.mjs
node --test tests/review/*.test.mjs
python3 tests/review/egress.test.py
```

Real deployed-phone, microphone and unscripted human acceptance remain incomplete
under T19/T30. This static review does not satisfy them. Full native model
attestation, candidate test execution and merge eligibility are not established.
