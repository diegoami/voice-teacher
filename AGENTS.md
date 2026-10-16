# Agent instructions

Read [CLAUDE.md](CLAUDE.md), [docs/production-plan.md](docs/production-plan.md),
[docs/process.md](docs/process.md), and the selected task contract in
[docs/tasks/](docs/tasks/README.md) before product implementation.

- The main session implements by default. It may delegate a bounded task to a
  native subagent of the same model family. Record the actual implementer and
  family on the PR; no implementer selection question is needed unless a
  different model or family is proposed.
- One task produces one branch and GitHub PR. Product implementation uses an
  isolated worktree; planning may use a task branch in the main checkout.
- An independent OpenCode model reviews through the CLI. Choose the reviewer
  ad hoc for the PR, validate its live ID, and record model, provider, variant
  and family. The reviewer must be of a different family from the implementer.
  No fixed roster, quota-based selection or silent substitution.
- Task scope and acceptance criteria are contracts. Report a criterion that
  cannot be met; do not weaken it or silently mark it satisfied.
- Preserve curriculum, personal history and provenance. Personal session
  records, credentials and learner audio stay out of this code repository.
- Only the main session may merge, with user authorization, an approving review
  for the current head and successful required checks. Never force-push, stash
  another session's work, or delete task/review worktrees as routine cleanup.
- Follow native sandbox approvals. Instruction files do not replace technical
  permissions, and a reviewer prompt alone does not enforce read-only access.

The backlog schedules future work; creating it does not start those tasks.
