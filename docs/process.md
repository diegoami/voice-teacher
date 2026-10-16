# Task and review process

The main session owns planning and integration. It implements directly or
assigns one bounded task to a native subagent of the same family. The
implementer opens a GitHub PR. An independent model, selected ad hoc and run
with the OpenCode CLI, reviews that PR at a recorded commit.

This adopts task contracts, isolated worktrees and commit-bound review from
[goal2](https://github.com/diegoami/goal2/blob/b3e1b672942108a26e9b3c5640d667968440ef51/docs/process.md),
[malpaco](https://github.com/diegoami/malpaco/blob/a5b7ad3e7e80aeed021376cb43f3ff3af0f1e3fc/docs/process.md)
and [harness_imperial](https://github.com/diegoami/harness_imperial/tree/b00831b8f808f48e98659c750824fe75b9ff1bb7).
It simplifies their model selection: the current session is the default
implementer, same-family native delegation is allowed, and the user chooses
the OpenCode reviewer when a concrete PR is ready. Those reference projects'
quota policies, model rosters, game-specific rules and direct-to-main task
edits are not adopted here.

## Task contracts and scheduling

The [backlog](tasks/README.md) defines execution dependencies, milestone gates
and one contract per task. Task files contain scope, owned paths, numbered
acceptance criteria, verification commands, hazards and roles. GitHub issues
link to those contracts; issue labels carry live status. The index contains
dependencies and issue links, not a second status board.

Statuses are `status:backlog`, `status:ready`, `status:in-progress`,
`status:in-review`, `status:rework`, `status:approved`, `status:blocked`,
and `status:merged`. Issues also carry `task` and a milestone label. A completed
task is closed by its merged PR. An unsuccessful review never closes the issue.
`blocked` names a concrete blocker; ordinary dependency waiting stays in backlog.

Before dispatch, the main session checks dependencies are merged, resolves
required product choices, and confirms the task remains one coherent PR. Split
work that crosses independently useful layers or cannot fit a bounded run.
Acceptance commands naming future files are specifications, not checks already
present or claims of readiness. Resolve paths against the merged project
layout at preflight; record necessary contract amendments in a separate planning
commit with reasons. Product choices that remain open do not block unrelated work.

Run the available baseline. For changed behaviour, reproduce the defect or
prove the new regression test fails without the change. A new feature test
should fail for the missing behaviour, not merely a missing executable. Existing
invariants must continue to pass. Documentation-only work uses link, contract
and dependency checks; it does not require invented runtime tests. Human phone
checks are marked explicitly and cannot be replaced by mocked browser tests.

The current bootstrap PR establishes the contracts. T01 and T02 then establish
the executable review tooling. These two tasks may use a supervised direct CLI
review with verified trusted permissions and a recorded head until the runner
is independently accepted; do not approve the runner using only its own output.

T01's [supervised adapter](../tools/review/README.md) and
[compatibility evidence](reference/opencode-compatibility.md) provide the
verified Linux CLI/policy boundary. Until T02 lands, the main session prepares
the pinned independent review clone, supervises the job, checks the complete
result and platform identity, and publishes it separately. The adapter itself
does not decide approval or write to GitHub. Use a fresh runtime per review.

## Implementer contract

1. Record task ID, issue, actual implementer/session or subagent, model family,
   base SHA and branch. The main session prepares isolated worktrees for native
   subagents and passes the full task and this contract, not just a path.
2. Use `task/Tnn-short-description`. One task owns one branch and PR. A subagent
   gets its worktree path and bounded file ownership; it cannot merge or edit
   the acceptance contract to accommodate its implementation.
3. Implement the scope, maintain affected documentation, and run each numbered
   acceptance check. Keep resumable local notes; record durable findings and
   validation in the PR. Do not commit personal inputs, secrets or raw audio.
4. Commit and push task-owned files, then open a PR with the task/issue link,
   behaviour change, scope, exact checks/results, limitations and actual roles.
   The main session verifies a subagent's handoff against the real branch/PR.
5. Mark ready for review when complete. Rework stays on this branch and uses
   the full review. New commits invalidate approval until reviewed again.

The main session can continue routine rework itself or with a same-family
subagent, recording any change of implementer. Two unsuccessful rework rounds
trigger a scope/architecture diagnosis with the user rather than an automatic
reviewer/model switch. Do not stop task work at a local patch without its PR.

## Choosing and invoking the reviewer

Choose only after the PR and validation evidence exist. Ask for the OpenCode
model if none has been named for this PR. A prior explicit choice for this PR
persists through rework. Validate the actual `provider/model` and any variant
against the installed CLI and live model list. A provider route is not a model
family: the same underlying family through another provider is still ineligible.
No automatic fallback. Diagnose a failed run before asking for a substitute.

Record PR number, base and head SHA, implementer family, reviewer model/provider,
variant, family, CLI version, agent/configuration identity and review session ID.
The review brief includes the full task, acceptance checks, PR diff scope and
implementer's results. Never pass credentials in the brief or logs.

T01 must verify the installed CLI's invocation and permission model; T02 owns
the watched wrapper and result publication. The local Linux binary is
`~/.opencode/bin/opencode`; this machine's PATH also exposes a Windows shim.
The inspected CLI supports `run --standalone --model --agent --file --format`
and encodes a variant as `provider/model#variant`. Older reference harnesses
must be checked before reuse. Re-check `--help` on version changes.

After T01 establishes a trusted `reviewer` agent, the invocation has this shape
(the wrapper supplies verified paths and model values):

```bash
"$OPENCODE_BIN" run --standalone --model "$REVIEW_MODEL" \
  --agent reviewer --file "$REVIEW_BRIEF" --format json \
  "Review the attached task and pinned PR; return the complete review." </dev/null
```

Run in a fresh review worktree at the PR head. Load trusted reviewer policy
from outside PR-controlled configuration and verify this through the CLI's
actual behaviour. The reviewer may inspect and run approved checks and write
test/cache artifacts in its isolated workspace; it may not change the submitted
patch, push, post, label or merge. T01 must verify permissions at the tool and
shell layers, including indirect write paths; deny lists alone are not a proven
sandbox. Review jobs do not inherit GitHub write credentials. The main session
or a separate trusted publisher posts their returned output.

Close stdin, retain session/log artifacts, impose startup/idle/total deadlines,
and watch the actual process/session. Do not consider a run successful merely
because its process exits zero. A failed or incomplete review remains visible
and never becomes approval. These requirements are planned until T01/T02 land;
the bootstrap documents do not claim technical enforcement already exists.

## Reviewer contract

- Prove checkout, base and head match the PR. Read the entire diff and task.
- Account for every acceptance criterion: command and result, or `not run`
  with a reason. Independently rerun reachable checks; main-session-only phone,
  credentialed or machine checks are identified and corroborated separately.
- Check scope, failure recovery, lesson/profile separation, provenance,
  idempotency and language-specific assumptions where relevant.
- Report all material findings in one pass, with file/line and reproduction
  or evidence. Distinguish confirmed defects, unverified concerns and follow-ups.
- Return one verdict: `approve`, `rework`, or `user decision`. Include numbered
  findings and an explicit list of unverified acceptance criteria. Conditional,
  missing, contradictory or truncated approval is not merge approval.
- Do not post to GitHub or edit the implementation. A main-session-only check
  does not become reviewer-verified by copying the author's output.

T02 records the review as evidence tied to its exact SHA, with any execution
limitations. A same-owner model review may need a PR comment rather than a
formal self-approval; never claim GitHub branch protection has been satisfied
by a comment alone. The complete review stays accessible, not just its verdict.

## Merge and follow-up

The main session reconciles every finding and verifies the PR head is still the
reviewed head. Required acceptance checks, project checks and any configured
GitHub required checks must pass. Required manual checks need recorded evidence;
where the reviewer cannot run them, the PR explicitly identifies the verifier
and the review's scope. Any waived criterion requires an explicit amended
contract and renewed review; the main session cannot relabel it passed.

Only the main session merges, with user authorization. Bind the operation to
the reviewed commit, for example `gh pr merge <n> --squash
--match-head-commit <sha>`. Preserve worktrees and local notes; cleanup is a
separate operation. Update issue status and record nonblocking follow-ups as
separate issues linked to their originating review. Creating this backlog and
PR does not authorize automatic execution or merging of every future task.
