# History and course item practice

T18 exposes read-only, paired-learner history. In the app, **Load history and
progress** fetches the saved server history, including sessions started by
another paired client. **Refresh history** updates it after practice or a sync
retry. Finished and interrupted sessions remain visible. Finishing a session
means the session stopped; it does not prove all its material was covered.

## Coverage rule

Course position means the first lesson with uncovered authored items in the
pinned course's lesson order. A lesson's required item set is the union of its
repetition items and guided-step target items. One supported repetition or
guided observation for the exact original source/course/content revision and
item revision covers that item. Accepted outcomes are `independent`, `repeated`,
`cued`, `modelled_repeated` and `corrected_repeated`. Assisted coverage therefore
counts without changing its assistance label or removing weak-item queue entries.

This is item practice coverage, not a mastery score, a count of communicative
goals passed, or a claim of independent recall. A shared item in multiple goals
still counts once. The app states the rule beside the counts. Lessons without
required items have no item coverage criterion and are not vacuously completed.
An unanswered model, uncertain recognition, skipped goal, `needs_turn` or free
conversation observation contributes no course coverage. Free dialogue cannot
silently advance an entire course unit, even when an observation names a known
item. T21 owns extracting those supported observations, not this query layer.

Each course retains its own source/course/revision group and ordered lessons.
Changing a source or item revision does not reinterpret old observations.
Practice in another source retains and displays both the original reference and
the later practice source; credit belongs to the original pinned item. A newer
superseding event removes an old observation from active coverage, while the
history keeps the old observation visibly labelled as superseded.

## Evidence and privacy

**Evidence for …** opens recorded outcomes, assistance, the recorded attempt,
practised or corrected form, supported reason and original/later provenance.
Every observation links to its actual accepted learner turn in the saved
transcript. A correction is shown as such only for correction assistance,
`corrected_repeated`, or a supported free observation with a preferred form and
reason; recognition uncertainty stays separately labelled. A preferred target
on an ordinary independent/repeated attempt is not automatically called an
error. The successful repetition is shown as the recorded attempt, without
inventing an earlier mistake. Original-session navigation remains available for
cross-session provenance. All text is rendered as text, never repository HTML.

`GET /api/v1/progress?limit=50` returns typed course coverage, recent sessions and
backup counts. Its limit is 1–100 sessions and it explicitly reports when more
sessions exist; coverage uses all saved history. `GET
/api/v1/sessions/{id}/evidence?offset=0&limit=50` pages observations with 1–100 rows
and a nullable `next_offset`. The app's More observations action continues that
page. These APIs never return engine capsules, full curriculum packages, hidden
answer alternatives, learner profiles, provider metadata or filesystem paths.
The authenticated learner determines ownership; unknown/other-owner sessions
return404 and anonymous history reads return401. Reads make no provider call,
Git write or source modification. Browser identity changes clear the view.

## Backup states

Counts distinguish locally saved records, exported records and pushed records.
Export acknowledgement comes from the transactional outbox. Confirmed pushed
IDs come from the existing GitSync worker, filtered to this learner's event IDs;
newer local practice remains locally saved until separately exported/pushed.
A failed push can leave exported work pending remote backup. A failed status
read reports unavailability and makes no new push claim. Errors are sanitized.

An embedding operator may pass the configured `GitSync` instance as
`create_app(..., progress_sync=worker)`; it must use the same runtime store.
This is a read-only status integration and does not start the worker or select
a remote. Without one, the app says remote sync is not configured and still
shows locally saved/exported counts. Private destination selection and hosting
configuration remain explicit operator decisions. No repository is selected,
created or pushed merely by opening history.

## Verification and limits

```bash
uv run pytest tests/progress/test_views.py -q
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e -- progress
```

Synthetic checks cover source/revision isolation, stopped/partial sessions,
repetition versus independent use, supported correction/turn links, historical
provenance and supersession, free/uncertain observations and unanswered models,
owner isolation and pagination. An actual temporary bare Git remote exercises
failed push, exported state, retry, pushed state and newer local practice.
Browser checks exercise both desktop and Android emulation, including an actual
synthetic Python server, rather than only mocked history responses. Real phone
media/usability acceptance remains T19.

This personal-server projection reads the learner's complete saved event history
for coverage; it is not a materialized, indexed analytics service. Recent session
and observation responses are bounded; transcript reads use the existing API.
Larger-history performance and operational budgets remain subjects for T27/T29.
