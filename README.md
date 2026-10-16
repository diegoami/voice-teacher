# voice-teacher

A spoken-lesson engine for reactivating a language learnt earlier: fixed
lesson shape (presentation → guided substitution → delayed recall → close),
coverage tracking with transcript-observable evidence, a cross-source
weak-point queue with provenance, and a teacher that is evaluated against a
checklist after every session.

This repository holds the **architecture and the proofs of concept**. It
grows out of the manual Claude-Code ↔ Claude-voice loop in
[diegoami/learnukrainian](https://github.com/diegoami/learnukrainian)
(`pimsleur-review/`), where the analysis that led here lives under
`docs/product/`.

## Related repositories

| Repository | Holds |
| --- | --- |
| `learnukrainian` | The Ukrainian curriculum (material, plan, openings), the current voice-teacher prompt and its iteration log, the recorded sessions, tracker and shared queue. Seed data and regression transcripts for this engine. |
| `ukrainian-vocabulary` | The vocabulary list harvested from media, split out of `learnukrainian` on 2026-09-25. A future source of practice items. |
| `language-learning-tools` | Vocabulary cards and spaced-repetition reviewer (language-neutral core, per-language profiles). Same code/data split this repo follows. |
| `language-learning-data` | Private vocabulary and review history. A natural later home for per-learner session records. |

## Documents

- [docs/options.md](docs/options.md) — the product shapes considered and why the own voice loop wins.
- [docs/architecture.md](docs/architecture.md) — target architecture: rules into code, components, data model, session engine, cost per session, roadmap, marketability.
- [docs/production-plan.md](docs/production-plan.md) — proposed product build: selectable lesson repositories, three practice modes, durable sessions, private progress and local-to-hosted operation.
- [docs/tasks/README.md](docs/tasks/README.md) — dependency-ordered product backlog, with one contract and GitHub issue per task.
- [docs/process.md](docs/process.md) — main-session/same-family implementation, GitHub PRs and independent OpenCode CLI review.
- [pocs/README.md](pocs/README.md) — the proofs of concept, in order, each with the question it must answer.

## Status

2026-10-16: POC 5 has run real lessons on Android, with spoken task prompts
and a two-sitting lesson option. Its 53 tests pass locally. The next proposed
step is the [production plan](docs/production-plan.md); app/server extraction,
durable storage, source selection and separate progress synchronization are
planned, not implemented.

2026-09-26: POC 0 (lesson connector) answered: it delivers a lesson reliably but cannot record or steer one through a general voice chat. See [pocs/00-mcp-connector](pocs/00-mcp-connector/README.md). Session 4A showed that speech recognition decides the runtime. POC 1 answered it: locked to Ukrainian, ElevenLabs Scribe v2 hears the learner's Ukrainian as Ukrainian (4.2% WER, no Russian) and keeps the learner's mistakes, while OpenAI `gpt-transcribe` corrects most of them. STT → Claude → TTS with Scribe stays the default. POC 2 answered the voice question: ElevenLabs Multilingual v2 with stress-marked text got every judged word right. See [pocs/02-tts-stress](pocs/02-tts-stress/README.md). See [pocs/01-stt-ukrainian](pocs/01-stt-ukrainian/README.md).
