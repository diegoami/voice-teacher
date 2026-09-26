# POC 1 — Speech-to-text on the learner's Ukrainian

## Question

How accurate is language-locked speech-to-text on *this learner's*
Ukrainian? Concretely: with the language forced to Ukrainian and no hint
about the text, what word error rate do ElevenLabs Scribe, OpenAI's
transcription models and Deepgram reach on a reading of lesson sentences,
and how many words come out in Russian spelling?

The own voice loop (STT → Claude → TTS, see
[docs/architecture.md](../../docs/architecture.md)) only works if the answer
is "accurate, and Ukrainian". If it is not, a speech-native teacher is the
better runtime.

## Why now: Session 4A

The same v4 lesson package was run twice on 2026-09-25 (records in
learnukrainian, `pimsleur-review/voice-sessions/`):

- **Claude voice mode**, voice language set to Ukrainian
  (`2026-09-24-session-4A`): almost every learner turn arrived in Russian
  spelling. `де знаходиться` became its Russian equivalent, `праворуч` a
  Russian phrase for "right hand", and `хвилин п'ять пішки` and `на
  наступній зупинці` Russian-looking words of similar sound. The teacher
  could not tell learner errors from recognition errors and stopped the
  lesson.
- **ChatGPT Voice** (speech-native; `2026-09-25-session-4A-chatgpt`): all 27
  learner voice turns arrived as Ukrainian, two of them unclear.

Scored with this POC's script (`python -m stt openings`), the learner's
repetitions of the opening lines as each app wrote them down:

| App (opening turns) | WER (sub/del/ins) | CER | Russian-spelt words | Turns exact |
| --- | --- | --- | --- | --- |
| Claude voice mode, 4A (15, with re-says) | 75.9% (40/0/4) | 24.0% | 22 of 62 (35.5%) | 0/15 |
| ChatGPT Voice, 4A (12) | 0.0% | 0.0% | 0 | 12/12 |

Two different recordings (the learner spoke twice), so this is not yet a
fair comparison of recognisers. It also cannot tell learner errors from
recognition errors: ChatGPT's transcript may be tidied toward the line the
teacher had just said. This POC removes both problems: one recording, a
known text, several recognisers, no context given to any of them.

## Method

1. **Reading list.** [reading_list.md](reading_list.md): 32 sentences from
   `REVIEW_MATERIAL.md` (Session 4 directions, one line each from Sessions 0
   and 1), 143 words. Lines 1–14 are the ones Claude voice mode
   misrecognised in 4A, including `праворуч`, `де знаходиться`, `хвилин п'ять
   пішки` and `на наступній зупинці`; lines 1–12 are the 4A opening itself.
2. **Recording.** The learner reads the list once into the phone used for
   lessons (instructions at the top of the reading list). One file, about
   three minutes.
