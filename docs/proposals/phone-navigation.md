# Phone navigation proposal

Status: **four-destination structure approved by the owner in the current
session**. The initial navigation implementation is in PR82. The wireframe
remains a synthetic proposal artifact. Individual History-record deep links
below remain proposed; the initial implementation covers the four destinations
and owner-checked active-session links.
Issue [#79](https://github.com/diegoami/voice-teacher/issues/79); contract
[T37](../tasks/T37.md). Open the [interactive wireframe](phone-navigation.html)
in a browser. It contains synthetic placeholders and navigation only.

## Friction and evidence

The owner reported that the deployed phone preview felt overwhelming because
so much material appeared on one page. They also asked for visible recording,
recognized answers and a running conversation (#77), and readable older session
records (#78). We do not have a new observed phone usability test in this task.

Inspection of the current app confirms that pairing/server configuration,
source/course/lesson selection, mode setup, saved sessions, active practice,
recording privacy and History/progress are all siblings on one long page.
Starting or returning to practice can leave unrelated controls above the active
task. History already combines backup status, imported position, item evidence,
completion choices and individual transcripts. Adding live conversation and
legacy archives increases that page's length. These are code/layout observations,
not measured task-completion times or an invented usability study.

## Four destinations

| Destination | Main responsibility | Secondary controls |
| --- | --- | --- |
| Lessons | Continue the current session or choose source → course → lesson/topic → mode → start | Remembered selection; lesson readiness and supported modes; optional topic-only conversation |
| Practice | Active task, teacher speech, explicit microphone state and talk/send/discard controls | Recognized answer, chronological conversation, written feedback; replay/stop; explicit pause/finish; talk style in an expandable control |
| History | Read recent app sessions and separate legacy session records | Transcript/evidence detail; course position; explicit complete/reopen choices; supporting tracker/queue references |
| Settings | Pairing/server connection, recording retention and backup/sync state | Disconnect/change server; advanced diagnostics disclosed on demand |

Use a labelled four-item bottom navigation on phones, with the same destinations
as a labelled top/side navigation on wider screens. Text labels remain visible;
icons, colour and motion are optional decoration. Place **Continue session** at
the top of Lessons and a persistent **Return to practice** link on History and
Settings whenever a session is open. The Practice label shows its state in text
(e.g. paused), without announcing every transcript change.

Default paired landing destination is Lessons, with a continuation card before
the selector. First pairing is a dedicated connection screen. A valid Practice
link opens its session only after authentication and ownership checks; expired
pairing returns to connection with the route retained within that server origin.
No grant, pairing code or learner text belongs in URLs.

## Practice layout

Keep the active task and latest teacher instruction at the top. Directly below,
show the recording/playback state and primary controls. The microphone indicator
means actual capture only; permission pending has different wording. An elapsed
counter appears only during actual capture. At phone sizes, keep the primary
control dock reachable at the bottom of the Practice viewport, above navigation
and the safe-area inset. It must not cover the focused text, keyboard, transcript
or recovery buttons; allow vertical scrolling when height is constrained.

Place the last recognized answer immediately below controls, clearly labelled as
speech recognition. Put the running conversation and written corrections below
that, with a compact **Latest turn** jump control. Keep chronological order and
user-controlled scrolling; do not force-scroll someone reading an earlier turn.
Do not repeatedly announce the whole conversation. Written feedback can load
while teacher speech continues and must preserve immediate/deferred correction
policy. An error in that panel does not disable recording or resend an answer.

Replay, stop playback, pause and finish remain available with text labels. Put
hold-to-talk preference and longer explanations in **Practice options**. Keep
pending-upload recovery/discard controls visible when needed; they are not
advanced settings. Starting a second session requires an explicit choice to
pause or finish the current session and resolution of pending capture/upload.
Changing lesson selection alone never alters a running session's pinned source.

## Principal journeys

1. **Choose and start:** Lessons remembers the source/course/lesson and mode.
   Show availability/readiness there. Start commits one durable start intent,
   then opens Practice. A failed response offers recovery of that same intent.
   Choosing a new source never rewrites the active session.
2. **Continue:** Lessons → Continue, or Return to practice from another page,
   loads the original session ID and current server presentation. Preserve its
   pinned lesson revision, selected policy, activity and request journal. A
   different paired learner must not see the previous learner's session.
3. **Speak and read feedback:** Practice shows permission → actual capture →
   finishing/saving → processing → teacher playback → ready. Recognized text
   appears only from accepted server turns. Teacher speech and written feedback
   are independent. Controls and recovery remain reachable while reading.
4. **Finish and move on:** Explicit Finish ends practice and shows a short saved
   result with **Choose next lesson**. Lesson completion is a separate explicit
   learner decision, with Complete/Reopen controls and an explanation that item
   coverage/weak-item evidence remain separate. Finishing does not silently
   complete the lesson. Next selection respects the approved imported position.
5. **Read History:** default to recent app sessions. A separate **Legacy sessions**
   view lists imported original records and states when only a summary or no
   transcript is available. Tracker/queue references have their own section.
   Source provenance and unresolved mapping remain inspectable. Neither reading
   old text nor opening a record creates a new lesson or practice turn.
6. **Settings:** show recording retention, pairing/server and backup state here.
   Changing a server/disconnecting requires resolving active capture and pending
   upload first. Do not forward credentials to a new origin. Preserve existing
   learner-bound journals and explicit privacy consent/revocation semantics.

## Back, deep links and pending audio

Use same-origin fragment routes for the first implementation:
`#/lessons`, `#/practice/<session-id>`, `#/history`,
`#/history/session/<session-id>`, `#/history/legacy/<opaque-id>` and `#/settings`.
Fragments permit refresh through the existing static asset server. Validate every
identifier and reject unsupported routes with a labelled route-not-found view and
an explicit Lessons link. A missing/foreign session or legacy ID shows an
unavailable detail, never a fabricated session or arbitrary filesystem lookup.

Ordinary navigation, browser Back/Forward and refresh must not implicitly finish
or pause a server session. Within an authenticated account, keep a single voice
controller outside destination panels so route rendering cannot dispose its
recorder or journal. Stop teacher playback when leaving Practice; returning does
not autoplay. This policy changes playback only, not the durable lesson step.

If navigation is attempted during permission request or actual capture, cancel
that navigation until the learner explicitly chooses **Stay**, **Discard recording
and leave**, or (after capture started) **Send answer and leave**. Browser Back
must restore the current route while this choice is pending; do not add duplicate
history entries. Pending uploads continue under the same account/controller;
show **Answer saving — return to practice** and use the existing receipt recovery.
If a connection fails, keep its recover/discard controls on Practice. Never start
another recording or replace a pending request ID due to a route change.

A full page close/refresh cannot rely on a custom dialog or completing async work.
Warn with the browser's standard unload prompt during an uncommitted capture;
state honestly that live capture is not recoverable across a killed page.
Already journaled uploads retain the existing durable IndexedDB recovery. On
refresh, reauthenticate and load the current server state/receipt before enabling
recording. Do not describe that as preservation of unsaved microphone buffers.

On destination change, focus the destination heading once. Back from a detail
restores its parent list and originating item when available. User-triggered
navigation may announce the new heading; growing conversation text stays outside
live announcements. Reduced motion requires no animation or smooth scrolling.

## Scope after owner review

The wireframe illustrates page responsibilities, not the production app. It does
not pair, record, import, save or expose real History. Owner agreement with the
four destinations does not waive the detailed audio/auth recovery requirements.

A separately bounded navigation implementation must keep the existing single
voice owner, preserve account/source selection and explicit completion actions,
and add browser checks for route validation, focus, Back/Forward, reload and
pending capture/upload/receipt recovery. Integrate T35/T36 after their review,
then test the whole flow together. Do not mark the current app as restructured
because this document or the clickable wireframe exists.

**Still incomplete:** owner review of this proposed structure, implementation
contract and product code, applicable production navigation checks, and actual
phone acceptance of readability and comfortable control reach. Emulated checks
of a synthetic wireframe establish only that the proposal can be inspected.
