# Release and milestone review

Review the integrated result at each release/milestone boundary, using the
current session or an explicitly selected reviewer. Independent eyes are useful;
no external CLI, provider, different-family rule or local harness is required.
The owner may request an external reviewer for a particular release.

1. Open a release/milestone issue with the full candidate SHA, previous release
   tag/SHA, included PRs, task acceptance results, known limits and owner decisions.
   Use the current clean checkout; no worktree or extra clone is needed.
2. Review the full range and integrated learner/operator flows: pairing, all
   practice modes, interruption/retry/resume, history/provenance, progress sync,
   recording privacy and restore. Re-run reachable checks. List live provider,
   owner listening, human microphone and physical-device evidence separately.
   A fresh clone's synthetic checks cannot establish human acceptance.
3. Save a complete Markdown report to `artifacts/release-review.md`: candidate
   and base full SHAs, actual reviewer/tool/model if known, scope, commands and
   results, checks not run, findings with reproduction/file references, disposition
   and verdict (`ready`, `fixes required`, or `owner decision`). Do not invent
   serving-model identity or label a self-review independent.
4. Resolve material findings in ordinary PRs, update the candidate, and review
   the changes before release. Keep every original report. Review at a changed
   head does not inherit the earlier verdict. Nonblocking findings become issues.
5. With owner publication authorization, create the release at exactly the
   reviewed SHA and attach the report, validation summary and SHA256SUMS via
   the REST API or GitHub UI. `python3 tools/artifacts.py release TAG FILE...`
   uploads to an EXISTING release; it never creates a tag or release. Release
   asset names must be unique; existing assets are never overwritten.

Release notes link the review and state outstanding acceptance accurately.
Do not publish an accepted three-mode release until T30's human and operational
criteria are met. A code milestone is not a claim of completed phone acceptance.
Private review logs and samples belong in Drive, linked from the issue only as
appropriate; never attach learner records or secrets to a GitHub release.
