# Proofs of concept

Each POC answers one question the architecture depends on. They are ordered
by how much they de-risk per day of work. A POC is done when its question
has a written answer in its own `README.md`, with evidence.

| # | Directory | Question | Done when |
| --- | --- | --- | --- |
| 0 | `00-mcp-connector/` | Can the Claude app's voice mode drive a lesson through a remote MCP connector (start lesson, next opening line, record turn, end session) reliably enough to replace clipboard and share link? | One real voice session run end to end through the connector; transcript captured server-side; a note on which tool calls the voice model actually made and missed. |
| 1 | `01-stt-ukrainian/` | How accurate is language-locked speech-to-text on *this learner's* accented Ukrainian? | Word error rate and Russian-spelt words per provider (ElevenLabs Scribe v2, OpenAI `gpt-transcribe` and `gpt-4o-transcribe`, optionally Deepgram Nova-3) on one phone recording of a 32-sentence reading list, with Claude voice mode and ChatGPT Voice in Session 4A as the comparison. |
| 2 | `02-tts-stress/` | Does any TTS model place Ukrainian stress correctly, with plain text or with the material's stress marks? | Fifteen sentences (4A lesson lines and Ukrainian/Russian stress traps) rendered by three ElevenLabs models and OpenAI `gpt-4o-mini-tts`, plain and marked; blind listening verdict per target word per variant. |
| 3 | `03-session-store/` | Can the current Markdown records (tracker, queue, iterations, sessions) round-trip through the relational schema without losing anything? | SQLite database built by an importer; exporter regenerates the Markdown; diff is empty or explained. |
| 4 | `04-adherence-eval/` | Can the C1–C15 checklist be scored automatically from a transcript with the failing turn cited, matching the hand-scored rows in `VOICE_ITERATIONS.md`? | Agreement per check on the 2B and 2C transcripts; disagreements explained. |
| 5 | `05-session-engine/` | Does an engine that owns the turn loop (state machine, small Claude prompt, target withheld until the first attempt) produce more independent production than controller v4, at an acceptable turn latency with Scribe and Multilingual v2? | One real voice lesson through the engine; independent productions per guided step compared with the v4 runs (3A, 4A on Claude and ChatGPT); turn latency and cost per lesson logged. |

Status (2026-09-26): POC 0 answered (the connector delivers a lesson; it cannot
record or steer one). POC 1 answered: locked to Ukrainian, ElevenLabs Scribe v2 hears the
learner's Ukrainian as Ukrainian (4.2% WER, no Russian) and keeps the
learner's mistakes (12 of 18 planted, 2 corrected), so STT → Claude → TTS
stays the default runtime with Scribe as the recogniser (see
`docs/architecture.md`). POC 2 answered: ElevenLabs Multilingual v2
with stress-marked text places Ukrainian stress right (0 of 28 judged words
wrong); `у мене́` needs a pronunciation fix. POC 5 planned (milestones in its README).

POCs 1 and 2 are the go/no-go items; run them early even though they are
small. POCs 3 and 4 make the existing skills cheaper without touching the
learner experience. POC 5 is the product.
