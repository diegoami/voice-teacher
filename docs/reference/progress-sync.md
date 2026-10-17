# Recoverable Git progress sync

T12 adds `voice_teacher.progress.git_sync.GitSync`. It runs separately from the
teaching request, using an app-managed checkout and the private
[T11 archive](progress-archive.md). One active writer server is supported.
Do not run two servers writing a learner's history concurrently.

```python
from voice_teacher.progress.git_sync import GitSync

sync = GitSync(store, "/private/managed-progress-checkout", verified_remote,
               private_verified=True, owner_verified=True,
               forbidden_roots=["/local/lesson-checkout"])
sync.start(interval=30)
status = sync.status()
# Before shutdown/handoff, confirm this returns True; False means still running.
stopped = sync.stop(timeout=5)
```

`private_verified` and `owner_verified` are explicit operator assertions, not
visibility inferred by this library. Before configuring a real destination,
record the owner, actual private visibility, namespace permission and verification
method in private server configuration. A public/unknown remote is not acceptable.
Synthetic tests use owned temporary local bare repositories; they do not establish
the privacy or ownership of any actual account/repository.

The managed checkout must be separate from runtime storage, app code and content.
T25 optionally adds an explicitly configured `legacy=LegacyLedger(...)` and
immutable legacy-history namespace; see [reviewed import](migration-apply.md).
Canonical-only bindings retain their previous identity. Existing workers cannot
silently adopt the additional namespace; use the verified handoff procedure.
The first setup requires an empty directory; existing arbitrary checkouts are
never adopted. Subsequent opens verify the private runtime destination binding,
writer identity and exact managed Git configuration. Registered content roots
are checked before checkout initialization; pass other content roots explicitly.
The app writes only validated batches under `voice-teacher/v1/batches/` and Git's
own metadata. Existing unrelated remote files are preserved, not staged as app
changes. Unknown tracked/untracked/staged files, modified batches, conflicts or
unfinished Git operations stop sync for operator inspection.

Supported remote transports are credential-free HTTPS URLs and absolute local
paths. Credentials never belong in URLs, batches or runtime status. For HTTPS,
an explicitly selected operator-owned executable `credential_askpass` can be
provided outside all code/content checkouts; Git invokes it only for authentication.
This is trusted private server configuration, not repository code. SSH/custom
credential schemes are not enabled implicitly. No arbitrary inherited Git
environment, global/system configuration, hooks, templates or fsmonitor is used.
Managed local configuration is allowlisted before operations. Every Git subprocess
has closed stdin and a bounded timeout (30 seconds by default). Captured Git output
is not published as status; exceptions/status avoid remote credentials and paths.

## Pipeline and states

`run_once()` is available for deterministic scheduling/testing; `start()` runs it
on a separate thread and retries on the configured interval. A runtime file lock
prevents concurrent workers for the same store. It is not a distributed lease;
separate servers require the explicit handoff below. `stop()` reports whether the
thread actually exited; a busy bounded Git operation may outlive a short stop wait.
Never claim the writer stopped merely because a stop request was sent.

Each cycle:

1. Verify identity/configuration, dirty/index state and canonical batch bytes.
   Recover app-owned untracked or already staged new batches into a local commit;
   this handles a crash after export/staging and avoids untracked-file collisions.
2. Fetch the configured branch and merge without force. Ordinary append-only
   divergence can reconcile; content/event conflicts stop rather than overwrite.
3. Restore remote batches transactionally, preserving newer local prefixes and
   refusing differing IDs or in-flight session advancement. Requeue local events
   absent from this destination, including prior local exports to another archive.
4. Export committed local events, stage only explicit validated hash-named batch
   files, and commit. Git work happens outside SQLite transactions.
5. Push without force. Only a successful push records its commit, timestamp and
   exported event-ID receipt atomically in private `progress-sync.json`.

The teaching path only needs SQLite; no fetch/commit/push is called by Coordinator.
Failure leaves local sessions, export files, pending export work and/or unpushed
commits available for retry. A lost push response does not claim success until a
later retry confirms the push. A failed commit can resume its own validated staged
batch files. Foreign staged files are retained and require operator inspection.

`status()` returns event IDs with distinct states:

| State | Meaning |
| --- | --- |
| `locally_saved` | SQLite has the event; no acknowledged local export yet |
| `exported` | Local batch publication succeeded; no successful remote receipt |
| `pushed` | Event belonged to a successfully pushed archive commit |

`last_push_at`/`last_push_commit` retain the last success through later failures.
`error` is sanitized. T11 outbox `done` means local export only; it does not remove
the remote-pending work represented by the checkout and push receipt. Cycles run
even when no SQLite jobs remain pending. An unchanged push can refresh the success
timestamp; it never fabricates new practice events. Per-event receipts and repeated
archive prefixes favour correctness initially; measure growth before compaction.

## Destination changes and server handoff

The runtime binds checkout path, remote, branch and namespace by fingerprint.
Changing any of them is rejected. Do not edit the binding/receipt, force-push,
reset a checkout, or delete pending batches to make a failure disappear.

1. Quiesce practice and provider work on the old server. Run a final successful
   sync and record its commit/timestamp and the complete validated archive. Confirm
   every event is `pushed`, not merely exported. Keep an independent private backup.
2. Stop the worker and confirm it exited. Shut down the old writer server. Verify
   the new destination's owner, privacy and app namespace; for a different remote,
   retain the original history/archive and record the deliberate migration choice.
3. Create a fresh private runtime and empty app-managed checkout for the new
   binding. For the same remote, pull/restore it. For a new remote, restore the
   validated old archive into the fresh runtime, then sync to the explicitly
   verified new destination. Do not mix learners or reuse an unrelated checkout.
4. Compare restored event IDs, snapshots, assistance/provenance and projections
   against the old archive. Run sync and verify the new remote commit and per-event
   pushed state. Pair clients explicitly to the new server; API credentials and
   in-flight provider receipts are not part of the portable archive.
5. Enable the new writer only after reconciliation. Keep the old runtime/remote
   read-only for rollback; never let both writers resume. If reconciliation fails,
   stop the new writer and inspect both histories without discarding either.

These are operator-required actions, not actions this task performs on a private
repository. T29 adds broader backup/restore acceptance and T28 deployment setup.

Verification:

```bash
uv run pytest tests/progress/test_git_sync.py -q
uv run pytest tests -q
```

Tests use local bare remotes and synthetic sessions. They exercise disconnected
practice, failed push/restart/retry, lost push responses, divergence reconciliation,
foreign dirt/index refusal, preserved card-review files/content, conflicting events,
staged commit recovery, privacy/destination/ownership gates, concurrent writer locks,
background execution and retained last-success status.
