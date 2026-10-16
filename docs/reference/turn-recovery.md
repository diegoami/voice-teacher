# Durable turn coordination

`voice_teacher.practice.coordinator.Coordinator` wraps the extracted guided
engine with durable request IDs, stored judge results and replayable teacher
presentations. It uses `Store` and a callable judge; an optional delivery callback
prepares audio references or other JSON metadata from saved teacher turns.
Provider implementations and HTTP endpoints follow in T09/T10.

`create(template, lesson, profile=UKRAINIAN, part="all")` takes a T03 private
session envelope and a prepared T04 lesson. It validates pinned source/languages,
item IDs and target renderings against the compiled curriculum. It stores the
initial teacher plan and full state at revision zero. Creation is explicit;
client retry semantics below apply to `submit` and `control`, not to `create`.
The initial presentation is retained in the snapshot for later speech preparation.

`submit(learner, session, request_id, expected_revision=..., text=...)` uses these
persisted stages:

1. `accepted`: unique request ID, exact text and expected revision recorded before
   judging. Another unfinished request for this session is rejected.
2. `judged`: the first completed judge result is recorded before applying it to
   the engine. After restart, the result is replayed instead of calling the
   provider again. Repetition may skip this stage.
3. `committed`: accepted turn, evidence, teacher plans, snapshot, export jobs and
   recorded request result share one SQLite transaction.
4. `delivered`: the delivery callback's JSON metadata has been stored. This
   internal stage means the server adapter completed; it does not prove the
   learner played/heard audio. No `teacher.reply_delivered` progress event is
   invented from synthesis alone.

Reusing an ID with the same text and original expected revision returns or
resumes that work. Different input/revision under the same ID is a conflict.
Replays consult the recorded request before checking the current session
revision, so a lost response remains recoverable after advancement. Historical
responses retain their original revision; clients must compare revisions before
playing audio or replacing their current screen. A new turn requires the current
revision and active status. Learner/session ownership is checked transactionally.

Within the supported single writer process, a per-session mutex spans provider
work without holding a database transaction. SQLite also enforces one unfinished
request and atomic revision/result checks across competing connections. Duplicate
requests across processes cannot add a second progress transition. Multiple
simultaneous server instances are still unsupported: they may duplicate provider
calls or delivery preparation despite recording only one local result.

Provider and delivery calls are outside database transactions. If a provider
response arrives but the process dies before saving it, retry may charge again;
no local mechanism guarantees exactly-once remote billing. Local accepted
attempts and evidence remain idempotent. If judging was saved, replay skips it.
If state was committed but synthesis fails, retry uses the saved teacher plan
without another engine transition. Client playback/network failure reuses the
same saved response/audio references; T18 owns actual browser playback state.

`control(..., operation="pause"|"resume"|"stop", expected_revision=...)` uses the
same durable request/result mechanism. Pause and stop can cancel an unfinished
intent after a crash; its input/decision remains in the private request table
with `cancelled` status, without manufacturing a progress attempt. If a concurrent
turn already committed, the control's stale revision is rejected and the client
retries with the refreshed revision. Accepted controls preserve valid engine
snapshots and record state events. Direct stop closes the engine without
inventing a spoken learner transcript. Resume preserves phase/help; replaying
the last teacher plan is a separate presentation action.

Coordinator capsule version 1 contains the prepared lesson, language profile,
inner T04 engine capsule and presentation. It lives inside T03's opaque
`engine_state.data`; interchange schema version 1 is unchanged. Item provenance
uses explicit curriculum item revisions; state events reference real existing
turn IDs. Assistance captured before the attempt is preserved in evidence rather
than upgrading a corrected/repeated answer to independent use. Engine logs and
private profiles stay in private storage outside the code repository.

SQLite internal schema v3 adds request stages and the active-request index. It
migrates v2 history without changing original events or export jobs; migration
failure rolls back the table/index and version. Unfinished requests are local
runtime work. Exported committed state and database backup of pending local work
remain separate guarantees (T11/T29); this coordinator does not implement export.

```bash
uv run pytest tests/integration/test_turn_recovery.py -q
uv run pytest tests/integration tests/storage tests/engine tests/contracts -q
```

Synthetic checks cover response replay in a fresh process, concurrent IDs,
six failure boundaries, atomic request/progress commit, failed synthesis/playback
retry, provider transactions, pause/stop races, cancelled intents, assistance,
two competing processes and v2/v3 migration failure/recovery. No live providers,
real learner records or client playback are required for these checks.
