# Phone destinations

The owner selected the four-destination structure during T37 in PR82, after
reviewing the [proposal and synthetic wireframe](../proposals/phone-navigation.md).

- **Lessons:** current-session continuation and source/course/lesson/mode setup.
  A current active session must be explicitly paused or finished before starting
  another. Selecting a different source leaves its pinned lesson unchanged.
- **Practice:** active task, teacher text, voice state and controls. Phone layouts
  keep talk and stop-playback controls above the bottom navigation. A single
  controller remains mounted while other destinations are displayed.
- **History:** recent app sessions, transcript/evidence and recording status.
  Course position and explicit completion/reopening are in an expandable section.
  T36 adds the separate legacy archive here when that dependency is integrated.
- **Settings:** server/pairing, recording retention and backup/sync status. Reads
  are on demand. Capture, saving and pending requests prevent disconnect/server
  replacement until resolved in Practice.

The four same-origin routes are `#/lessons`, `#/practice`, `#/history` and
`#/settings`. An active session has an owner-checked `#/practice/<session-id>`
link. Refresh verifies the paired identity and loads the server presentation
without preparing speech merely for navigation. A missing/foreign session is
unavailable; a route alone never creates a session. Unknown routes show an
explicit Lessons link. Credentials and learner text never enter these URLs.
Individual History-record deep links remain proposed; History detail currently
stays mounted across destination changes and its in-page supporting-turn links
focus/scroll to the retained transcript without replacing the destination route.

Back/Forward and ordinary navigation do not finish or pause server sessions.
While permission or capture is active, a modal offers Stay or Discard and leave;
after capture starts it also offers Send answer and leave. A blocked Back restores
the current entry without adding history entries. Live capture is not durable
across page termination: the browser warns during permission/capture/saving.
Already journaled uploads retain existing IndexedDB/receipt recovery. Sending
while leaving preserves the same controller/request and never autoplays teacher
speech in a hidden Practice page. Returning does not autoplay either. Explicit
Open remains available for reloading a saved session once pending work is resolved.

Destination changes focus the heading. Native modal focus containment is used,
and focus returns to the destination after confirming navigation. Text labels,
visible active navigation and touch-size controls do not depend on animation.
Paired learner changes clear old session state; a different learner's deep link
cannot bypass server ownership checks. Source selection and learner-bound journals
remain separate from navigation. No source/progress migration is performed.

T37's full browser suite passed 120 checks across desktop and Android emulation,
including actual synthetic-server restart, recording, receipt/control recovery,
retention, course choice, authentication isolation and new navigation checks.
Wireframe checks and synthetic screenshots are separate evidence, not a real-phone
usability test. T35's live conversation and T36's legacy archive retain their own
PRs/contracts and must be integrated before combined acceptance.

**Incomplete:** individual History-record deep links, combined dependency/phone
acceptance and the existing independent merge gate. Do not mark real-phone
readability/control reach, microphone/unscripted acceptance or new historical
imports complete from these browser results.
