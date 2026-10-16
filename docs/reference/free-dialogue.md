# Bounded free conversation

T20 adds a separate text-dialogue component, rather than reusing the fixed-answer
judge. Its context has a topic, the pinned learner level, target/instruction
languages and recent conversation. A selected lesson can contribute its public
title and up to six communicative goals; its hidden target renderings and private
legacy context are excluded. Free conversation also works without a repository.
It records accepted learner turns and teacher replies, with no automatic item,
lesson-completion or mastery evidence. T21 owns supported observations/feedback;
T22 owns the complete topic/preference UI and live quality gate.

The confirmed default correction preference is `light_immediate`. The alternative
is `end_of_session`, selectable when creating a conversation. The provider is told
to offer at most one clear immediate correction, or defer corrections respectively;
T21 adds independently supported feedback. This task does not claim that generated
corrections have been verified simply because the dialogue provider said them.

## Configuration and API

The dialogue provider is optional and explicitly configured. Use
`--dialogue-model <provider/model>` or `VOICE_TEACHER_DIALOGUE_MODEL`; it reuses the
server's private `OPENROUTER_API_KEY`, without defaulting to the selected judge
model. Construction/import/health checks do not call providers. An unconfigured
server continues to report free conversation unavailable. Select a model with
strict structured-output support; incompatible responses fail without fallback.
The current adapter follows [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs)
and the [chat completion API](https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request).

After pairing, create a source-free conversation with:

```json
{
  "session_id": "client-generated-uuid",
  "mode": "free_conversation",
  "topic": "Train travel",
  "language": "uk",
  "instruction_language": "en",
  "correction_style": "light_immediate"
}
```

Alternatively provide the complete `source_id`, `course_id`, `lesson_id` triple.
The lesson must author free conversation and its language pair must be configured.
Its authored topic is the default; an explicit short topic may override it.
Partial references, conflicting explicit languages and lesson-practice-only
options are refused. Guided/repetition still require their complete lesson
reference. Topic length is at most 500 characters. Public responses keep the
existing presentation allowlist: no profile, provider settings or hidden source
content is returned.

## Policy and context boundaries

A trusted `FreePolicy` and language profile are pinned in the plan. The built-in
pair is uk/en; operator code can configure another `FreePolicy`/`LanguageProfile`
pair and localized opening, pause, limit and closing text. This adds no fields to
existing language profiles or their historical hashes. Only the learner's `level`
enters model context; unrelated profile fields and other sessions do not.

The provider receives one trusted system instruction and one JSON data message.
Curriculum, profile values, prior utterances and the current learner turn remain
data. There are no tool definitions, tool execution loop, repository scripts,
server-control fields or plugin capabilities. Output must be a strict object
containing only nonempty `text`. Tool/function calls, refusal, truncated output,
unknown fields and invalid JSON are rejected. Generated text can be spoken and
saved, but cannot invoke a command, close a session or write course progress.
These are structural boundaries, not a claim of perfect model adherence to prose.

Each request includes at most eight recent utterances and 12,000 history
characters, plus the current turn (up to 8,000 characters), bounded topic/goals
and level. JSON input is capped at 128 KiB. The provider makes one HTTP call,
with a default 20-second timeout, no redirects or automatic retry, a 64 KiB
response limit and 256 completion tokens (configured range 64–512). A teacher
reply is capped at 1,200 characters. Unknown usage stays absent; only supported
finite nonnegative numeric usage fields are retained.

Conversation defaults to twelve generated replies (operator limit 1–30). At the
limit it saves a paused boundary and offers finish/new conversation; resume does
not silently extend the limit. Exact configured stop/pause phrases, including
ordinary polite stop requests, are handled before generation. Mentioning a stop
word in another sentence does not itself end the conversation. App finish/pause
controls remain engine-owned and make no dialogue call. Resume replays the last
conversation reply with the same history; no new learner attempt is invented.

## Durability and compatibility

The existing request journal accepts input before calling the provider outside
SQLite transactions, then saves the typed reply before committing history,
progress events, presentation and export jobs together. After a crash, a saved
reply can be committed in a fresh process without the original provider or
another model call. A provider failure leaves the conversation snapshot unchanged;
retry uses the original request ID and text. Committed delivery failure replays
that reply without another accepted learner turn. Remote billing cannot be exactly
once if a process dies after the provider answered but before its reply was saved.

The provider/model/policy/token-limit identity is pinned. A changed provider
cannot silently generate the next reply; restoring the configured identity or
finishing remains possible. Stop/pause and saved-decision recovery work without
a currently configured dialogue provider. Profile or source refresh does not
replace an existing conversation's level, goals, topic, language or policy.

New conversations use coordinator capsule v5 and a strict native snapshot with
plan/profile hashes, phase, bounded history, reply decisions and presentation.
Older guided/repetition capsules v1–v4 remain readable. Recognition annotations
retain v5 through subsequent turns. SQLite and session/progress envelope versions
remain unchanged. Source-free events and activity descriptors survive the same
private archive roundtrip as repository-grounded practice. No credentials or raw
recordings enter these snapshots; generated speech stress for novel words still
needs the live T22 assessment.

```bash
uv run pytest tests/practice/test_free_dialogue.py tests/providers/test_dialogue.py -q
uv run pytest tests -q
```

All fixtures, HTTP providers and recordings in these tests are synthetic. Checks
include real fresh-process reply recovery, archive restore, privacy allowlists,
context/token/HTTP bounds, explicit controls, source-free/source-grounded turns,
changed-provider refusal and instruction-language policy. No live model quality,
real phone behavior or private remote writes are claimed by these checks.

T21 adds the separate [post-attempt feedback boundary](free-feedback.md), private
observations and deliberate personal review. New configured conversations use
coordinator capsule 6; older capsule 5 histories retain their original behavior.
The dialogue generator still receives no hidden target renderings. Structural
observation checks do not substitute for T22's linguistic-quality evaluation.
