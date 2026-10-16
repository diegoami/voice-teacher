# Product practice engine

The root Python project installs `voice_teacher` from `server/voice_teacher`.
Python 3.12 or newer and uv are required. From a fresh checkout:

```bash
uv sync --locked
uv run pytest tests/engine tests/contracts -q
```

The core needs no provider credentials, lesson checkout or network access.
Engine tests replace network entry points with failures. Their lesson material
is synthetic, including a 12-step, nine-target representative sequence.
The preserved POC remains independently runnable:

```bash
cd pocs/05-session-engine
uv sync --locked
.venv/bin/python -m pytest -q
```

## Boundaries

`voice_teacher.practice.Lesson` is a prepared runtime input, distinct from the
versioned repository manifest in [data-formats.md](data-formats.md). It requires
explicit source, course, lesson and item identities. T07 will adapt content
repositories into this input. The engine never opens a sibling directory or
infers identity from the target text. Repeated occurrences of one item share
the round-zero presentation; distinct IDs with identical text remain distinct.

Pass `Lesson`, a callable `Judge` and optionally a `LanguageProfile` and clock
to `Session`. Call `start()` once, then `hear(transcribed_text)` for each turn.
Both return `Say` objects: `text` preserves authored stress for speech and
`display` removes only the profile's specified stress mark. `session.card`
contains the current instruction; `done` indicates closure. Hearing before
start or after closure raises `RuntimeError`.

The `providers` module defines judge, speech-recognition, speech-synthesis and
session-store protocols, with no network clients. Speech is orchestrated by the
caller; the synchronous engine consumes text and returns teacher turns.
Judge inputs include targets only after a learner turn. Evidence and logs may
contain private learner text and belong in private runtime storage.

`snapshot()` returns a JSON capsule; `save(store, session_id)` hands it to an
injected store. `Session.from_snapshot(lesson, judge, capsule, profile=...)`
restores phase, position, help, repeat retries, history, evidence and logs. It
checks the capsule version and lesson/profile fingerprints, so the caller must
keep the exact prepared inputs pinned. This interface does not implement
atomic persistence or concurrency control; T05/T06 own those guarantees.

## Preserved behaviour

The Ukrainian profile retains the measured POC phrases, stop prefixes,
stress normalization and English task cards. The phase order is opening
repetition, new-target repetition, guided conversation with cards, guided
conversation without cards, delayed recall and close. `part="1"` closes after
the first guided round; `part="2"` starts without cards and includes recall.

The port keeps the repetition tolerance, one retry, four-step lookahead,
social/question handling, first-error cue or short correction, whole-sentence
correction guard, second-error full model, and evidence labels. Explicit source
and item identities and separate display text are additive. Unlike the POC's
text-based deduplication, round zero groups by explicit item ID. Existing POC
files are unchanged. Provider implementations, stress enrichment of generated
speech, selectable practice modes and durable storage remain later tasks.
