# POC 5 — Session engine

Status (2026-09-27): milestone 1 done (4B targets derived by GPT-6 Sol for 1.5
cents); milestone 2 built: the lesson state machine, the typed lesson, the
simulated comparison (Gemini 3.8 Flash chosen as teacher), and one typed
lesson with the learner, which led to judge v2. Next: voice on Android.

## Question

Does an engine that owns the turn loop, a state machine for the lesson
shape plus a small teacher prompt with the learner's target withheld
until the first attempt, produce **more independent production** than
controller v4 in a general voice chat? And does the whole loop (Scribe →
engine → language model → ElevenLabs Multilingual v2) run at a **turn latency a
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
                     │  guided:  teacher model, tools      free turns go through an
                     │  recall:  model judges, no cues     automatic stress marker plus
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
them once with a strong model and the learner checks them. If it works,
`/voice-prepare` in learnukrainian writes `lesson.json` directly.

**Lesson shape (set with the learner, 2026-09-27).** Each part of the lesson
makes one thing easier than the next:

1. *Opening review:* the previous lesson's lines. The teacher says a line,
   the learner repeats it. The screen says: «Listen and repeat exactly what
   you hear. Don't answer, even when it is a question.»
2. *Round 0, new sentences:* this lesson's own target sentences, each once,
   to repeat, with the card «Repeat exactly what you hear; don't answer it.
   You will need it to …».
3. *Round 1, with the script:* the guided dialogue; each step shows its
   task card («Your turn: ask where the nearest station is»).
4. *Round 2, without the script:* the same dialogue, no cards.
5. *Delayed recall:* the prompts one at a time, no help before an attempt.
6. *Close:* «Заня́ття закі́нчено.»

In the repeat phases no model is called. A turn counts as a repetition when at
most one word in three differs, so a lost or garbled word passes but an answer
(«це коштує двадцять» for «Скільки це коштує?») does not; the line is said
once more, then the lesson moves on.

