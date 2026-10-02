# POC 5 — Session engine

Status (2026-10-02): milestone 1 done (4B targets derived by GPT-6 Sol for 1.5
cents); milestone 2 done (the lesson state machine, the typed lesson, Gemini
3.8 Flash as teacher, judge v2 after the first typed lesson); milestone 3
built and tested offline, with one smoke test of the real speech services
(the voice app, `python -m engine serve`); it has not been run on a phone
yet. Next: install it on the phone, then one real voice lesson (milestone 4).

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
text costs Multilingual v2 about one wrong stress in ten words on traps. The
first plan was an automatic stress marker (the `ukrainian-word-stress`
package from lang-uk). Milestone 3 does without it: see "Stress marks" below.

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

## Milestone 3: voice on Android (2026-10-02)

A mobile-first web app served by the engine. One learner turn is one request:
the phone uploads the recording, the server sends it to Scribe v2, passes the
text to the session, synthesises every line the teacher says with Multilingual
v2 and answers with JSON (plain text per line, an audio URL per line, the task
card, whether the lesson is done).

Files: `engine/server.py` (Starlette app, routes, per-turn log), `engine/app.html`
(the page: inline CSS and JS, no external resources), `engine/voice.py` (the
Scribe and ElevenLabs requests), `engine/stress.py` (stress marks), `run.sh`.

### How to run

On the PC (needs `ELEVENLABS_API_KEY` and `OPENROUTER_API_KEY` in the
git-ignored `.env`):

```
cd pocs/05-session-engine
uv sync
./run.sh                       # server + Cloudflare quick tunnel; prints the HTTPS address
```

`run.sh` takes an optional lesson file (default `fixtures/lessons/4B.json`)
and passes further arguments to the server (`./run.sh fixtures/lessons/4B.json --model openai/gpt-6-luna`).
Ctrl+C stops both the server and the tunnel. Without the tunnel, for
development in a PC browser (`localhost` counts as secure for the microphone):

```
uv run python -m engine serve fixtures/lessons/4B.json --port 8765
# open http://127.0.0.1:8765/<token>/ ; the token is in fixtures/token
```

All routes sit under `/<token>/`; anything else is 404. The token is created on
the first run in `fixtures/token` (git-ignored). Anyone with the address can
run lessons on your keys, so keep it private; it stays the same between runs,
but the quick tunnel's host changes every time.

### On the phone

1. Open the printed `https://….trycloudflare.com/<token>/` address in Chrome
   on Android.
2. Menu (three dots) → "Add to Home screen" (or "Install app"). The icon opens
   the lesson full screen. The home-screen icon keeps the old address, so after a
   new `run.sh` open the new address in Chrome again (the host changes each time).
3. Press Start, allow the microphone when asked. Headphones are best (no echo of
   the teacher into the microphone).

The page shows the teacher's lines in plain spelling (each appears as it is
spoken), the task card in a yellow box, and in small text what speech
recognition heard. States: ready, starting, the teacher speaking, your turn,
listening, thinking (with elapsed seconds), finished. Errors are written out:
microphone denied or missing, no connection, a failed speech service.
"Hear again" replays the last teacher turn; "Stop the lesson" ends the lesson
with the closing line. The screen stays on during a lesson where Chrome allows
a wake lock.

**Tap to talk is the default; hold to talk is a switch** (top right, remembered
on the phone). Tap to talk: tap, speak, tap again. It is the default because a
learner thinking before a Ukrainian sentence would have to keep a thumb pressed
for several seconds, and a thumb that slips ends the turn mid-word. Hold to
talk gives a clear end of the turn and no stray recording, at the price of the
held thumb; the long-press menu is suppressed on the button. Recordings under
half a second are discarded with a message.

### What is logged per turn

