# POC 5 — Session engine

Status (2026-09-27): milestone 1 built and tested (package parser, target
derivation, review sheet); the derivation call waits for an Anthropic API key.

## Question

Does an engine that owns the turn loop, a state machine for the lesson
shape plus a small Claude teacher prompt with the learner's target withheld
until the first attempt, produce **more independent production** than
controller v4 in a general voice chat? And does the whole loop (Scribe →
engine → Claude → ElevenLabs Multilingual v2) run at a **turn latency a
learner accepts**?

Why it is next: POCs 1 and 2 settled the ear (Scribe v2, keeps the
learner's mistakes) and the voice (Multilingual v2 with stress marks).
POC 0 showed that lesson structure cannot be enforced from outside a
general voice chat. This POC is the first piece of the product.

## What "better" means

Measured per lesson part, against the v4 runs of the same or a comparable
part (3A and 4A on Claude, 4A on ChatGPT):

- **Independent productions** per guided step: the learner produced the
  target without it being supplied first (the tracker's `Independent`).
  This is the main number.
- Checks that become structural and should simply pass: full opening, one
  line per turn (C3, C4); no model before the first attempt (C14); delayed
  recall without cues (C9); clean close (C12); no meta-talk (C16).
- Turn latency: from the end of the learner's speech to the first teacher
  audio, per phase. Target: under 2.5 s median in the guided phase; the
  opening should feel instant.
- Cost per lesson, from the logged characters, seconds and tokens.

## Design

```
learner (Android phone: installable web app, push-to-talk)
   │ audio per turn                     ▲ teacher audio (MP3, streamed)
   ▼                                    │
Scribe v2 (uk) ──► engine state machine ──► text ──► stress marks ──► Multilingual v2
                     │  opening: no model                (authored lines keep theirs;
                     │  guided:  Claude, tools             free turns go through an
                     │  recall:  Claude judges, no cues    automatic stress marker plus
                     │  close:   engine                    a correction list: мене́, …)
                     ▼
               session log (JSON Lines: turns, evidence, timings, costs)
```

**Lesson data.** The engine reads a `lesson.json` per lesson part, derived
from the `/voice-prepare` package (the parser from POC 0 already reads
packages). Each guided step carries: the teacher line (marked and plain),
the expected outcome (English, what the model sees before an attempt), and
the target sentence(s) (Ukrainian, hidden until the first attempt). The
package has no explicit target per step, so the first milestone derives
them once with Claude and the learner checks them. If it works,
`/voice-prepare` in learnukrainian writes `lesson.json` directly.

**Phases.**
- *Opening:* the engine speaks line *k* (pre-rendered, authored marks),
  records the repetition, and says it once more only if the transcript
  shares less than half its words with the line. No model call.
- *Guided:* after each learner turn Claude (Sonnet 5, brief cached) answers
  with one short spoken line and one tool: `accept`, `cue(partial)`,
  `correct(attempt, preferred, chunk)`, or `model_sentence`. The engine
  rejects `model_sentence` before two attempts and asks for a cue. The
  target enters the context only after the first attempt is logged.
- *Delayed recall:* the engine reads the prompts one at a time; the model
  judges the answer and may only correct, never cue before an attempt.
- *Close:* the engine says «Заняття закінчено.» and stops.

**Evidence.** Every tool call writes an evidence row (`independent`, `cued`,
`corrected_repeated`, `modelled`, …) with the turn it rests on. The export
writes the transcript in the learnukrainian format, so `/voice-record` can
record the lesson as usual.

**Stress in free turns.** Claude writes plain Ukrainian. POC 2 showed plain
text costs Multilingual v2 about one wrong stress in ten words on traps. So
free turns go through an automatic stress marker (first candidate: the
`ukrainian-word-stress` package from lang-uk; to verify) and a small
correction list for words every voice gets wrong (`мене́`). Authored lines
keep their checked marks.

## Milestones

| # | Milestone | Output | Learner's part |
| --- | --- | --- | --- |
| 1 | `lesson.json` from a package: parser plus a one-off Claude pass for the per-step targets | `lesson.json` for the next unused lesson part, tests | Check the targets (5 minutes) |
| 2 | Text engine: state machine, Claude teacher with tools, evidence log, transcript export; a simulated learner (Claude playing a learner with typical errors) for automatic runs | CLI lesson in the terminal; tests; three simulated runs | One typed lesson |
| 3 | Voice on Android: a mobile-first web app (PWA: home-screen icon, full screen) with push-to-talk, served over HTTPS through the POC 0 tunnel; Scribe per turn; stress marker + correction list; Multilingual v2, streamed; timings logged | `python -m engine serve`, the app on the phone | Install it, a short sound check |
| 4 | One real voice lesson on the phone; export and `/voice-record` in learnukrainian; comparison with the v4 runs; a note on what the PWA could not do on Android | Answer in this README; `docs/architecture.md` updated | One lesson (15–25 min) |

Each milestone is committed and tested before the next; milestone 2 is
useful on its own (a text tutor with the lesson shape enforced).

## Defaults (change them if you disagree)

- **Android first, as an installable web app (PWA)**, not a native app.
  Chrome on Android allows the microphone only on HTTPS, which the POC 0
  Cloudflare tunnel provides; the PC runs the engine and must be on. The
  same page works in a PC browser for development. A native app (Kotlin,
  or the PWA wrapped with Capacitor) only if milestone 4 hits a limit the
  PWA cannot cross: the lesson stopping with the screen locked, Bluetooth
  headset buttons as push-to-talk, audio routing. A stable address (named
  tunnel or a small server) comes with daily use, not with this POC.
- **Audio from the phone** is what Chrome records (WebM/Opus); Scribe
  accepts it as is.
- **Push-to-talk**, as the architecture says. Automatic end-of-turn
  detection later.
- **The next unused lesson part** from learnukrainian, read in place, not
  copied (only `lesson.json` fixtures live here).
- **Batch Scribe per turn** first; its streaming model only if latency
  demands it.
- Model: `claude-sonnet-5` for the teacher; the simulated learner and the
  target derivation on the same model.

## Cost

Per 20-minute lesson, from POCs 1 and 2 and the architecture's estimate:
speech-to-text about $0.04, teacher voice about $0.25 (2,500 characters),
Claude about $0.05–0.15. **About $0.35–0.45 per lesson.** Building it:
simulated runs cost a few cents each; the target derivation is one call per
lesson part.

## Risks

- **Latency.** Three network hops per turn. Streaming the TTS and keeping
  the model's output to one sentence should hold the guided phase under
  2.5 s; if not, pre-render the step lines and speak only the model's short
  reaction live.
- **The stress marker.** If the automatic marker is poor, free turns fall
  back to plain text (3 of 28 words wrong in POC 2) until a better marker or
  a larger correction list exists.
- **Android.** Microphone permission, audio playback without a fresh tap,
  and the screen locking mid-lesson are the known PWA pain points; the
  push-to-talk tap covers playback, and a screen wake lock covers the rest
  where Chrome supports it. What is left decides whether a native app is
  needed.
- **Scribe on short turns.** POC 1 measured whole readings. One-word turns
  («Так.», «Дякую.») may be harder; the log will show it, and a low
  confidence score triggers «Повторіть, будь ласка.» instead of a correction.
- **The comparison is small.** One lesson against a handful of v4 runs is a
  direction, not a proof. Milestone 2's simulated runs make repeated
  measurement cheap.
