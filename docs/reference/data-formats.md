# Version 1 interchange contracts

T03 defines reusable curriculum, private session snapshots and immutable
progress-event envelopes. This is a format/validation layer; it does not add
storage, a teaching engine, source discovery or Git synchronization.

Canonical schemas live in [schemas/v1](../../schemas/v1/common.json), using
JSON Schema draft 2020-12. Their `.invalid` identifiers are registry keys,
not URLs to fetch. The Python validator resolves every reference locally.

```bash
uv sync --locked
uv run pytest tests/contracts -q
```

The root project is not packaged yet. Python 3.12+ and locked dependencies
provide the contract checks before T04 extracts the product engine. Existing
POCs keep their own environments and test configuration. Format-validation
extras are required: a bare jsonschema install can silently omit timestamp
format checks.

```python
import json
from schemas.validate import validate_curriculum, validate_session, validate_event_stream

curriculum = json.loads(open("tests/contracts/fixtures/guided.json", encoding="utf-8").read())
validate_curriculum(curriculum)
snapshot = json.loads(open("tests/contracts/fixtures/session.json", encoding="utf-8").read())
validate_session(snapshot)
events = json.loads(open("tests/contracts/fixtures/progress.json", encoding="utf-8").read())
validate_event_stream(events)
```

All supplied fixtures are synthetic. JSON schemas check shapes and fields;
the Python validators additionally check identities, references, capabilities,
snapshot hashes and stream ordering. Consumers must run both layers. Errors
identify a JSON location; structural diagnostics avoid dumping whole private
payloads. Do not treat an error as safe public telemetry without considering
its field names and semantic IDs.

## Identity and revisions

| Entity | Stable identity |
| --- | --- |
| Registered catalogue | `source_id` |
| Course | `(source_id, course_id)` |
| Item | `(source_id, course_id, item_id)` |
| Lesson | `(source_id, course_id, lesson_id)` |
| Guided step | `(source_id, course_id, lesson_id, step_id)` |
| Recall goal | `(source_id, course_id, lesson_id, goal_id)` |
| Session / turn | `(learner_id, session_id)` / `(learner_id, session_id, turn_id)` |
| Progress event | Globally unique `event_id` |

IDs are authored strings, not inferred from text or folder names. A source
namespace remains stable if its remote URL or local path changes. Identical
local item IDs in different courses or sources remain distinct. Repeated IDs
within the same entity namespace fail. Guided-step and recall-goal namespaces
are separate. A catalogue registration may activate only one package per
source namespace; T08 manages revision activation.

`item_revision` starts at one. Preserve an item's ID through spelling changes
and increase its revision when its rendering changes. Substantial meaning
changes need a new ID or an explicit later migration map. Deciding whether
meaning changed is an authoring responsibility; the validator cannot infer it.

A pinned `source` reference contains source/course/lesson IDs and `revision`:

- `commit`: full lowercase 40- or 64-hex Git object ID, or null for an explicit
  uncommitted snapshot. Clean content requires a commit.
- `content_sha256`: SHA-256 of the compiled curriculum package, serialized by
  `canonical_json` as UTF-8, sorted object keys, compact separators, preserved
  Unicode, no non-finite numbers. Array order is significant.
- `dirty`: whether the snapshot includes uncommitted content. A dirty snapshot
  can also retain its base commit; its hash identifies the actual content.

This hash covers the compiled reusable curriculum, not its original Markdown
bytes, filesystem metadata, learner profile or engine state. T07/T08 preserve
original source provenance and verify Git commits. Schema validation alone
does not prove a claimed commit exists in a repository.

## Reusable curriculum

[curriculum.json](../../schemas/v1/curriculum.json) represents one source,
its courses, course-level items and lesson capabilities. Course-level items
can be reused by several lessons without creating new identities. Each course
declares target and instruction language tags. No language is hard-coded.

Each item has separate `display` and `speech` text plus a meaning. Renderings
are preserved exactly, including authored combining stress marks. Validation
does not rewrite Unicode or guess pronunciation. Authors supply appropriate
learner-facing spelling separately from speech notation.

