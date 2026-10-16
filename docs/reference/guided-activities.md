# Guided conversation and saved activities

T14 plans independent guided practice directly from pinned canonical goals.
A guided lesson needs authored `guided_steps`; opening repetition and recall
are optional. The default routine starts a scenario immediately. A combined
routine deliberately adds the authored review set and new-sentence modelling.
No dialogue generator runs before an attempt: teacher speech comes from the
authored teacher line and communicative task, without passing hidden target
renderings to another model. The post-attempt judge receives offered answers.

## Planning and presentation

`plan_guided(snapshot, course_id, lesson_id, ...)` returns a private `GuidedPlan`.
The coordinator recompiles it against the session's pinned curriculum before
writing anything. The API accepts these guided options on `POST /api/v1/sessions`:

| Option | Default | Behaviour |
| --- | --- | --- |
| `routine` | `guided` | `combined` requires authored repetition capability |
| `cards` | `true` | Task cards in the first sitting; answers remain hidden |
| `spoken_tasks` | `true` | Speak the first sitting's communicative task |
| `max_goals` | `3` | One to six scenario or recall goals per activity |
| `activity` | `combined` | Both sittings; or `first_sitting` / `second_sitting` |

Here `activity` selects which sittings to plan; `routine` selects whether to add
modelling. Repetition rejects guided options that differ from their defaults.
The app shell currently uses the default options; T16/T17 own session controls.

Combined opening review is split into activities of at most six authored items,
without truncating the set. Each first-sitting scenario block then models its
new sentences before the task-card round. Guided-only blocks skip modelling.
All first-sitting blocks precede all second-sitting blocks. The second sitting
uses the same goals without cards or spoken tasks. Delayed recall follows all
scenario blocks, in separate bounded activities, retaining every authored recall
ID, including goals involving items from different blocks. These are turn-count
bounds, not guarantees of minutes or fixed counts after retries.

Activity completion automatically saves a `paused` session, with `done=false`
when another activity remains. Resume starts the exact next block. A manual
pause within a block retains counters, attempts, cue/correction/model state,
and replays the last planned teacher speech on resume. Neither replay adds an
attempt or resets help. Finish and a spoken stop end the entire session, even
at a boundary. Authored stop phrases can still be practised as exact answers.

Public presentations add nullable `activity: {activity_id, position, total,
complete}`. Positions start at zero. Goals, answer alternatives, plan snapshots
and provider metadata stay private. Activity completion describes practice,
not mastery. Immutable activity descriptors and the full current plan are saved
with the source revision; changing the active source cannot rewrite them.

## Evidence and target hiding

Social replies do not consume a goal or an attempt. A recognized later step
skips intervening goals explicitly; prior help on that turn remains recorded
conservatively instead of upgrading the new goal to independent. A contradictory
`accept` verdict marked off-task cannot earn accepted-goal credit. One meaningful correction or partial cue
precedes a full model; modelling is recorded as help. A clarification that
would disclose a whole offered answer, or a one-word cue that is already the
whole answer, becomes an explicit model instead of uncredited help. Disabling
cards does not substitute hidden answers. Plans whose teacher/task/recall text
already includes its whole offered answer are refused before session creation.

An accepted goal does not prove which authored item was used. Only an exact
normalized match to an offered rendering with one unambiguous explicit item ID
receives that item's credit. Equal text under different IDs, or an accepted
paraphrase without an offered match, retains the accepted outcome and original
learner turn, phase, goal position, assistance and pinned plan, with no preferred
answer or original-item attribution. Source/course practice provenance remains.
These unattributed observations cannot invent weak-item queue entries. Matching
an intentional model retains that model's item and an assisted label.

Canonical guided steps may optionally specify boolean `open_answer` (default
false). The legacy adapter retains its reviewed value in the compiled snapshot,
so refreshing a legacy source no longer loses this judging policy. This adds
an optional field to schema v1: existing documents remain readable; old readers
with strict field allowlists reject newly emitted documents containing it.
Existing pinned sources without it keep the prior canonical false default.

## Recovery compatibility and verification

New guided sessions use coordinator capsule v4 (`engine_kind=guided`). Capsules
v1/v2 (legacy guided) and v3 (repetition) remain readable. Recognition reports
retain capsule v4 and do not advance activities. Native guided engine snapshots
now write v2 for non-first or unknown item attribution and read v1/v2. Old
history keeps its recorded item credit; it is not retroactively reinterpreted.
Older engines reject v2 rather than silently replacing unknown credit. SQLite
and exported session/event envelope versions are unchanged.

The configured language profile is pinned. Operator code can supply a mapping
of instruction-language activity closing messages via
`Coordinator(..., guided_activity_endings={...})`; English has a built-in message.
Other instruction languages require an explicit closing plus a configured profile.
Curriculum does not provide teaching policy or operational instructions.

```bash
uv run pytest tests/practice/test_guided.py -q
uv run pytest tests/engine tests/api tests/content -q
uv run pytest tests -q
```

Tests use synthetic content, a scripted judge, real fresh-process resume,
archive roundtrips and injected delivery failures. They do not claim live
speech validation or Android usability; the required phone gate belongs to T19.