**The model only judges.** The engine writes every teacher line: the step
lines, the task cards, the correction template «Ви́правлення: … Скажі́ть усе́
ре́чення.», a partial cue (the target's first words) and, after two misses,
the full sentence to repeat. The model returns a verdict for one learner turn
(`accept`, `error`, `unclear`, `question`), the chunk to correct and, for a
question about meaning, a one-sentence answer. It cannot break the lesson
rules because it never chooses what to say; its call is small, so it is fast
and cheap. Evidence labels follow from the help used: `independent` (the card
holds no Ukrainian), `cued`, `corrected_repeated`, `modelled_repeated`,
`needs_turn`.

**Task cards (found 2026-09-27, by the learner).** A step's teacher line does
not tell the learner what to say next: after «Метро́ шви́дше.» nothing implies
«Де найбли́жча ста́нція?». The package tells only the teacher ("wait for the
learner to ask where the nearest station is"), so in the voice lessons the
learner had to guess, which may explain some of the lines the teachers ended
up supplying (C14). The engine shows each step's task on the phone screen,
in English, while the teacher speaks Ukrainian: «Your turn: ask where the
nearest station is.» It is the Pimsleur prompt, and it is already in every
package (the step's expected outcome). Help comes in stages: the task card,
then a partial cue (the first word or two), then the full sentence to
repeat. An answer given after the card alone counts as independent: the card
holds no Ukrainian.

**Evidence.** Every tool call writes an evidence row (`independent`, `cued`,
`corrected_repeated`, `modelled`, …) with the turn it rests on. The export
writes the transcript in the learnukrainian format, so `/voice-record` can
record the lesson as usual.

**Stress in free turns.** The teacher model writes plain Ukrainian. POC 2 showed plain
text costs Multilingual v2 about one wrong stress in ten words on traps. So
free turns go through an automatic stress marker (first candidate: the
`ukrainian-word-stress` package from lang-uk; to verify) and a small
correction list for words every voice gets wrong (`мене́`). Authored lines
keep their checked marks.

## Milestones

| # | Milestone | Output | Learner's part |
| --- | --- | --- | --- |
| 1 | `lesson.json` from a package: parser plus a one-off model pass for the per-step targets | `lesson.json` for the next unused lesson part, tests | Check the targets (5 minutes) |
| 2 | Text engine: state machine, teacher model with tools, evidence log, transcript export; a simulated learner (a model playing a learner with typical errors) for automatic runs; **the teacher model chosen by measurement**: the same simulated lessons on three candidates (frontier, fast, cheap), compared on judging, latency and cost | CLI lesson in the terminal; tests; simulated runs per candidate | One typed lesson |
| 3 | Voice on Android: a mobile-first web app (PWA: home-screen icon, full screen) with push-to-talk, served over HTTPS through the POC 0 tunnel; Scribe per turn; stress marker + correction list; Multilingual v2, streamed; timings logged | `python -m engine serve`, the app on the phone | Install it, a short sound check |
| 4 | One real voice lesson on the phone; export and `/voice-record` in learnukrainian; comparison with the v4 runs; a note on what the PWA could not do on Android | Answer in this README; `docs/architecture.md` updated | One lesson (15–25 min) |

Each milestone is committed and tested before the next; milestone 2 is
useful on its own (a text tutor with the lesson shape enforced).

## Milestone 2 result: the teacher model (2026-09-27)

The simulated 4B lesson (`python -m engine simulate`): 29 first attempts,
the same for every model, written once by GPT-6 Sol with planted mistakes (a
Russian word, a wrong ending, a wrong word) and correct variants in other
words. Report: [fixtures/simulations/4B.md](fixtures/simulations/4B.md).

| Teacher model | Mistakes caught | Correct answers accepted | Unclear handled | Median / slowest call | Cost of the lesson's judging |
| --- | --- | --- | --- | --- | --- |
| **Gemini 3.8 Flash** | 12/12 | 15/15 | 1/1 | **1.06** / 2.59 s | $0.030 |
| GPT-6 Luna | 12/12 | 15/15 | 1/1 | 1.35 / 3.27 s | $0.004 |
| GPT-6 Sol | 12/12 | 15/15 | 1/1 | 1.58 / 2.75 s | $0.075 |

All three judged every turn right and gave correct correction chunks
(«до це́нтру», «мені́», «кра́ще»), so on this set the difference is speed and
cost. **Gemini 3.8 Flash is the default teacher**: it is fastest, and speed is
what the voice loop is short of; its cost is three cents a lesson. GPT-6 Luna
is the fallback if cost ever matters (a seventh of it, 0.3 s slower).

What this does not show: the planted mistakes are clear-cut. Real learner
mistakes are subtler and arrive through speech recognition; the typed and the
voice lessons are where the judge is really tested. Two settings mattered for
speed: OpenRouter's fastest-provider routing (a model's discounted "flex"
endpoint took 2–4 s a call) and minimal reasoning. The whole comparison,
including the learner script, cost about $0.14.

## Milestone 2: the first typed lesson (2026-09-29)

The learner typed lesson 4B through the engine with Gemini 3.8 Flash
(`python -m engine play`). The session log stays local
(`fixtures/sessions/`, git-ignored); this is the summary.

- The shape worked: opening review and round 0 as pure repetition, round 1
  with task cards, round 2 without, recall, close. Evidence in rounds 1–2
  and recall: 23 independent, 3 cued, 2 corrected and repeated, 1 modelled.
- Judging: 35 calls, median 1.11 s, slowest 2.32 s; 2.6 cents for the
  lesson.

What the lesson exposed, all in round 2 and recall, where there is no card:

| What the learner did | What the engine did | Fix (judge v2) |
| --- | --- | --- |
| Returned the teacher's greeting | Counted a failed attempt, gave a cue | New verdict `social`: the teacher says «Слу́хаю вас.» and waits; no attempt counted |
| Asked a later step's question (ran ahead in the dialogue) | Rejected it twice, modelled the expected question | New verdict `later_step`: the judge sees the next four steps' tasks; the engine marks the steps in between `skipped`, records that step `independent` and answers with its reply |
| Asked the same thing in other words ("is it a direct line?" for "do I have to change?") | Rejected it | The judge accepts a question that asks for the same information in other words |
| Typed «закінчимо» at a recall prompt | Treated it as an attempt | «Закінчимо», «стоп», «досить» end the lesson, decided by the engine without a model call |

Judge v2 on the simulated lesson: still 12/12 mistakes caught and 15/15
correct answers accepted, median 1.04 s. It now also accepts «Як пройти до
центру?» for "ask the best way to get to the centre", which v1 corrected
toward «Як кра́ще дої́хати»: correct Ukrainian that does the task, as the v4
controller already required.

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
- **Models through OpenRouter**, any vendor, one setting per role
  (`engine/llm.py`): `TARGETS_MODEL` (default `openai/gpt-6-sol`) derives the
  targets; `TEACHER_MODEL` is chosen in milestone 2. OpenCode Zen or OpenAI
  by setting `LLM_PROVIDER`. (Changed 2026-09-27 from Claude only, the
  learner's decision.)

## Cost

Per 20-minute lesson, from POCs 1 and 2 and the architecture's estimate:
speech-to-text about $0.04, teacher voice about $0.25 (2,500 characters),
the teacher model $0.02–0.40 depending on the one chosen. **About $0.30–0.70 per lesson.** Building it:
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
