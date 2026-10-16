# Independent repetition

T13 reads the canonical repetition capability directly. A phrase-only lesson
needs `repetition` in its modes and authored `repetition_item_ids`; it does not
need dummy guided steps, opening routines or recall goals. `plan_lesson` selects
one to six authored items in order (or an explicit subset), keeping stable item
IDs/revisions and stress-marked speech. `plan_queue` selects one or two existing
private weak-item event IDs. Both produce a pinned `RepetitionPlan` verified again
against the session curriculum/learner-owned history before creation.

`Coordinator.create_repetition` uses the existing durable work stages and speech
delivery boundary. The database stays at schema v6. Repetition uses coordinator
capsule v3 with `engine_kind: repetition`; guided v1/v2 capsules remain readable.
Older coordinators reject v3. Recognition reports preserve this version and remain
separate portable annotations across later controls/turns. The repetition snapshot
pins plan/profile hashes and checks phase, position, retry counters and evidence.

## Evidence and recovery

Default practice plays the authored model, accepts a repetition and advances. One
mismatch replays it; a second records `needs_turn` and advances. A match records
`repeated`, never pronunciation accuracy or mastery. No judge is called during
listen-and-repeat. Authored stop words remain valid material; a standalone spoken
stop command closes only when it is not the current target. The app finish control
is always explicit and does not fabricate evidence for an unfinished item.

With `recall_before_model: true`, the meaning/task prompt is shown/spoken before
the answer. The post-attempt judge receives only the current target. Only an
accepted on-task answer at this unexposed stage records `independent`. Any other
verdict supplies the model and switches to repetition; its eventual match remains
`repeated`. A prompt containing the full authored answer is refused for recall.
There is no generated pre-attempt dialogue or confidence heuristic.

Request retries and saved teacher-plan replay reuse existing state/evidence. A
cached judgement survives delivery failure. Pause persists the exact phase/item;
resume replays that item/model or the still-hidden recall prompt without evidence
advancement. Finish is final, as in T06; a paused session can resume. Raw audio and
teacher cache follow T10 and do not enter progress Git.

## Private review queue and provenance

`weak_queue(store, learner)` derives candidate IDs from supported weak outcomes
(`needs_turn`, `skipped`, `cued`, `corrected_repeated`, `modelled_repeated`), ignoring
superseded, disputed recognition and uncertain observations. Repeating a supplied
answer does not retire an existing weak target. A later accepted independent
attempt removes its review candidate; this is an evidence rule, not a mastery or
course-completion claim. No persistent personal queue is written into a lesson
repository.

A queued target keeps its original source snapshot, item revision and original
learner session/turn. The new event's `source`/`practice_source` identify the chosen
current lesson. Original and practice IDs are never merged by text. The original
source snapshot must be available in this learner's history and have the same
language pair as current practice. Another learner's IDs are refused. T11 archive
export/restore resolves both sets of references; selecting/reviewing a queued item
does not update another session, activity or course position. T18 owns the full
course progress UI.

## API

The lesson catalogue now includes `repetition` in `available_modes` for authored
phrase sets with a configured language profile. `Coordinator(..., profiles={
(language, instruction_language): LanguageProfile(...)})` configures additional
pairs; Ukrainian/English remains the default. Provider language support must also
match the selected pair. No profile is inferred from source content.

Start through `POST /api/v1/sessions` with the existing source/course/lesson/session
IDs, `mode: repetition`, default `activity: combined` and optional
`recall_before_model`. `item_ids` selects up to six authored repetition items;
`queue_event_ids` selects up to two private candidates. These options are mutually
exclusive and apply only to repetition. A repetition activity uses its own short
set, not the historical guided sitting numbers.

Authenticated `GET /api/v1/review-items` returns only the current learner's opaque
candidate event IDs, with no hidden targets or profile. Existing text/audio turns,
status and pause/resume/finish controls remain unchanged. The app shell can offer
this mode as soon as the server advertises it. Expanded settings/review selection
and recording controls build on these server contracts in subsequent app tasks.

```bash
uv run pytest tests/practice/test_repetition.py -q
uv run pytest tests -q
```

Tests cover phrase-only subsets, retry/replay, pause/reopen/resume/finish,
post-judgement delivery failure, independent vs exposed repetition, bounded retries,
queue ownership/disputes, cross-source archive roundtrip without another course's
state changes, recognition-report compatibility, configurable profiles, stop-word
material, invalid snapshot recovery and authenticated catalogue/start/queue APIs.
