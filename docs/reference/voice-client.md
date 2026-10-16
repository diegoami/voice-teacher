# Browser recording and teacher playback

T16 adds tap-to-talk, optional hold-to-talk, teacher replay and global finish to
the [web app](web-app.md). The server remains the authority for session progress.
Text and task cards remain readable throughout recording, processing and playback.
A paused activity refuses new recordings; T17 owns full pause/continue controls.

## Media lifecycle

Capture and playback share one controller per paired learner/session. Starting
capture interrupts playback first. Repeated taps cannot create parallel captures
or uploads. Hold supports pointer/touch capture and Space/Enter, with cancellation
on lost focus or pointer cancellation. Every capture exit stops its microphone
tracks; a late permission grant after finish or navigation is released immediately.
Leaving a session stops its player and microphone without inventing a server stop.
Explicitly reopening even the same saved session replaces the local controller
with the latest server presentation and rechecks its durable pending intent.

Recording requires HTTPS or loopback and browser microphone permission.
`MediaRecorder.isTypeSupported` chooses WebM/Opus, WebM, Ogg/Opus or MP4; uploads
use the corresponding accepted base media type. Unsupported formats, denied or
unavailable microphones, empty recordings and recordings under 250 ms show an
explanation and allow another attempt. Recording automatically ends at 60 seconds
and refuses data above 8 MiB. These local checks do not detect silence, pronounce
judgements or replace the server's recognition/limits.

The recorder waits for the final `dataavailable` followed by `stop` before
building its Blob, as specified by [MediaRecorder](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/stop_event).
Teacher audio is fetched from owner-bound API URLs with a bearer header and the
current revision, then played sequentially using memory-only Blob URLs. Playback
and upload requests have 45-second timeouts. Cookies, redirects and response
caches are disabled. There is no provider credential in the browser.

Autoplay is attempted after an accepted answer but is optional. A blocked or
interrupted `play()` leaves teacher text and a visible Play button, following
[the browser playback contract](https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/play).
Replay sends no learner attempt. Stop playback and a new recording interrupt the
player, abort an unfinished audio fetch and revoke temporary Blob URLs.

## Durable client intent and recovery

Before uploading, IndexedDB stores one unfinished recording per learner/session:
the exact Blob, media type, UUID request ID and expected revision. This database
is scoped to the server origin; its composite key additionally binds learner and
session. It contains no bearer, pairing code or operator/provider keys. It is
private browser data, separate from the server's recording retention policy.

A successful response must match the session, request ID and next revision
before the recording can be acknowledged and removed. On failure, the recording
stays available across refresh. Opening its saved session checks the server first.
If the saved presentation belongs to that request, recovery uses it without
another POST. Otherwise an explicit Recover action can retry the same ID, exact
bytes and media type at the original revision. A moved-on or paused session
refuses automatic resubmission and explains the conflict. Recovery never creates
a fresh attempt ID for an uncertain upload.

Discard deletes the browser copy, then reloads authoritative server state before
recording again. It does not retract an already accepted server attempt. An
unacknowledged recording remains until acknowledged, explicitly discarded, or
removed by clearing this site's browser data. Do not use a shared browser profile
for private practice. Server-side retention/settings are T26; this task adds no
background cleanup of another session's pending work.

Finish immediately stops capture/playback and aborts the client upload. It saves
a separate finish intent before sending the server control. A turn may already
be committing: finish reloads the current revision and permits at most two
control attempts, assigning a new ID only when its input revision changes.
A failed finish remains pending; refresh resumes the stored stop intent without
uploading the learner recording again. The app says finished only after the
server confirms it. It cannot revoke provider work already underway on the server.
Site storage must be available to save these intents; storage/network failures
remain recoverable errors rather than pretending a response was saved.

## Checks and limits

```bash
npm --prefix apps/web run build
npm --prefix apps/web test -- --run
npm --prefix apps/web run test:e2e -- voice
```

Controlled-media browser scenarios cover both modes, native taps and hold
(pointer/touch/keyboard), rapid double sends, denial/unsupported/empty/short
capture, late permission, sequential and interrupted playback, blocked playback,
byte-identical retries before commit, recovery after commit, pending finish races,
finish response loss across refresh, and IndexedDB identity/acknowledgement.
They retain synthetic screenshots and traces only. Catalogue regressions run
alongside them on desktop and Android emulation. T19 still requires real Android
recording, autoplay, routing and usability checks; emulation cannot replace them.
