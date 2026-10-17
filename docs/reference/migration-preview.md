# Read-only historical migration preview

T24 provides `python -m voice_teacher.progress.preview`. It reads explicitly
selected legacy tracker, shared queue and transcript Markdown into a private
reconciliation report. It never constructs a Store, connects to a database,
exports progress or pushes a repository. A report is not an import authorization
or a version-1 progress-event stream. T25 owns reviewed application and any
further mapping needed for valid persistent history.

Read the source repository's root and nested instructions before selecting
files. Keep each source/course independent. The planner does not follow links,
discover unrelated files, run package scripts, call providers or modify sources.
Inputs are UTF-8 regular files, with no symlinks in relative path components,
bounded to 4 MiB each, 16 MiB total, 128 files and 10,000 extracted records.
The original bytes' SHA-256 must match the operator manifest before parsing.

## Discovery and explicit mapping

Create an operator manifest outside Git with exactly these fields:

```json
{
  "format_version": 1,
  "namespace": "reviewed-legacy-sample",
  "learner_id": "operator-selected-learner",
  "inputs": [
    {"path": "tracker.md", "kind": "tracker", "sha256": "64 lowercase hex characters"},
    {"path": "review/queue.md", "kind": "queue", "sha256": "64 lowercase hex characters"},
    {"path": "sessions/example/transcript.md", "kind": "session", "sha256": "64 lowercase hex characters"}
  ],
  "mappings": []
}
```

Paths are explicit, relative to `--root`. Replace example paths and hashes with
reviewed inputs. An empty mapping produces a discovery report: all extracted
records remain unresolved. The report preserves every entire source text plus
its original hash, record raw text, headings, line span and table fields. Table
rows are separate records; paragraphs and fenced blocks stay opaque. A transcript
block is not automatically one learner attempt. Unknown formats, templates,
summaries and duplicated logs remain available without fabricated observations.
Malformed table rows retain their raw text and a parse issue.

Read the private report and explicitly map selected `record_id` values. Each
mapping has exactly this shape:

```json
{
  "record_id": "record-<discovered SHA-256>",
  "observation_key": "operator-stable-evidence-key",
  "original_source": {"source_id": "original-source", "course_id": "course-a", "lesson_id": "unit-a"},
  "practice_source": {"source_id": "later-source", "course_id": "course-b", "lesson_id": "unit-b"},
  "assistance": null,
  "correction": null,
  "repetition_of": null
}
```

These are explicit legacy source identities, not manufactured pinned curriculum
revisions. `assistance` is null when unknown; allowed explicit labels are
`modelled`, `repeated`, `cued`, `independent`, `corrected_repeated`, `needs_turn`.
The operator must substantiate a non-null label. Labels are never mined from
prose, and neither mastery nor pronunciation is inferred. A supported correction
is `{attempt, preferred, reason}`, with all three original strings retained.

Use a distinct `observation_key` for a later repetition, retain the original
source, set the new practice source, and set `repetition_of` to the original
observation key. References must resolve with matching original provenance;
cycles, missing references and chains exceeding 128 levels become conflicts.
Identical phrases under different source/course mappings remain distinct.

Map multiple records to the same observation key only after manually verifying
they describe the same evidence. Equal proposals then become one observation
with all supporting record IDs. Conflicting proposals retain all raw evidence
and become conflicts, with no last-writer-wins result. This explicit grouping
prevents a tracker summary, shared-queue copy and transcript copy from being
counted as separate practice merely because all were read. Unmapped rows stay
unresolved; no cross-source or text-similarity deduplication occurs.

## Private report and reconciliation

```bash
mkdir -m 700 /private/operator-preview
python -m voice_teacher.progress.preview \
  --root /private/source-checkout \
  --manifest /private/operator-manifest.json \
  --output /private/operator-preview/discovery.json \
  --protected-root /private/runtime \
  --protected-root /private/progress-checkout
```

The output's parent must already exist with private permissions. A new mode-0600
file is created exclusively; an existing file or final symlink is refused.
Source roots, the code installation, any Git checkout (including worktree `.git`
files) and supplied protected roots cannot receive the report. Supply runtime and
progress roots even if they are not Git checkouts. The only write is the selected
report file; the command prints aggregate counts and sanitized failure categories.
Raw text, per-record details, learner identity and source paths stay in the
private report. Run with `PYTHONDONTWRITEBYTECODE=1` when interpreter cache writes
must also be suppressed. No report or real manifest belongs in the code repo.

For every input and in the total, `records = proposed + unresolved + conflict`.
`observations` counts unique accepted proposal groups, not rows or mastery.
The report retains `apply_authorized: false` and `human_evidence_review:
incomplete`; it does not turn an operator mapping into verified semantic truth.
Review each raw record and every ambiguity before selecting T25's sample.

Record IDs hash the namespace, relative path, heading context, exact raw block
and its duplicate occurrence ordinal. Proposed IDs hash namespace, learner ID
and the explicit observation key. Identical inputs/mapping yield identical JSON,
including after input/mapping array reorder. Changed file bytes invalidate the
manifest; do not silently refresh hashes or reuse a mapping for changed evidence.
Duplicate occurrence ordinals are not persistent identities across source edits.

The synthetic tests exercise reconciliation, explicit duplicate
grouping, cross-course distinctions, raw preservation, deterministic replanning,
input hashes, path traversal, symlinks, reference conflicts, report permissions
and the real CLI's byte-for-byte preservation of unrelated state. No real learner
history has been imported or accepted by these tests.
