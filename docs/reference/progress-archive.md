# Private progress export and restore

T11 adds `voice_teacher.progress.Archive`. It exports committed event history
from SQLite into a configured private destination. It does not infer remote
visibility, create Git commits or push. The operator must verify ownership and
privacy before selecting a repository; T12 supplies recoverable Git sync.

```python
from voice_teacher.progress import Archive, readable_history
from voice_teacher.storage import Store

store = Store("/private/server-data")
archive = Archive("/private/progress-checkout",
                  forbidden_roots=["/local/content-checkout", "/private/server-data"])
archive.export(store)
events = archive.read()
text_view = readable_history(events)

restored = Store("/private/another-server-data")
count = archive.restore(restored)
```

The destination must already exist. Every export writes only beneath
`voice-teacher/v1/batches/`. Unrelated card-review files are not scanned or
changed. Code and configured forbidden roots cannot overlap the destination.
Runtime storage and the archive must be separate. Export additionally refuses
any checkout registered in the source registry. Supply all other content roots
through `forbidden_roots`, including sources not registered on this instance.
Namespace and batch symlinks are rejected. The configured root is trusted
operator configuration; concurrent hostile local filesystem replacement is
outside this importer boundary.

Each UTF-8 file is a canonical JSON object with exactly these fields:

- `schema_version: 1`, `kind: "private_progress_batch"`;
- `learner_id`, `session_id`;
- `events`: a complete per-session prefix, starting at one and ending with a
  `state.saved` durable checkpoint;
- `activities`: immutable activity descriptors with ID, position and JSON data.

The filename is the SHA-256 of its complete bytes plus `.json`. The events use
the existing [version-1 interchange contracts](data-formats.md), including full
private session snapshots. No new event authority or progress inference is
introduced. Overlapping prefixes deduplicate by event ID and exact content;
changed event contents, conflicting session sequences or activities are errors.
The initial implementation repeats prefixes for simplicity and correctness;
storage growth should be measured before introducing incremental compaction.

Export reads one consistent SQLite view, resolves historical source/item and
learner/session/turn references, then leaves the transaction before filesystem
work. It writes a 0600 `.pending-*` file, flushes it, publishes by exclusive hard
link and fsyncs the directory. New namespace directories are 0700 and their
parent entries are synced. Existing batches are never overwritten. Only after
publication does SQLite acknowledge the exported event IDs. A crash before
acknowledgement leaves pending work; retry publishes the same bytes/name safely.
New practice occurring after the read remains pending. Completed local export
does not mean a Git commit or remote backup succeeded.

Import checks filenames, checksums, closed batch fields, event schemas, complete
checkpoints and duplicate IDs before writes. Complete history must resolve each
historical source snapshot/item revision, origin turn belonging to the learner
and superseded observation. Namespace `.pending-*` files are ignored; unexpected
files, corrupt published batches and symlinks fail explicitly. Default limits
are 16 MiB per batch, 256 MiB total and 10,000 directory entries; increase them
explicitly for a measured restore rather than allowing unbounded reads.

`restore` uses one SQLite transaction for the complete import, reusing Store's
normal transition validation and projections. Existing matching prefixes are
idempotent; older archives cannot erase newer local history. Differing IDs,
revision/content conflicts, unresolved/cyclic supersession dependencies and
activity conflicts roll back the whole import. Checkpoints are replayed in
session order with superseded observations available before replacements.
Existing in-flight provider work blocks any advancement of that session.
Existing learner profiles are not overwritten; a new learner starts from its
first restored session snapshot's profile. All per-session profiles stay intact.
Imported events are marked locally exported, without a remote-push claim.

The portable boundary is the last committed session checkpoint. Pending
recognition/judging intent, cached provider responses, original client request
receipts, audio caches, pairing credentials, operator configuration and API
keys are not exported. A restored interrupted session resumes from that
checkpoint; resubmitting a previously in-flight turn can call a provider again.
Quiesce provider work before a server handoff. Replay guarantees apply to event
history, not exactly-once provider billing or lost HTTP request receipts across
restores. Raw audio and SQLite binaries are never copied. Authored transcript,
profile and lesson strings are private content and require a private destination;
this field allowlist is not a scanner for secrets pasted into ordinary text.

`readable_history(events)` generates a plain text view containing saved status,
turns, actual assistance/outcomes, original item identities and supersessions.
The view is derived and never used as import authority. It does not relabel
assisted attempts as independent or imply mastery.

Verification uses synthetic data and temporary local destinations only:

```bash
uv run pytest tests/progress/test_roundtrip.py -q
uv run pytest tests -q
```

Tests cover complete/interrupted recovery and continued practice, corrections,
cross-source provenance and supersession, repeat/older-prefix import, checksum
and event conflicts, partial publication and retry, transactional rollback,
pending provider work, registered content exclusion, unrelated-file retention,
symlinks, limits and credential/audio/database exclusion.