Lessons declare supported modes:

- `repetition` requires nonempty `repetition_item_ids`.
- `guided_conversation` requires guided steps, each with teacher renderings,
  a goal and target item references; recall goals have their own IDs/prompts.
- `free_conversation` requires a topic and may have no curriculum items.

All item references must resolve within the selected course. Targets belong
in server-side curriculum; this interchange package is not a safe client API
response. T09 and the mode tasks control target disclosure.

Every curriculum object has a closed field set. Learner profiles, personal
progress or other extra object fields are rejected at all defined levels.
This structural separation does not detect personal information deliberately
written into an ordinary text field; source preparation/review still matters.

## Private session snapshots

[session.json](../../schemas/v1/session.json) contains learner/session IDs,
mode/status, monotonically increasing state `revision`, last applied
`event_sequence`, pinned source and the complete reusable `curriculum_snapshot`.
The validator checks selected source/course/lesson/mode/languages and compiled
content hash against the embedded package. Checkout changes cannot reinterpret
this snapshot.

The learner profile is a separate private JSON object. `engine_state` is an
explicit version-1 capsule whose `data` is JSON owned by the engine. T04 defines
its mode/state semantics; this contract guarantees lossless storage rather
than pretending to validate an engine that has not been extracted. Unknown
capsule versions fail. Raw bytes and arbitrary Python values are rejected.

Source-free sessions are restricted to free conversation, with an explicit
topic/languages and null source/curriculum. A source-backed session must use
a lesson-supported mode. Changing a session's mode or pinned source requires
a separate session.

## Private progress events

[progress.json](../../schemas/v1/progress.json) defines `schema_version: 1`,
learner/session identity, event ID, positive per-session sequence, timestamp
with timezone, mode, source, turn reference/text, assistance, provenance,
optional evidence and optional snapshot. No raw recording field is provided.
Progress/transcripts/snapshots belong only in a verified private destination.

| Event type | Required behavior |
| --- | --- |
| `state.saved` | Carries a validated session snapshot with matching learner/session/mode/source and event sequence |
| `turn.accepted` | Carries learner turn text and assistance state |
| `teacher.reply_planned` | Introduces a teacher turn and its saved text |
| `teacher.reply_delivered` | References that same planned teacher turn |
| `evidence.recorded` | References an accepted learner turn and carries outcome/attempt/recognition-uncertainty evidence |
| `observation.superseded` | References an earlier observation event ID; cannot supersede itself |

Assistance records kind, help level and whether the target was exposed.
An exposed/modelled/cued answer cannot be labelled independent. Outcomes
describe observed use, help and repetitions; there is no mastery score or
pronunciation inference. A corrected observation is a supersession event plus
new evidence, preserving the original record rather than editing it.

Provenance preserves `original_source` and its pinned revision, optional
`original_item`, origin session/turn, and the current `practice_source`.
The current practice source must equal the event source; a known original
item must agree with its original source/course. Different original/practice
sources are intentional. Source-free observations can have null original
source/item; later review targets retain their original session/turn.

`validate_event_stream` requires unique event IDs, contiguous sequences starting
at one per session, fixed mode/source per session, increasing saved-state
revisions and consistent turn contents. Learner acceptance/teacher planning
introduce turn IDs only once; later evidence/delivery must reference those
turns and preserve the assistance recorded at acceptance. State snapshots
cannot manufacture accepted attempts. An explicit
`partial=True` allows a batch to start later and defer missing earlier-turn
resolution; it still checks internal ordering and contradictions.

Original provenance and superseded event references may point into a different
archive segment. T11 must resolve them against the complete private archive
before activating projections. Shape validation or a partial-batch pass is
not proof that those historical records exist. Database constraints, export
deduplication, transactional updates and actual append-only storage belong to
T05/T11/T12, not this validator.

Unknown interchange `schema_version` values fail. Unknown event types/fields
also fail; evolve formats deliberately with new versioned schemas and explicit
adapters instead of silently discarding new data. Private engine capsules and
the outer interchange envelope have separate version boundaries.
