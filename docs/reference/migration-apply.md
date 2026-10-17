# Reviewed historical import

T25 applies a selected [T24 preview](migration-preview.md) without inventing
learner turns or engine sessions. Many historical records are summaries or
opaque transcript blocks with unknown assistance. A separate, branded
`legacy-import.sqlite` ledger in the private runtime preserves that evidence,
its reviewed mapping and explicit source-specific course position. Existing
version-1 practice events, learner profiles and unrelated review history are
not rewritten.

The owner selected a dedicated private `diegoami/voice-teacher-progress`
repository and the latest recorded session with tracker/queue references as
the initial sample. Repository ownership/private visibility was verified on
2026-10-17. This choice and a prepared preview do not authorize an unreviewed
manifest. Record approval of the exact private sample before application.

## Review the concrete sample

The approval JSON has exactly these fields:

```json
{
  "format_version": 1,
  "reviewed": true,
  "approved_by": "named-operator",
  "preview_sha256": "SHA-256 of canonical preview JSON",
  "selected_observation_ids": ["legacy-<selected proposed ID>"],
  "course_positions": [],
  "destination_remote": "https://github.com/owner/private-progress.git"
}
```

Draft approvals use `reviewed: false` and cannot apply. The review flag and
verifier name are explicit operator assertions, not cryptographic proof of a
human action. The main session records the actual owner's approval separately.
The report hash binds the full preview, including every raw input and unresolved
record. A changed hash, unknown/conflicted observation, missing selected original
for a repetition, unsupported field or changed destination refuses application.

An optional course-position declaration is:

```json
{
  "source_id": "explicit-legacy-source",
  "course_id": "explicit-legacy-course",
  "covered_lesson_ids": ["earlier-unit"],
  "next_lesson_id": "next-part",
  "evidence_record_ids": ["record-<mapped tracker row>"]
}
```

Each referenced row must be mapped and belong to the same original source and
course. Identities are reviewed legacy references; they do not silently match a
different catalogue or content revision. Coverage is the original source's
declaration, with retained evidence, rather than a mastery score. T33 exposes
this position and explicit learner completion/reopening before app release.
Archival import alone does not claim the current selector already consumes it.
Preserve covered units and the next part; do not restart completed sessions
merely to create new-system practice events. Weak expressions remain available
for targeted later review independently of course completion.

## Apply and reconcile

Keep manifests, approvals, runtime and reports outside code/content checkouts.
Verify the destination's owner/private visibility and the app namespace using
the actual hosting service before setting either verification flag. No visibility
is inferred from a URL or local bare repository. The code refuses credentials
in destination URLs, source/runtime overlap, Git runtime paths, public runtime
permissions and foreign/unversioned nonempty database files.

```bash
PYTHONDONTWRITEBYTECODE=1 python -m voice_teacher.progress.legacy \
  --root /private/source-checkout \
  --manifest /private/reviewed-manifest.json \
  --approval /private/reviewed-approval.json \
  --runtime /private/voice-teacher-runtime \
  --destination /private/progress-checkout \
  --remote https://github.com/owner/private-progress.git \
  --private-verified --owner-verified
```

The destination directory must already exist. The command re-reads the hash-pinned
sources and rebuilds the preview before committing any historical projections.
It writes the selected observations, course declarations and complete reviewed
receipt in one SQLite transaction. A mid-import failure rolls everything back;
the same retry adds nothing twice. A new receipt with conflicting existing
observation/position IDs is refused for explicit review, never overwritten.
Unresolved/conflicted records remain in the retained report and are not activated
as practice observations. Existing raw source hashes must still match afterward.

The only stdout is aggregate counts plus local-export/remote-push state; failures
are sanitized. A failed export may leave a committed local import ready to retry.
Do not interpret local success as a successful remote backup. Retain the source
manifest, approval and private reconciliation report with the runtime.

## Export, sync and restore

Immutable canonical JSON batches are published exclusively under
`voice-teacher/legacy-v1/batches/<sha256>.json`, mode 0600. Each includes the
reviewed preview, original raw text, all unresolved context and exact approval.
Restore reconstructs the preview from its retained input bytes using the same
planner, checks its hash and selected references, validates every incoming batch
before activation, then replays the set transactionally. Partial/corrupt/forged
evidence cannot activate partial history. Legacy records never become fabricated
canonical sessions during export or restore.

`LegacyArchive(destination).export(ledger)` and `.restore(ledger)` provide local
backup/recovery. The ledger is bound to its exact verified destination; changing
that destination requires a separately reviewed handoff. Do not edit a receipt,
reset a checkout or rename an immutable batch to make a conflict disappear.

The existing single-writer Git worker accepts explicit `legacy=ledger`:

```python
ledger = LegacyLedger(runtime, destination_remote=verified_remote,
                      private_verified=True, owner_verified=True,
                      forbidden_roots=[source_checkout])
worker = GitSync(store, managed_checkout, verified_remote,
                 private_verified=True, owner_verified=True,
                 forbidden_roots=[source_checkout], legacy=ledger)
worker.run_once()
```

The canonical Store and legacy ledger must share the private runtime and remote.
An app-managed checkout must be fresh; do not pre-clone or mix arbitrary staged
files into it. Supplying legacy support changes the bound configuration, so an
existing canonical-only worker cannot silently adopt it. Preserve its work and
follow a reviewed fresh-runtime handoff instead. Default canonical-only bindings
remain unchanged. The worker validates both namespaces, stages only exact
validated hash-named batches, preserves unrelated tracked remote files, fetches/
merges/pushes without force, and reports separate `legacy_imports` receipt states
(`locally_saved`, `exported`, `pushed`). Authentication stays in the explicit
operator-owned askpass helper, outside all checkouts; credentials are not archived.

The initial real sample, remaining import scope and main-session verification
belong in the PR's acceptance evidence. Until the owner reviews and the selected
sample is actually applied/reconciled, DW2 stays incomplete. Synthetic fixtures
and local bare Git tests cannot substitute for that check. Real-phone acceptance
also remains explicitly incomplete under its own task contracts.
