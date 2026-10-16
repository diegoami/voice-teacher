# Transactional runtime storage

T05 adds `voice_teacher.storage.Store`. It stores private runtime data in a
configured directory outside code, content and Git checkouts. No database or
learner record belongs in this repository. A newly created directory is 0700
and the database is 0600. Supply `forbidden_roots` for any content directories
that are not Git checkouts. Database-file symlinks are refused.

```python
from voice_teacher.storage import Store

store = Store("/absolute/private/server-data", forbidden_roots=["/path/to/content"])
store.save_learner("learner-id", {"level": "beginner"})
# Build validated version-1 progress events and a full private session snapshot.
store.commit("learner-id", "session-id", events, expected_revision=None)
snapshot = store.session("learner-id", "session-id")
```

Each transition is a nonempty batch of version-1 progress events ending in
exactly one `state.saved` event. That event contains the full resulting session
snapshot. New sessions start at revision zero and event sequence one. Updates
require the current `expected_revision`, advance it by one, and append contiguous
event sequences. Learner and session identity are explicit on every operation.
Session IDs are scoped by learner; event IDs are globally unique. A learner
must exist before its first session. Inputs are copied and validated; source,
curriculum, mode, topic and languages remain pinned throughout a session.

One `BEGIN IMMEDIATE` transaction checks ownership/revision and commits the
snapshot, optional activity descriptors, immutable events, turn/observation/
evidence projections and one pending export job per event. Revision ownership
is checked again in the SQL update. SQLite connections are short lived, foreign
keys are enabled and synchronous mode is FULL. Speech, judging, Git and other
external work must happen before/after this call. No provider callback is accepted.
The database belongs on a local persistent filesystem, with one writer server.

`RevisionConflict` rejects stale updates. `EventConflict` rejects an event ID
already present, even for an identical replay; it never overwrites history.
T06 supplies durable request-ID replay semantics above this storage boundary.
Unexpected insert or constraint failures roll back all rows, including session
creation, evidence and outbox work. Append-only triggers reject direct event
UPDATE/DELETE. They protect application invariants, not against a local database
owner who can alter its schema.

`events(learner, session)` returns original events in sequence order.
`projection(...)` returns activities, turns, observations and evidence from one
consistent read transaction. Supersession records preserve the original evidence
and require an earlier observation belonging to the same learner. Historical
provenance resolution against a complete exported archive remains T11.
`rebuild(...)` regenerates session, turn, observation and evidence projections
transactionally from immutable events; it leaves activities and pending/completed
export jobs untouched. It does not discard evidence superseded by a later event.
Activity descriptors are private immutable plan metadata (`activity_id`, zero-based
`position`, JSON-object `data`), inserted with a transition; they are not a new
interchange format or a mode scheduler.

`pending_exports(limit=100)` lists stable event-ID jobs in per-session order.
`record_export_attempt(job_id, succeeded=...)` records retries or completion;
completed jobs remain completed on replay. No Git or export worker runs here;
T11/T12 own those operations. Callers can retrieve job payloads from the event log.

Internal SQLite schema version 3 is separate from JSON interchange version 1.
The migration path creates v1 core tables, then v2 activities/projections/outbox
and append-only triggers. Existing v1 event history backfills projections and
pending export jobs. T06 adds durable request stages in v3; see
[turn-recovery.md](turn-recovery.md). DDL and `user_version` changes share one transaction.
Existing databases are inspected read-only before a writable connection: newer
versions, foreign application IDs and nonempty unversioned databases are refused.
There is no automatic downgrade, destructive repair or adoption of unrelated data.

Verification:

```bash
uv run pytest tests/storage -q
uv run pytest tests/engine tests/contracts tests/storage -q
```

Tests use synthetic JSON and temporary private directories. They cover actual
writer-process exit/reopen, projection reconstruction, transaction failure at
events/evidence/outbox, stale/concurrent revisions, duplicate event IDs, source
pinning, immutable history, supported migrations and byte-preserving refusal
of future schemas. The current implementation validates a complete session
history on append/rebuild for correctness; optimize this only after measuring
real session sizes. This storage primitive does not yet coordinate resumable
provider stages, deliver audio or synchronize a progress repository.
