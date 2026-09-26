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
- [pocs/README.md](pocs/README.md) — the proofs of concept, in order, each with the question it must answer.

## Status

2026-09-26: POC 0 (lesson connector) answered: it delivers a lesson reliably but cannot record or steer one through a general voice chat. See [pocs/00-mcp-connector](pocs/00-mcp-connector/README.md). Session 4A showed that speech recognition decides the runtime. POC 1 answered it on one recording: locked to Ukrainian, OpenAI `gpt-transcribe` (2.8% WER) and ElevenLabs Scribe v2 (4.2%) produced no Russian-spelt words, so STT → Claude → TTS stays the default. See [pocs/01-stt-ukrainian](pocs/01-stt-ukrainian/README.md).
