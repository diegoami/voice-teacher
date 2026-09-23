# Proofs of concept

Each POC answers one question the architecture depends on. They are ordered
by how much they de-risk per day of work. A POC is done when its question
has a written answer in its own `README.md`, with evidence.

| # | Directory | Question | Done when |
| --- | --- | --- | --- |
| 0 | `00-mcp-connector/` | Can the Claude app's voice mode drive a lesson through a remote MCP connector (start lesson, next opening line, record turn, end session) reliably enough to replace clipboard and share link? | One real voice session run end to end through the connector; transcript captured server-side; a note on which tool calls the voice model actually made and missed. |
| 1 | `01-stt-ukrainian/` | How accurate is language-locked speech-to-text on *this learner's* accented Ukrainian? | Word error rate on the audio of one session for two providers (e.g. ElevenLabs Scribe v2, Deepgram Nova-3), with the garbled turns from the 2B/2C transcripts as the comparison. |
| 2 | `02-tts-stress/` | Does any TTS provider place Ukrainian stress correctly when given the accented text from `VOICE_OPENINGS.md` (or SSML/phonemes)? | The eleven Session 3 opening lines rendered by two or three providers; listening verdict per line per provider. |
| 3 | `03-session-store/` | Can the current Markdown records (tracker, queue, iterations, sessions) round-trip through the relational schema without losing anything? | SQLite database built by an importer; exporter regenerates the Markdown; diff is empty or explained. |
| 4 | `04-adherence-eval/` | Can the C1–C15 checklist be scored automatically from a transcript with the failing turn cited, matching the hand-scored rows in `VOICE_ITERATIONS.md`? | Agreement per check on the 2B and 2C transcripts; disagreements explained. |
| 5 | `05-session-engine/` | Does a state machine plus a small teacher prompt, with the learner's target withheld until an attempt, produce more independent production than controller v4? | A text-only run of one lesson part against the engine, then a voice run; evidence counts compared with 2C. |

Status: POC 0 built, awaiting its first voice session (2026-09-23).

POCs 1 and 2 are the go/no-go items; run them early even though they are
small. POCs 3 and 4 make the existing skills cheaper without touching the
learner experience. POC 5 is the product.
