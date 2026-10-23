# Agent instructions

Read [CLAUDE.md](CLAUDE.md), [docs/production-plan.md](docs/production-plan.md),
[docs/process.md](docs/process.md), and the selected task contract in
[docs/tasks/](docs/tasks/README.md) before product implementation.

- The main session implements directly, or delegates a bounded task to a native
  subagent when useful. Record the actual implementer on the PR.
- Use one checkout and a branch, one task and PR at a time. No new worktrees or
  extra implementation/review clones. In cloud sessions retain the assigned
  session branch; see [the process](docs/process.md) for sequential PRs.
- Per-PR external reviews are optional; no reviewer CLI, model family or local
  harness is required. Review the integrated candidate at release/milestone
  boundaries, record the exact SHA and preserve the review in release assets.
  Resolve material findings before release. See [release reviews](docs/release-review.md).
- Task scope and acceptance criteria are contracts. Report a criterion that
  cannot be met; do not weaken it or silently mark it satisfied.
- Everything required for development is in Git or the project's private Google
  Drive folder. Required private files never depend solely on this machine.
  Use [cloud setup](docs/cloud.md) and [artifact storage](docs/artifacts.md).
  Credentials belong in environment secrets, never in Git or review assets.
- Preserve curriculum, personal history and provenance. Personal session
  records, credentials and learner audio stay out of this code repository and
  GitHub release assets, even when the repository is private.
- Only the main session merges, with user authorization, completed task checks
  and successful required CI. Answer any review findings that were raised.
  Never force-push, stash another session's work, or delete existing task/review
  worktrees as routine cleanup.
- Follow native sandbox approvals. Instruction files do not replace technical
  permissions. Optional legacy agy reviews retain their OS read-only boundary
  and explicit model selection; they are never required for merge.

The backlog schedules future work; creating it does not start those tasks.

## Recalling prior work

Before answering questions about prior sessions, tests, acceptance or merges,
verify the relevant task notes and Git history across branches/worktrees. Check
live GitHub PR status before reporting current merge status. Conversation
summaries are pointers, not complete evidence; if evidence is missing, say
"not verified" rather than claiming an activity never happened.

Report automated tests, live provider runs, owner listening checks, human
microphone conversations and physical-phone acceptance separately. A pending
phone gate does not mean that no live session or listening check occurred.
Start with the T22/PR67 reminder in CLAUDE.md when recalling voice tests.
