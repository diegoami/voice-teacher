# Task and release process

Owner direction, 2026-10-23: use the cloud-compatible workflow adopted recently
by [malpaco](https://github.com/diegoami/malpaco/blob/493ab8240001/CLAUDE.md)
and [goal2](https://github.com/diegoami/goal2/blob/a83951082453/CLAUDE.md).
This replaces mandatory worktrees, external OpenCode review and family gates.
Historical task contracts and legacy review reports keep their original evidence;
these workflow clauses supersede their old role/merge requirements. Product
scope, numbered acceptance criteria and human acceptance gates do not change.

## Setup and scheduling

Read CLAUDE.md, the production plan, this process and the task contract. Follow
[cloud setup](cloud.md); a fresh checkout can run the synthetic suite without
private data or provider credentials. GitHub issues and labels hold live status.
Check dependencies and open PRs before starting; do not repeat merged work.

Use GitHub REST (`gh api`) or connected GitHub tools. Claude cloud's GitHub proxy
blocks GraphQL; `gh pr` and `gh issue` may fail even with working authentication.
Do not replace proxy credentials merely because a placeholder is visible.

## One checkout, branches and PRs

The main session implements directly or delegates a bounded native subtask in
this checkout with disjoint file ownership. No new worktrees or extra clones.
Preserve existing worktrees and evidence; this workflow change does not delete
them. Never stash, force-push, rewrite main or discard somebody else's changes.

Locally, use `task/Tnn-description` from current main. In a cloud session keep
the assigned session branch (often `claude/...`). One task and one PR at a time.
Commit and push task work regularly; resumable facts belong in the PR/issue,
not solely in a temporary directory. When a session ends with an open PR, the
next session inspects and continues it rather than starting a duplicate.

For each change, reproduce the defect or show a meaningful regression fails
without it; run affected checks and the available baseline. Explain changes,
checks, actual implementer, limitations and each Done-when result in the PR.
Documentation changes need link/contract checks rather than invented app tests.
Never replace human listening, real microphone or physical-phone checks with
synthetic tests, and never infer that pending phone checks erase earlier live runs.

Per-PR reviews are optional. The main session can review its diff; an external
review is useful when requested or warranted by risk. Any available model/tool
may review; no mandatory provider, model family, CLI, OS package or roster.
Record the actual reviewer and exact reviewed head when a review happens;
resolve material findings and relay the report in full. A failed optional tool
run is recorded accurately and does not become approval or block unrelated work.
Legacy tools under tools/review remain opt-in historical tooling with their
own permissions and runtime prerequisites, not the default cloud workflow.

## Validation and merge

Run affected Python checks (`uv run --locked pytest <paths> -q`), and, for web
changes, build, unit and relevant browser tests. CI supplies backend and web
checks. Check the PR's exact head, check-runs AND commit statuses; pending,
failed or missing expected checks are not green. A docs-only task has the
workflow validation check; product changes also require the relevant suites.
A criterion not performed is marked pending with a reason, never silently waived.

Only the main session merges, with owner authorization and satisfied contract
and required checks. This workflow change alone does not authorize merging
existing PRs, publishing a release or starting the whole backlog. Use a
head-bound REST merge:

```bash
# Replace N and SHA with the actual PR and full checked head.
gh api --method PUT repos/diegoami/voice-teacher/pulls/N/merge \
  -f merge_method=merge -f sha=SHA
```

Cloud session branches use merge commits rather than squash: after a confirmed
merge, `git pull --ff-only origin main` on that same branch incorporates main
without rewriting history and prepares it for the next task. If it cannot fast
forward, inspect the divergence; do not force/reset. Local task PRs can squash.
Never delete branches or old worktrees as a side effect of merge.

REST references (use structured JSON files with `--input` for multiline bodies):

| Operation | Endpoint |
| --- | --- |
| Open PRs | `GET repos/diegoami/voice-teacher/pulls?state=open` |
| Issue and comments | `GET repos/diegoami/voice-teacher/issues/N[/comments]` |
| Create PR | `POST repos/diegoami/voice-teacher/pulls` |
| Head/checks/status | `GET repos/diegoami/voice-teacher/pulls/N`, `commits/SHA/check-runs`, `commits/SHA/status` |
| Comment | `POST repos/diegoami/voice-teacher/issues/N/comments` |
| Merge | `PUT repos/diegoami/voice-teacher/pulls/N/merge` with `sha` |

## Releases and durable evidence

[Release review](release-review.md) examines the integrated candidate, task
coverage, real-user flows and privacy/recovery risks. Keep the report, checks,
SHA and disposition of findings as release assets and link them from the release.
No fixed external reviewer is a prerequisite for daily task merges.

Generated outputs go in ignored `artifacts/`. Public/synthetic review reports,
checks and builds may go to GitHub releases; private input, audio, history,
operator configuration and credentials never do. Required private files and
private evidence go to the private Drive folder via [artifact storage](artifacts.md).
No required artifact may survive only under /tmp or on a developer machine.
