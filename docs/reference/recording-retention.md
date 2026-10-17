# Private learner recording retention

T26 makes saved server copies of learner recordings optional. Saving defaults to
off for every learner. The speech provider still processes each submitted
recording; this setting controls this server's retained copies. Transcripts,
practice events, learner completion choices and imported history remain separate.

## Learner controls

Open **Recording privacy**, then **Load recording settings**. Choose off or a
duration and apply it. The web choices are 1, 7 or 30 days; the paired API accepts
whole days 0–30. Turning saving off immediately deletes that learner's retained
copies. This does not delete the session transcript, practice evidence, corrections
or weak-item queue. Failed settings responses tell the learner to reload and
confirm the server's actual state.

A duration starts when an upload request is first accepted for processing. An
opted-in recording can therefore exist even if recognition later fails. Retrying
the same upload never extends its expiry or recreates expired/deleted audio.
Increasing the preference affects future uploads; shortening it also bounds
existing copies by their original creation time. Enabling saving does not recover
recordings first accepted while saving was off.

**Evidence for … → Load recording status** displays saved/not-saved, expired,
deleted or unavailable status for the session's uploads. Cleanup preserves those
metadata references and immutable practice history. Missing/corrupt retained
assets become unavailable and are not silently regenerated.

The browser keeps an unacknowledged recording in its owner/session-bound pending
upload journal for safe retry. It removes the pending bytes after acknowledgement
or cancellation. This transient device storage is separate from the server's
retention preference. Closing a tab during an unacknowledged request does not
promise to erase the pending upload.

## Expiry and maintenance

Expired audio cannot be retrieved. Reads recheck expiry under the recording lock,
including after waiting for another operation. The API application also sweeps
expired assets every 60 seconds during its lifespan. Startup, new processing,
recording reads and explicit cleanup enforce the policy. An idle running server
therefore removes expired copies within the next sweep, normally at most 60
seconds after expiry; a stopped server cleans up on its next startup.

An operator can expire assets without serving the app:

```bash
python -m voice_teacher.storage.recordings --runtime /private/server-runtime
```

Use the installed application version and its private runtime directory. The
command returns an expired-record count; failures return a sanitized error and
nonzero exit. It never edits progress events or teacher-audio cache. Startup and
maintenance also remove interrupted `.pending-*` files and untracked managed
recording files. Unknown ordinary files are preserved; symlinks stop cleanup
rather than following their targets. A periodic-worker failure emits a generic
operator warning without learner text, audio, credentials or private paths.

## Storage and authenticated access

SQLite schema9 adds learner preferences and recording metadata. Raw bytes live
only in the runtime's dedicated `learner-recordings/` directory (0700), as
hashed `.bin` files (0600). Stable identities bind learner/session/request and
the accepted upload digest/media type. A thread lock and OS file lock coordinate
server operations with an operator cleanup process. File publication and database
failure leave no acknowledged partial asset; interrupted untracked files are
removed at startup/maintenance. Files and metadata stay outside code/content/Git.

All paths below begin `/api/v1` and require a paired learner token:

| Method/path | Behaviour |
| --- | --- |
| `GET /recording-retention` | Read own `retention_days` |
| `POST /recording-retention` | Set `{retention_days: 0..30}`; zero purges retained copies |
| `POST /recording-retention/cleanup` | Accept `{}` and expire assets; return own count |
| `GET /sessions/{id}/recordings` | Own session's allowlisted recording metadata |
| `GET /sessions/{id}/recordings/{recording_id}` | Return retained bytes; 410 for expired/deleted/not-saved/unavailable |

Unknown/wrong-owner sessions or recording IDs return 404; anonymous requests
return 401. Clients cannot supply another learner ID. Raw paths and filesystem
names are never accepted. Metadata excludes private paths, raw content and digest
fields. Binary and JSON API responses use no-store/nosniff protections. Current
session revision is not required to inspect historical recording metadata.

## Private progress destination

Raw recordings and the local retention preference are excluded from the progress
archive and Git sync. A clean canonical archive restore defaults saving to off;
T29 owns complete runtime/asset backup recovery. Snapshots and transcripts are
sensitive even without audio. Remote sync still requires T12's explicit verified
private destination and owner assertions. It refuses unverified configuration
before checkout initialization. Do not treat a caller's boolean as external
verification: the operator must inspect the actual selected repository first.

For a GitHub destination, for example:

```bash
gh repo view OWNER/PRIVATE-PROGRESS --json nameWithOwner,isPrivate,viewerPermission
```

Require the intended owner/repository, `isPrivate:true` and appropriate write
permission before enabling sync, and reverify after destination/visibility changes.
Unknown/public/mismatched destinations must remain disabled. Keep credentials out
of remote URLs and use the explicit private askpass configuration described in
[progress sync](progress-sync.md). T25 records the selected dedicated destination;
T26 rechecked its metadata without reading or modifying private progress content.
Visibility is operator-verified, not continuously polled by GitSync itself.

## Verification and remaining acceptance

```bash
uv run pytest tests/privacy -q
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e -- retention
```

Original synthetic voice fixtures exercise default off, opt-in lifetime, retry,
restart cleanup, idle expiry, disable/lost-response recovery, owner isolation,
traversal/symlink refusal, archive exclusion, publication/migration rollback and
unchanged evidence/teacher audio. Browser checks include desktop and Android
emulation with an actual synthetic server. Real deployed-phone, microphone and
unscripted human acceptance remain explicitly incomplete under T19/T30.
