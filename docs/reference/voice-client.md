# Browser recording and teacher playback

T16 adds tap-to-talk, optional hold-to-talk, teacher replay and global finish to
the [web app](web-app.md). The server remains the authority for session progress.
Text and task cards remain readable throughout recording, processing and playback.
A paused activity refuses new recordings. Pause and Continue retain the server-owned activity, step and assistance; completed activity boundaries are labelled separately from interrupted practice.

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
The owner-bound `/sessions/{id}/requests/{request_id}` receipt confirms an accepted response even after another control changes the latest presentation. Recovery acknowledges that recording without another POST and loads the current session, never a historical reply. Otherwise an explicit Recover action can retry the same ID, exact
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
a durable control intent before sending the server control. A turn may already
be committing: finish reloads the current revision and permits at most two
control attempts, assigning a new ID only when its input revision changes.
Finish reads `/sessions/{id}?prepare_audio=false` to inspect saved state without
requesting speech. If control state commits but closing audio fails, this read
confirms completion and retains the closing text. Other status reads keep their
existing audio-preparation default. A failed finish remains pending; refresh
resumes the stored stop intent without uploading the learner recording again. The app says finished only after the
server confirms it. It cannot revoke provider work already underway on the server.
Site storage must be available to save these intents; storage/network failures
remain recoverable errors rather than pretending a response was saved.

Pause stops local media immediately and persists its intent. If Send already saved
an upload, pause first recovers that same ID and Blob, then pauses at the current
revision. Provider failures retain both intents and offer Recover; Finish can
supersede a pending pause and explicitly cancel unfinished server work. A recording
still being captured is discarded locally on pause. Continue restores the current
cue or starts the next completed activity boundary. Neither action claims mastery.
The client waits for any in-flight local Blob write before checking its intent.

The same IndexedDB database upgrades from version 1 to version 2 transactionally:
old recordings remain intact and old finish intents become typed controls. Other
learner/session rows stay separate. Close old tabs if a database upgrade is blocked.
No background migration deletes pending recordings or copies access grants.

Controls and uncertain-turn recovery inspect saved state without synthesizing
audio. Opening a saved session also falls back to that text-only state on a speech
502. Only a missing session (404) retries its original saved creation body, including
source, mode and session ID; the current catalogue selection cannot replace it.

## Checks and limits

```bash
npm --prefix apps/web run build
npm --prefix apps/web test -- --run
uv sync --locked --python 3.14
uv run pytest tests/integration/test_resume.py -q
npm --prefix apps/web run test:e2e -- resume
npm --prefix apps/web run test:e2e
```

Controlled-media browser scenarios cover both modes, native taps and hold
(pointer/touch/keyboard), rapid double sends, denial/unsupported/empty/short
capture, late permission, sequential and interrupted playback, blocked playback,
byte-identical retries before commit, recovery after commit, pending finish races,
finish response loss across refresh, and IndexedDB identity/acknowledgement.
They retain synthetic screenshots and traces only. Catalogue regressions run
alongside them on desktop and Android emulation. T19 still requires real Android
recording, autoplay, routing and usability checks; emulation cannot replace them.

The resume suite starts `tests/integration/browser_server.py` as a real loopback
child process, serves the built app and uses synthetic recognition, judgement and
speech. Its external temporary database, grants and content persist across SIGKILL
and restart. Fresh-browser tests change current content/profile and verify the old
cue, assistance and pinned source. Stage tests kill the process during recognition,
judging and synthesis, then recover one accepted turn. This fixture never reads
provider keys, starts live speech or registers a production debug endpoint. Test
roots are separate per scenario and retained outside Git. `VOICE_TEACHER_TEST_PYTHON`
can name the locked interpreter; `VOICE_TEACHER_TEST_REPO` and
`VOICE_TEACHER_TEST_TMP` can locate read-only fixtures and private temporary data in
an isolated test environment. CI installs locked Python dependencies for these
checks; desktop and Android emulation run the same actual-server scenarios.

When running these checks in a read-only container, copy the app and its locked
dependencies into writable scratch space. An executable `tmpfs` is required
there: a default `noexec` mount can reject Vite's npm shim or prevent Rollup's
native module from mapping, before any browser test starts. If the container
cannot execute the npm shim, invoke Vite's installed JavaScript entry point
through Node in the scratch Playwright configuration; keep the submitted config
unchanged. Mount a parent artifact directory and use a child as Playwright's
output directory, since the runner clears that output directory. Keep synthetic
backend state outside Git checkouts. If a host temporary directory inherits an
unrelated Git marker, choose a separate approved temporary root rather than
weakening the Store's code/content separation guard.
