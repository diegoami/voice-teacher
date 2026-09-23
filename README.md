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
| `language-learning-tools` | Vocabulary cards and spaced-repetition reviewer (language-neutral core, per-language profiles). Same code/data split this repo follows. |
| `language-learning-data` | Private vocabulary and review history. A natural later home for per-learner session records. |

## Documents

- [docs/options.md](docs/options.md) — the product shapes considered and why the own voice loop wins.
- [docs/architecture.md](docs/architecture.md) — target architecture: rules into code, components, data model, session engine, cost per session, roadmap, marketability.
- [pocs/README.md](pocs/README.md) — the proofs of concept, in order, each with the question it must answer.

## Status

2026-09-23: POC 0 (lesson connector) built and tested locally and through a tunnel; awaiting the first real voice session. See [pocs/00-mcp-connector](pocs/00-mcp-connector/README.md).