3. **Transcription.** `python -m stt run <file>` sends the file, unchanged,
   to every provider whose key is set, with the language forced to Ukrainian
   and no prompt, keywords or other hint:

   | Provider | Model | Language setting |
   | --- | --- | --- |
   | `elevenlabs` | Scribe `scribe_v2` | `language_code=uk` |
   | `openai` | `gpt-transcribe` | `languages[]=uk` (the model's only language field) |
   | `openai-4o` | `gpt-4o-transcribe` | `language=uk` |
   | `deepgram` (optional) | `nova-3` | `language=uk`, `smart_format=false` |

   Raw responses are saved under `fixtures/transcripts/<file>/` and reused
   on the next run (`--force` asks again).
4. **Scoring.** Both texts are lower-cased; punctuation and stress marks are
   dropped; apostrophes are unified; digits are spelt out (`5` → `п'ять`).
   The whole transcript is aligned word by word with the whole reading list
   (minimum edit distance), then split back into sentences. Per provider:
   - **WER** = (substitutions + deletions + insertions) / 143 reference
     words; **CER** the same on characters, sentence by sentence;
   - **Russian-spelt words**: words whose spelling exists in Russian and not
     in Ukrainian: letters ы э ъ ё, a soft sign before е и ю я (пьет),
     initial и- (Идите), -тся (находится), -ия/-ие (станция), and a short
     list of Russian-only words (где, как, нет, потом, мне, можно, …). Any
     word with і ї є ґ is Ukrainian. A lower bound: `правую`, `пешки` and
     `далеко` pass;
   - **other-script words** (Latin, Greek), since 2C also drifted there;
   - sentences recognised exactly, overall and for the fourteen 4A lines.

   The report (`fixtures/transcripts/<file>/report.md`) has a summary
   table, a per-line table for the 4A lines, and what each provider heard
   for every wrong sentence. Only the first two go into this README; the
   details are a transcript of the learner's voice and stay local.
5. **Tests without audio.** `uv run pytest`: a fake HTTP API checks that
   each request forces Ukrainian and carries no hints, parses each vendor's
   response shape, and runs `python -m stt run` end to end on a fake file:
   a perfect transcript scores 0%, digits are not counted as errors, a
   transcript with three Russian lines finds them in the right sentences,
   and a provider without a key is reported, not fatal. The 4A table above
   is also a test when the learnukrainian checkout is present.

### What would decide it

- **STT → Claude → TTS stays the default** if at least one provider reaches
  a WER near 10% or lower with (almost) no Russian-spelt words, and
  gets the 4A lines right. Errors that remain should look like the
  learner's own mistakes, not like another language.
- **A speech-native teacher moves to the front** if every provider drifts
  into Russian or stays far above that, as Claude voice mode did.

A follow-up run, if the plain run is borderline: pass the lesson's own
phrases as hints (Scribe `keyterms`, OpenAI `prompt`/`keywords`), which the
engine can do because it knows each step's expected answer. It may also hide
real learner errors, so it is a separate measurement, not the baseline.

## Running it

One-time, in this directory:

```bash
uv sync
```

API keys go into environment variables, or into a `.env` file in this
directory (git-ignored; `KEY=value` per line). OpenAI's key covers both
OpenAI models; Deepgram is optional.

| Variable | Where to get it |
| --- | --- |
| `ELEVENLABS_API_KEY` | elevenlabs.io → Developers → API keys (speech-to-text permission) |
| `OPENAI_API_KEY` | platform.openai.com → API keys |
| `DEEPGRAM_API_KEY` | console.deepgram.com → API keys (optional) |

```bash
uv run python -m stt providers
```

Put the recording at `fixtures/audio/reading-1.m4a` (git-ignored), then:

```bash
uv run python -m stt run fixtures/audio/reading-1.m4a
```

OpenAI accepts only mp3, mp4, mpeg, mpga, m4a, wav and webm, at most 25 MB.
A phone's default recorder gives `.m4a` on iPhone and on most Android
phones; for anything else, convert first (`ffmpeg -i in.ogg reading-1.wav`).

Other commands: `transcribe` (only send), `report` (only score what is
saved), `openings <transcript.md>…` (the lesson-opening table above).

Cost: about three minutes of audio per run, a few cents per provider.

## Answer (2026-09-26, one recording, all four recognisers)

**Accurate, and Ukrainian.** On one phone recording of the reading list
(2.2 minutes, AAC in `.m4a`), with the language locked to Ukrainian and no
hints, no recogniser produced a single Russian-spelt word. Both
OpenAI `gpt-transcribe` and ElevenLabs Scribe v2 got all fourteen lines
right that Claude voice mode had turned into Russian in 4A, with word error
rates under 5%.

| Provider (model) | WER (sub/del/ins) | CER | Russian-spelt words | Other-script words | Sentences exact | 4A lines exact | Request time |
| --- | --- | --- | --- | --- | --- | --- | --- |
| OpenAI (`gpt-transcribe`) | 2.8% (4/0/0) | 0.5% | 0 | 0 | 28/32 | 14/14 | 4.8 s |
| ElevenLabs (`scribe_v2`) | 4.2% (3/0/3) | 3.1% | 0 | 0 | 27/32 | 14/14 | 3.4 s |
| OpenAI (`gpt-4o-transcribe`) | 9.1% (12/1/0) | 2.1% | 0 | 0 | 21/32 | 10/14 | 5.3 s |
| Deepgram (`nova-3`) | 17.5% (23/0/2) | 5.9% | 0 | 0 | 15/32 | 7/14 | 1.8 s |

For comparison, the 4A openings (see above): Claude voice mode 75.9% WER,
22 Russian-spelt words, 0/15 turns exact.

The fourteen 4A lines, per recogniser:

| # | Sentence | gpt-transcribe | Scribe v2 | gpt-4o-transcribe | Nova-3 |
| --- | --- | --- | --- | --- | --- |
| 1 | Перепрошую, де знаходиться станція метро? | ✓ | ✓ | ✓ | ✓ |
| 2 | Як пройти до центру? | ✓ | ✓ | ✓ | 1 err |
| 3 | Ідіть прямо до перехрестя. | ✓ | ✓ | 1 err | 1 err |
| 4 | Потім поверніть праворуч. | ✓ | ✓ | ✓ | 2 err |
| 5 | Станція буде ліворуч. | ✓ | ✓ | ✓ | ✓ |
| 6 | Це далеко? | ✓ | ✓ | ✓ | ✓ |
| 7 | Ні, хвилин п'ять пішки. | ✓ | ✓ | ✓ | ✓ |
| 8 | Як краще доїхати до центру? | ✓ | ✓ | ✓ | ✓ |
| 9 | Можна автобусом або метро. | ✓ | ✓ | 1 err | 1 err |
| 10 | Де мені виходити? | ✓ | ✓ | ✓ | 1 err |
| 11 | На наступній зупинці. | ✓ | ✓ | 1 err | ✓ |
| 12 | Ні, не до вокзалу. Мені потрібно до автовокзалу. | ✓ | ✓ | ✓ | 2 err |
| 13 | Ідіть прямо до перехрестя, а потім поверніть праворуч. | ✓ | ✓ | 1 err | 2 err |
| 14 | Після перехрестя? | ✓ | ✓ | ✓ | ✓ |

What the errors are (from the local report, not quoted here). Where all
four recognisers agree against the text, the learner most likely said it
that way; the learner confirms the reading was not perfect.

- **Shared by all four:** `а` for `і` in line 32, so almost certainly a
  reading slip. Three also wrote a colloquial variant of one word in
  line 17, and three wrote `і` for `й` in line 22 (the same conjunction).
  Take these out and `gpt-transcribe` is left with one error, a shortened
  form of `перепрошую`.
- **Scribe v2 writes verbatim; `gpt-transcribe` tidies.** Scribe kept a
  word the learner began and said again (line 16), a syllable stutter
  (line 32) and a false start before line 31; `gpt-transcribe` dropped all
  three. Scribe has one error of its own: a different number in line 15,
  where the other three agree with the text.
- **`gpt-4o-transcribe`:** voicing and ending errors (`з` heard as `с`,
  imperative `ідіть` as other verb forms). Ukrainian throughout, but a
  teacher would correct errors the learner did not make.
- **Nova-3:** the same kind, more often.

What this shows:

1. **The Russian drift in 4A was Claude voice mode's recogniser, not the
   learner's pronunciation.** The same learner reading the same lines gives
   no Russian-spelt word on any of four API recognisers once the
   language is locked.
2. **Runtime A (STT → Claude → TTS) stays the default.** Two recognisers
   clear the bar set above (WER well under 10%, no Russian, all 4A lines
   right): `gpt-transcribe` and Scribe v2. A speech-native teacher is the
   fallback, not the plan.
3. **Which of the two could not be settled by correct reading.**
   `gpt-transcribe` is more accurate on what was meant; Scribe is more
   faithful to what was said. A teacher needs the learner's real errors, so
   run 2 reads sentences with deliberate mistakes. Its answer: **Scribe v2**
   (see below).

Cost of this run, at list prices on 2026-09-26 for the 132 seconds each
provider reported (the two refused OpenAI requests were not billed):

| Provider (model) | List price | This run | 10 min of learner audio (one lesson) |
| --- | --- | --- | --- |
| OpenAI `gpt-transcribe` | $0.0045/min | $0.010 | $0.045 |
| ElevenLabs `scribe_v2` | $0.22/hour | $0.008 | $0.037 |
| OpenAI `gpt-4o-transcribe` | ≈ $0.006/min (tokens) | ≈ $0.013 | ≈ $0.06 |
| Deepgram `nova-3` | $0.0048/min (promotional; $0.0077 regular) | $0.011 | $0.05 |
| **Total** | | **≈ $0.04** | |

Recognition is not a cost question: either good recogniser costs about
four or five cents per lesson, in line with the architecture's estimate.

Limits: one recording of read speech, one day, one phone. Batch requests
only: per-turn latency on short clips and the streaming variants are not
measured.

## Run 2: does the recogniser keep the learner's mistakes? (2026-09-26)

[reading_list_errors.md](reading_list_errors.md): 26 Session 4 sentences.
Eighteen contain one planted mistake of the kinds a learner makes: seven
Russian words (где, потом, нет, можно, спасибо, здесь, повторите), eight
wrong case endings or verb forms (до центр, на наступна зупинка, біля
готель, Де мені виходить?), two gender errors and one wrong word. Eight are
correct, as controls. The mistakes are marked only in the file's source
(`<!-- error: said → correct -->`), so the reader is not tempted to fix
them.

For each planted mistake the report says whether each recogniser **kept**
it, **corrected** it to the right Ukrainian (hiding it from the teacher), or
wrote something else, and how many controls it got exactly. WER is against
what was read, mistakes included. The recogniser for the engine is the one
that keeps the most mistakes without inventing errors in the controls.

```bash
uv run python -m stt --reading-list reading_list_errors.md run fixtures/audio/<file>
```

### Answer

**ElevenLabs Scribe v2 writes down the learner's mistakes; `gpt-transcribe`
corrects most of them.** One phone recording (108 s), all four recognisers:

| Provider (model) | Mistakes kept | Corrected (hidden) | Other | Controls exact | WER against what was read | Request time |
| --- | --- | --- | --- | --- | --- | --- |
| ElevenLabs (`scribe_v2`) | **12/18** | **2/18** | 4/18 | 7/8 | 8.0% | 2.8 s |
| Deepgram (`nova-3`) | 7/18 | 3/18 | 8/18 | 6/8 | 18.8% | 2.4 s |
| OpenAI (`gpt-transcribe`) | 6/18 | 10/18 | 2/18 | 8/8 | 11.6% | 4.5 s |
| OpenAI (`gpt-4o-transcribe`) | 5/18 | 9/18 | 4/18 | 7/8 | 18.8% | 3.8 s |

Per planted mistake:

| # | Read (mistake → correct) | Scribe v2 | gpt-transcribe | gpt-4o-transcribe | Nova-3 |
| --- | --- | --- | --- | --- | --- |
| 1 | где → де | kept | corrected | corrected | other |
| 2 | до центр → до центру | kept | corrected | corrected | kept |
| 4 | потом → потім | kept | corrected | corrected | corrected |
| 5 | лівий → ліворуч | other | other | other | other |
| 7 | нет → ні | kept | corrected | corrected | kept |
| 9 | можно → можна | kept | corrected | corrected | corrected |
| 10 | виходить → виходити | kept | corrected | kept | kept |
| 11 | наступна зупинка → наступній зупинці | kept | kept | other | other |
| 12 | до вокзал → до вокзалу | kept | kept | corrected | kept |
| 15 | навпроти банк → навпроти банку | kept | kept | kept | other |
| 16 | спасибо → спасибі | corrected | kept | kept | corrected |
| 17 | найближчий → найближча | other | corrected | corrected | other |
| 18 | біля готель → біля готелю | kept | kept | other | kept |
| 21 | потрібна → потрібен | kept | corrected | corrected | kept |
| 22 | здесь → тут | kept | kept | kept | other |
| 23 | іншій бік → іншому боці | other | other | other | other |
| 25 | повторите → повторіть | other | corrected | corrected | other |
| 26 | українці → українців | corrected | corrected | kept | kept |

Reading the table:

- **`gpt-transcribe` hides the mistakes a teacher most needs to hear.** It
  turned five of the seven Russian words into their Ukrainian equivalents
  (где, потом, нет, можно, повторите) and fixed five endings or agreements
  (до центр, виходить, найближчий, потрібна, українці). What it keeps is
  mostly what cannot be tidied into a nearby Ukrainian word. The same
  tidying made it the most accurate on correct reading in run 1. For a
  transcript that is a virtue; for a teacher it removes the evidence.
- **Scribe v2 kept 12 and corrected only 2.** Its four "other" results
  still show a mistake: line 5 came out as a different wrong form
  (all four recognisers agree on it, so it is probably how it was said),
  lines 17 and 23 as other wrong forms, and line 25 as a Russian verb in
  Ukrainian letters. Counting those, Scribe let the teacher see a mistake
  in 16 of 18 lines. Of the seven Russian words it kept five, wrote
  повторите in Ukrainian letters, and corrected only спасибо.
- **Controls:** Scribe got one of the eight correct lines wrong (`їдете`
  as `йдете`, by transport vs on foot); `gpt-transcribe` none.
- `gpt-4o-transcribe` corrects like `gpt-transcribe` and is less accurate.
  Nova-3 keeps some mistakes but garbles too much to tell them from its own
  errors.

**Decision: ElevenLabs Scribe v2 is the recogniser for the engine.** It is
accurate on correct Ukrainian (run 1: 4.2% WER, no Russian, all 4A lines),
keeps the learner's mistakes (run 2), and is the cheapest and fastest of
the two good ones. `gpt-transcribe` is the better choice only where a clean
transcript matters more than the learner's errors, such as a lesson summary.

One consequence for the 4A comparison above: ChatGPT Voice's perfect
opening transcript may be the same kind of tidying. Its transcript is not
evidence that the learner said every line correctly.

Cost of run 2 at the same list prices (108 s): Scribe $0.007,
`gpt-transcribe` $0.008, `gpt-4o-transcribe` ≈ $0.011, Nova-3 $0.009;
about $0.035. Both runs together: about $0.08.

Limits: one reader, one recording, planted mistakes read deliberately.
Real mistakes in spontaneous speech may sound less clear-cut. Next:
per-turn latency on short clips (whether the engine needs Scribe's
streaming model), then the first engine turns in POC 5 with Scribe
transcripts shown to the learner.

## Files

- `reading_list.md`: the sentences and the recording instructions.
- `reading_list_errors.md`: run 2, the same with planted mistakes.
- `stt/text.py`: normalisation, numbers, the Russian-spelling test.
- `stt/align.py`: word alignment and edit distance.
- `stt/score.py`: reading-list parser, per-sentence scoring, summary.
- `stt/providers.py`: the four requests, with the language forced.
- `stt/report.py`: the Markdown report and the lesson-opening parser.
- `stt/__main__.py`: `providers`, `transcribe`, `report`, `run`, `openings`.
- `tests/`: everything above without real audio or network, including
  a verbatim and a tidying recogniser for run 2.
- `fixtures/audio/`, `fixtures/transcripts/`: local only, git-ignored.
