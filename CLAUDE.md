# voice-teacher

Architecture and proofs of concept for a spoken-lesson engine. Read
`README.md` and `docs/architecture.md` first.

Before resuming product work, read the confirmed choices and restart order in
[docs/tasks/README.md](docs/tasks/README.md#resuming-product-work). A handover
request alone does not restart the paused task sequence.

Product tasks follow `AGENTS.md`, `docs/process.md` and their contract under
`docs/tasks/`. The main session or its native same-family subagent implements;
an independently chosen OpenCode model reviews the resulting GitHub PR.

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
