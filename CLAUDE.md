# voice-teacher

Architecture and proofs of concept for a spoken-lesson engine. Read
`README.md` and `docs/architecture.md` first.

Before resuming product work, read the confirmed choices and restart order in
[docs/tasks/README.md](docs/tasks/README.md#resuming-product-work). A handover
request alone does not restart the paused task sequence.

Product tasks follow `AGENTS.md`, `docs/process.md` and their contract under
`docs/tasks/`. The main session implements in the current checkout on a branch;
no worktrees or external reviewer are required. Per-PR reviews are optional.
Release/milestone reviews cover the integrated candidate and persist with the
release. These owner choices (2026-10-23) supersede the old mandatory OpenCode,
different-family and worktree clauses in earlier contracts and runbooks.

A fresh cloud session uses [docs/cloud.md](docs/cloud.md) and
`bash tools/cloud_setup.sh`. Required private files live in the project's private
Drive folder ([docs/artifacts.md](docs/artifacts.md)); ordinary tests use only
committed synthetic fixtures. No home-directory skills, sibling checkout,
systemd service, reviewer CLI or provider key is needed for development.

## Prior live-test evidence

On 2026-10-17, T22's bounded live integration completed three scripted dialogue
turns with real providers and produced three MP3 replies. The owner listened
and reported that they sounded right. This work, including the listening
record, merged in [PR67](https://github.com/diegoami/voice-teacher/pull/67).
See [the retained evidence](docs/reference/three-mode-evals.md#resumed-check-three-accepted-turns)
and [the owner clarification](docs/tasks/T22.md#owner-acceptance-clarification-2026-10-17).
The pending full phone/microphone acceptance does not negate these completed
checks. Verify evidence before answering historical questions; do not rely
only on a carried-over conversation summary.

## Repository boundaries

- Each POC lives in `pocs/NN-name/` with its own `README.md` stating the
  question, the method, and the answer with evidence. Do not start a POC
  without writing its question down.
- Curriculum content, learner records and the current voice-teacher prompt
  stay in `diegoami/learnukrainian`; read them there, do not copy them here
  except as test fixtures under a POC directory.
- Never commit API keys, learner audio, or personal session transcripts.
  Audio and transcripts used as fixtures are git-ignored; document how to
  obtain them.
- Keep `docs/architecture.md` current: when a POC changes a decision, edit
  the document and say which POC changed it.
