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

## Answer

Pending: waiting for the first recording.

## Files

- `reading_list.md`: the sentences and the recording instructions.
- `stt/text.py`: normalisation, numbers, the Russian-spelling test.
- `stt/align.py`: word alignment and edit distance.
- `stt/score.py`: reading-list parser, per-sentence scoring, summary.
- `stt/providers.py`: the four requests, with the language forced.
- `stt/report.py`: the Markdown report and the lesson-opening parser.
- `stt/__main__.py`: `providers`, `transcribe`, `report`, `run`, `openings`.
- `tests/`: everything above without real audio or network.
- `fixtures/audio/`, `fixtures/transcripts/`: local only, git-ignored.
