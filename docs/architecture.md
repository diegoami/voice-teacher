# 3. Target architecture and roadmap

This describes Option C from file 02 with Claude Code (or a scheduled agent)
as the authoring and evaluation back end. It is deliberately concrete so it
can be argued with.

## Guiding principle: rules into code, judgement into the model

Sort every rule in the current controller by who should own it:

| Rule today (controller v4 / checklist) | Owner in the product |
| --- | --- |
| Wait on receipt, start on command (C1, C2) | Gone: the app has a Start button. |
| Full opening, one line per turn, no comments (C3, C4) | State machine. The model is not called during the opening; TTS reads line *k*, the app records the repetition, advances. |
| No praise (C5) | System prompt **and** an output filter that strips a short list of praise phrases before TTS. |
| Scope ≤ 6 phrases, ≤ 2 weak items (C6) | Validation at authoring time (already code) plus the model only sees the brief. |
| Short turns (C7) | `max_tokens` small; a sentence counter that truncates to two sentences. |
| Correction routine (C8) | Model judgement, with a `record_correction(attempt, preferred, reason)` tool so the evidence is structured. |
| Delayed recall without model (C9) | The recall prompts are sent one at a time by the engine; the target sentence is not in context. |
| Ukrainian first (C10) | System prompt; a language detector on the model's output can flag drift. |
| Voice formatting (C11) | Strip markdown before TTS; irrelevant to the model. |
| Clean close (C12) | The engine closes; the model is not asked. |
| Recognition repair (C13) | Language-locked STT makes garbling rare (POC 1: ElevenLabs Scribe v2, 4.2% WER and no Russian on the learner's reading); the STT confidence score drives the repeat request, not the model. |
| Attempt before model (C14) | **Information hiding.** Each guided step carries `teacher_line` and `expected_outcome`; the learner's Ukrainian target is stored but injected into the model's context only after the first attempt has been recorded. |
| Plain spelling (C15) | Two renderings of every phrase: `display` (plain) and `tts` (with stress in the engine's format). The model never sees the marks. |
| Turn counts instead of minutes | A clock and per-phase time budgets. |

What remains for the model is what only a model can do: understand an
imperfect learner sentence, decide whether it is acceptable or needs one
correction, phrase the next question with one changed detail, answer "what
does X mean" in one sentence, and stay in character. That is a much smaller
prompt, and a much smaller checklist, than v4.

## Components

```
┌──────────────────────────────────────────────────────────────────────┐
│ Learner client (web / PWA)                                           │
│  push-to-talk button · stop button · shows plain text of teacher     │
│  turn · optional "show my transcription" · session timer             │
└──────────────┬───────────────────────────────────────────────────────┘
               │ audio chunks / events (WebSocket)
┌──────────────▼───────────────────────────────────────────────────────┐
│ Session engine (server)                                              │
│  phase state machine: opening → guided → recall → close              │
│  per-turn: STT(uk) → engine rules → (model call with tools)          │
│            → post-filters → TTS → stream audio back                  │
│  writes turns + evidence rows as they happen                         │
└───┬──────────────┬──────────────────┬─────────────────────────────────┘
    │              │                  │
 STT service    Claude Messages    TTS service
 (ElevenLabs    API (Sonnet 5      (ElevenLabs /
  Scribe v2 /   default; Opus 5    Google / Azure
  Deepgram)     for evaluation)    Ukrainian voice)
                                     
┌──────────────────────────────────────────────────────────────────────┐
│ Database (SQLite for one user → Postgres)                            │
└──────────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────────┐
│ Authoring & evaluation back end (Claude Code skills today; a         │
│ scheduled Managed Agent or a plain cron job with the API later)      │
│  author next lesson part · verify evidence · run adherence eval ·    │
│  propose prompt version · export Markdown for the repo               │
└──────────────────────────────────────────────────────────────────────┘
```

Model choice: the teacher turn is short and latency-bound, so Sonnet 5 at low
effort with the brief cached is the sensible default; run the adherence
evaluation and authoring on Opus 5, where quality matters and latency does
not. Fable is not needed anywhere in this loop.

## Speech recognition decides the runtime (Session 4A, 2026-09-25)

Changed by the two 4A voice runs in learnukrainian (POC 0 run 2 and the
ChatGPT comparison), measured with POC 1's scorer.

Claude voice mode and ChatGPT Voice taught the same v4 lesson package.
Claude voice mode's speech recognition, with its voice language set to
Ukrainian, turned almost every learner turn into Russian spelling: none of
its 15 opening repetitions was right, word error rate 76%, 22 of 62 words
Russian-spelt. ChatGPT Voice, which is speech-native, wrote down all 12
repetitions exactly and every learner voice turn as Ukrainian. The lesson on
Claude failed because of recognition, not because of the prompt or the
model: a teacher that reads Russian cannot correct Ukrainian.

So the recogniser is the deciding component, and there are now two serious
runtimes for the session engine:

- **A. STT → Claude → TTS** (the diagram above). It keeps Claude as the
  teacher, the rules in code and the cheapest cost per session. It depends
  on a language-locked recogniser hearing *this learner's* Ukrainian as
  Ukrainian. That is POC 1's question, now the first go/no-go.
- **B. A speech-native teacher.** The model hears the audio itself, as
  ChatGPT Voice does. Today that means ChatGPT Voice as a general voice chat,
  which is what the learner uses since 2026-09-26; POC 0 showed that such a
  chat can be handed a lesson but not steered or recorded turn by turn. In
  the own engine it means a speech-to-speech API (OpenAI Realtime or a
  successor) with the engine's state machine driving it through tools and
  per-step instructions, at several times the cost per session of A (see
  the cost table), and with the teacher model no longer Claude.

POC 1 decides the default: if one of the language-locked recognisers is
accurate and stays Ukrainian on the learner's recording, keep A; if all of
them drift as Claude voice mode did, B moves first and POC 5 is built around
a speech-to-speech session. Either way the engine, the evidence and the
evaluation stay the same; only the turn's audio path changes.

**Decided by POC 1 (2026-09-26): A stays the default, with ElevenLabs
Scribe v2 as the recogniser.** On one phone recording of 32 lesson
sentences, Scribe locked to Ukrainian had a 4.2% word error rate, no
Russian-spelt word, and all fourteen lines Claude voice mode had
misrecognised in 4A right. Deepgram Nova-3 reached 17.5%, also without
Russian. The 4A drift was the Claude app's recogniser, not the learner's
pronunciation. B stays the fallback. Still open: OpenAI's recognisers (not
run, no credits), per-turn latency, and whether Scribe keeps real learner
errors in spontaneous speech.

## Data model

The tables below are the current Markdown files made explicit. Names are
suggestions.

```
source            id, name ("Pimsleur review", "Emova", "youtube-vocabulary"), language
syllabus_unit     id, source_id, number, title, coverage_criterion, order        -- "Session 3"
lesson_part       id, unit_id, label ("3A"), main_goal, status                   -- authored brief
item              id, source_id, display, tts, meaning, kind (phrase|vocab|pattern)
lesson_item       lesson_part_id, item_id, role (opening|active|weak|recall)
guided_step       id, lesson_part_id, order, teacher_line_display, teacher_line_tts,
                  expected_outcome (English), target_item_id (hidden until attempt),
                  new_word_meaning (nullable)
prompt_version    id, label ("v4"), system_prompt, hypothesis, created_at
session           id, learner_id, lesson_part_id, prompt_version_id, started_at,
                  ended_at, settings (stt/tts/model/input mode), audio_retained
turn              id, session_id, order, role, text, audio_ref, stt_confidence,
                  phase, step_id
evidence          id, session_id, item_id, state (modelled|repeated|cued|
                  independent|corrected_repeated|needs_turn), attempt, preferred,
                  reason, turn_id
queue_target      id, item_id, original_source_id, origin_label ("Session 2C"),
                  status (active|practised|retired), next_context
queue_history     id, queue_target_id, session_id, practice_source_id, outcome
adherence_result  id, session_id, check_id ("C8"), result (pass|fail|n/a),
                  turn_id, note
```

Rules the schema encodes that today live in prose: provenance is a foreign
key, not a table cell; evidence is append-only (no "aggressive
deduplication" is possible); a unit's coverage is computed from evidence, not
edited; queue targets are selected by query ("active, fits unit 3, not used
in the last two sessions"), not by an LLM reading a file.

Export: a script renders `REVIEW_TRACKER.md`, `REVIEW_QUEUE.md` and
`VOICE_ITERATIONS.md` from the database so the repository keeps its readable
history and nothing already recorded is lost.

## The session engine in more detail

**Opening.** For each opening line: TTS the `tts` rendering; wait for a
push-to-talk turn; STT it; if confidence is low or the transcription has
fewer than half the words, re-say once; store `repeated`; advance. No model
call. This alone retires C1–C5 and most of C13.

**Guided sequence.** For each step: TTS the teacher line; wait; STT. Call
the model with: the small system prompt, the brief (cached), the transcript so
far, the current step's `expected_outcome`, and — only if `attempts ≥ 1` —
the target sentence. The model answers with text plus optional tool calls:

- `accept()` → engine advances.
- `cue(partial)` → engine TTS's the partial cue, increments attempts.
- `correct(attempt, preferred, reason, chunk)` → engine records evidence and
  runs the chunk → sentence routine itself.
- `model_sentence()` → allowed only when `attempts ≥ 2`; otherwise the engine
  rejects the call and asks for a cue. C14 becomes impossible rather than
  discouraged.

**Delayed recall.** Engine sends prompts one at a time; the model judges the
answer; the target is never in context before the first attempt.

**Close.** Engine says the closing line and ends. Any "give me a summary"
is handled by the app UI afterwards, from the database, never by the teacher.

**Stress marks.** Store both renderings. Try, in this order, what the chosen
TTS accepts for Ukrainian stress: the combining acute already used in the
material, SSML `<phoneme>`, or a per-engine stress notation; keep the one
that survives a listening test. The learner-facing text stays plain.

**Audio retention.** Keep learner audio per turn (opt-in). It turns the
current "cannot say whether `хотел бы` was speech or transcription" into a
checkable fact, and it makes pronunciation feedback a future feature instead
of a forbidden inference.

## Cost per 20-minute session (order of magnitude; verify before quoting)

Assumptions: ~40 teacher turns, ~10 minutes of learner audio, ~2,500
characters of teacher speech, brief and system prompt cached, model called
only in guided and recall phases (~25 calls).

| Component | Estimate |
| --- | --- |
| Claude Sonnet 5, ~25 calls, ~4k cached input + ~80 output tokens each | ≈ $0.05–0.15 |
| Claude Opus 5 instead | ≈ $0.15–0.40 |
| Speech-to-text, 10 min (ElevenLabs Scribe / Deepgram, list prices) | ≈ $0.05–0.10 |
| Text-to-speech, ~2,500 characters | ≈ $0.05–0.50 depending on provider and tier |
| **Total, own loop** | **≈ $0.15–1.00** |
| OpenAI Realtime speech-to-speech for comparison (10 min in, 10 min out) | ≈ $3.00 |
| Post-session evaluation (Opus 5, one transcript, checklist + evidence verification) | ≈ $0.10–0.30 |

Cheap enough that a subscription at a few euros a month covers daily use.
The biggest cost driver is TTS provider choice, not the model.

## Roadmap

**Phase 0 — remove the hand-offs (days).** A remote MCP server with
`start_next_lesson`, `next_opening_line`, `record_turn`, `end_session`,
added as a connector; the controller moves to a Claude Project's
instructions. Transcripts land in the server (and are committed to
`voice-sessions/` by a script). This is Option A; it also tells you how well
the voice model uses tools, which decides how much of the engine above must
be server-side.

**Phase 1 — a real store behind the same skills (a week).** SQLite with the
schema above; importers for the current Markdown (tracker, queue,
iterations, sessions); exporters back to Markdown. `/voice-prepare`,
`/voice-record` and `/voice-iterate` read and write the database through a
small CLI instead of editing tables. Nothing changes for the learner yet;
everything becomes queryable and idempotent.

**Phase 2 — automate the evaluation (days).** The C1–C15 checklist as an
LLM-judge eval over `session.turns` with the failing turn cited, run
automatically after each session, results into `adherence_result`. Add a
small regression set of past transcripts so a prompt change can be scored
before it is used live. This is the `build-eval` / hill-climb pattern applied
to the teacher.

**Phase 3 — own voice loop, single user (weeks).** The session engine, a
web client with push-to-talk, STT/TTS integrations, the reduced system
prompt. Run it side by side with the Claude app for a few sessions and
compare adherence results and independent-production counts.

**Phase 4 — product hardening.** Accounts, per-learner profiles (the
hard-coded `LEARNER` becomes a row), content tooling to author a unit from
any material, a second language to prove the engine is generic, billing,
audio retention consent.

## Marketability, honestly

**Who it is for.** Not beginners: returning learners who did a course years
ago (Pimsleur, Duolingo, a class) and want spoken reactivation with a plan,
not another A1 course. Also learners of less-served languages, where the big
apps' catalogues are thin and their speech recognition is weak. Ukrainian is
a good first market for both reasons.

**What is different.** Existing AI tutors (ChatGPT voice, Speak, Praktika,
Langua, TalkPal and similar) are open-ended conversation with a coach
persona. This design is the opposite: a fixed lesson shape, a syllabus with
coverage criteria, evidence instead of scores, a cross-source weak-point
queue with provenance, and a teacher that is evaluated against a checklist
every session. "Bring your own material" (a subtitle file becomes next
week's practice items) is a natural extension because the vocabulary track
already exists in this repository.

**What is not different.** The speech stack is commodity; anyone can wire
STT → LLM → TTS. Defensibility comes from the lesson engine, the evaluation
loop, and the curated content per language, not from the plumbing.

**Risks.**
- STT accuracy on learner-accented Ukrainian was the first go/no-go. In 4A
  Claude voice mode's recogniser turned the learner's Ukrainian into
  Russian; on the learner's own reading, ElevenLabs Scribe locked to
  Ukrainian did not (POC 1: 4.2% WER, no Russian). Read speech is the easy
  case: spontaneous turns with real learner errors are still unmeasured.
- TTS stress handling for Ukrainian may be poor on every provider; the
  listening test in Phase 3 is a go/no-go.
- Latency: three network hops per turn. Streaming STT and streaming TTS keep
  it acceptable; a non-streaming first version will feel slow.
- Content is the long pole for a second language; the engine is not.
- Pimsleur is a trademark; the product cannot use the name and the material
  must stay original (it already is, by design).

## What to keep from this repository, and what to let go

Keep as seed data and specification: `REVIEW_MATERIAL.md`, `REVIEW_PLAN.md`,
`VOICE_OPENINGS.md`, the evidence-label rules, the queue rules, the checklist,
the version log, the three transcripts (they are your first regression set),
and the three skills as the specification of the authoring and recording
agents.

Let go, in this order: the clipboard and share link (Phase 0), Markdown as
the write model (Phase 1), the general-purpose voice chat as the runtime
(Phase 3), and with it about half of controller v4.
