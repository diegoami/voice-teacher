# Tnn Task title

- **Kind:** feature | infrastructure | migration | acceptance | decision
- **Milestone:** named release boundary
- **Issue:** GitHub issue link
- **Branch:** `task/Tnn-short-description`
- **Merge after:** task IDs, or none
- **Implementer:** main session by default; a native same-family subagent may
  implement. Record the actual identity/family on the PR.
- **Reviewer:** independent OpenCode model chosen ad hoc for this PR, invoked
  through the CLI; record its provider/model, variant and family. Different
  family from the implementer; see [process](../process.md).
- **Evidence:** relevant production-plan section, current code or measured result.
- **Owns:** bounded paths and contract seams; shared edits require coordination.

## Scope

One independently useful change. State confusing exclusions and unresolved
decisions that must be settled before dispatch.

## Done when

1. Observable outcome, including an appropriate failure/retry boundary.
2. Regression/integration/manual acceptance evidence and expected result.
3. Relevant existing invariants and project checks still pass.

The implementer publishes a GitHub PR with the acceptance results; independent
review and merge checks are lifecycle requirements from the process.

## Verification

Commands or a precise human procedure. Future test paths are planned contracts;
preflight resolves them before `status:ready`. Do not claim they run today.

## Hazards

The specific regression or data-loss risk this task must avoid.