Each learner turn appends a `timing` event to the session log
(`fixtures/sessions/<part>-<time>.jsonl`, git-ignored, written when the lesson
finishes, is stopped, or is abandoned by starting another): what was heard,
`stt_seconds`, `judge_seconds` (from the judge's own log entry), `tts_seconds`
(wall time for all the turn's lines, the new ones synthesised in parallel),
`total_seconds` (upload received to response sent), `audio_seconds` (from
Scribe, when it says), `tts_chars_billed` and `cost_usd` per part: Scribe at
$0.22 per hour of audio, the judge from OpenRouter's reported cost, ElevenLabs at
$0.10 per 1,000 characters **not served from the cache**. Turn 0 is the start.
If Scribe returns no text, the lesson does not advance: the teacher says «Повторіть, будь ласка.»
and the turn is logged with `retry: true`.

Teacher audio is cached under `fixtures/tts-cache/` (git-ignored), keyed by a
hash of model, voice and the marked text, so every fixed line is paid for once.

### Stress marks, and why there is no stress library

The engine speaks pre-marked lesson text almost everywhere: the introduction,
opening, step lines, targets, recall prompts and its own fixed phrases all carry
checked marks. Only a correction chunk (the model's «до це́нтру») and a
one-sentence answer to a question about meaning come from the model, in plain
spelling. For those, `engine/stress.py` applies, to every line before synthesis:

1. a word that already has a mark is left alone;
2. an unmarked word is looked up in a dictionary built once per lesson from every
   marked word in the lesson and the engine's fixed phrases, keeping its
   capitalisation and punctuation;
3. then the `CORRECTIONS` dict in `stress.py` (words every voice gets wrong; it
   starts with `мене` → `мене́`, easy to extend);
4. everything else stays unmarked.

A stress library (the candidate was lang-uk's `ukrainian-word-stress`, a
machine-learning install; not tried here) would mark a few words per lesson at
a cost in install weight and machine load, and with a risk of wrong marks
(Multilingual v2 follows a wrong mark; POC 2).
The correction chunks reuse the lesson's own words, so the lesson dictionary
already covers most of them. What this approach cannot do: mark a word the
lesson never marked and the correction list lacks, tell homographs apart
(the dictionary has one marked form per spelling), or fix a form the lesson
marks in another case. Those words go to the voice unmarked, the case POC 2
measured at roughly one wrong word in ten. The lessons will show which words
to add to `CORRECTIONS`. Unit-tested in `tests/test_stress.py`.

### Verified, and not

Verified: the 46 tests (endpoints with a fake speech-to-text, fake
text-to-speech and the fake judge; the cache; wrong token gives 404; stress
marking); the server started locally and answers under the token path, 404
elsewhere; one smoke test with the real services: the start request synthesised
the introduction and the first opening line (279 characters, 2.9 s for the
request, about $0.028), and Scribe read that MP3 back: «Перепрошую, де
знаходиться станція метро?», identical to the line, 0.72 s, 2.46 s of audio
(about $0.0002).

Not verified, because nothing was run on a phone: the page's behaviour in
Chrome on Android (recording, playback order, the autoplay unlock, wake lock,
installability: the manifest has PNG and SVG icons and a service worker, but
Chrome decides), the tunnel (`run.sh` was written and not run), hold to talk
on a touch screen, and real turn latency over the phone's network.

### Known limits

- Not streamed: each line is a whole MP3 and the page plays after the response
  arrives, so a turn costs recognition + judge + synthesis in sequence (new lines
  are synthesised in parallel). Streaming is the next step if the latency is too slow.
- One lesson in memory; starting again abandons it (its log is saved). A server
  restart loses a running lesson.
- If synthesis fails after the lesson has advanced (a service error mid-turn),
  the page shows the error and the teacher's line for that turn is lost; the
  learner can stop and start again. A recognition failure leaves the lesson
  untouched.
- The microphone is opened for each recording, not kept open, so playback is
  not ducked by a call-style audio mode; the first words may be clipped if you
  speak at the instant you tap.
- The screen locking, or Chrome in the background, stops recording and playback
  where the wake lock is refused; milestone 4 will show whether it matters.
- No automatic end of turn, no interruption of the teacher (the button is off
  while the teacher speaks).
- The quick-tunnel host changes on every run; a stable address comes later.

## Milestone 4, run 1: the first voice lesson (2026-10-02)

Lesson 4B on the learner's Android phone through `run.sh` (Scribe, Gemini 3.8
Flash, ElevenLabs Multilingual v2). The session log stays local; this is the
summary. The learner stopped with «стоп» at round 2, step 8, after 12 minutes.

Time from the end of the upload to the reply (measured on the PC; the phone
network and playback start come on top):

| Turn | Speech to text | Judge | Voice | Total |
| --- | --- | --- | --- | --- |
| Repeat phases (no model) | median 0.9 s | – | 0.9 s, 0 when cached | about 1.8 s |
| Rounds 1–2 | median 0.9 s | median 1.3 s, max 3.2 s | 0.9 s, 0 when cached | about 3 s, max 5.5 s |

Cost: $0.155 for the lesson: voice $0.117 (first run: the cache filled;
lines already cached cost nothing next time), speech to text $0.016, judge
$0.022.

Evidence: opening 10 of 12 lines repeated (2 needed another turn), round 0
9 of 9, round 1: 6 independent, 2 cued, 1 corrected, 3 modelled; round 2
(until the stop): 4 independent, 2 modelled.

Findings:

- **The learner sometimes repeated the teacher in round 1 instead of
  answering**: after 21 listen-and-repeat lines the habit carries over, and
  in a voice lesson the task card on screen is easy to miss. Proposed: in
  round 1 the voice also reads the task card in English, as Pimsleur does.
- **Speech recognition is rougher in a lesson than on the reading**:
  garbled words in about one turn in five, `з` written as `с` in «зупинка»
  three times (pronunciation or recognition; cannot tell without the audio),
  and Latin-script output. Italian speech in the background (confirmed by
  the learner) was transcribed into one 14-second turn and a few
  Latin-script fragments: the recogniser writes whatever it hears. Lessons
  need a quiet room; a warning on very long turns and on turns mostly in
  another script would help.
- **One judging miss, fixed (judge v3):** a later step's task done in other
  words was rejected instead of recognised as running ahead. After the fix
  the same turn is a `later_step` to step 6.
- Worked as designed: the greeting back («Слу́хаю вас.»), running ahead to
  the thank-you, «стоп», corrections of `мені́ вихо́дити`, `шви́дше`,
  `зупи́нка`, cached lines in about 0 s.

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
- **Unmarked model words.** Words the model writes that the lesson never
  marked and the correction list lacks go to the voice plain (3 of 28 words
  wrong in POC 2). The correction list grows from what the lessons show.
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
