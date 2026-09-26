# POC 2 — Ukrainian stress in text-to-speech

## Question

Does any text-to-speech model place Ukrainian word stress correctly, and
does it help to send the text with stress marks (the acute accents the
lesson material already carries)?

A teacher voice that stresses words wrongly teaches the wrong stress. The
engine has a good recogniser now (POC 1: ElevenLabs Scribe v2); this is
the other half of the go/no-go for the own voice loop.

## Method

1. **Items.** [stress_items.md](stress_items.md): fifteen sentences, each
   naming the words to judge (27 target words). Items 1–10 are Session 4A
   lesson lines with the material's stress marks. Items 11–15 were written
   for this POC: words whose Ukrainian stress differs from Russian
   (`одина́дцять`, `чотирна́дцять`, `дочка́`, `легки́й`, `кропива́`), the
   prefix-stressed `ви́хід`, and the homograph pair `за́мок` (castle) /
   `замо́к` (lock), which plain spelling cannot tell apart.
2. **Variants.** Every item is spoken in eight versions:

   | Variant | Provider, model | Text sent |
   | --- | --- | --- |
   | `el-v2-plain` / `el-v2-marks` | ElevenLabs Multilingual v2 | plain / with stress marks |
   | `el-v3-plain` / `el-v3-marks` | ElevenLabs v3 | plain / with stress marks |
   | `el-flash-plain` / `el-flash-marks` | ElevenLabs Flash v2.5 (low latency), `language_code=uk` | plain / with stress marks |
   | `openai-plain` / `openai-marks` | OpenAI `gpt-4o-mini-tts`, voice `coral` | plain / with marks, plus an instruction that an acute accent marks the stressed syllable |

   ElevenLabs uses one premade voice (George) for all three models and a
   fixed seed, so the model, not the voice, is what varies.
3. **Sanity check.** Scribe (POC 1) transcribed the eight versions of item
   1: all eight say the sentence, so the marks are not read aloud. The
   OpenAI version with marks is slower (5.0 s against 3.8 s plain).
4. **Blind listening.** `python -m tts listen` serves a page on this
   computer. Per sentence the eight versions appear as A–H in a random order
   that stays the same on reload, with no provider names. For each one the
   listener presses right, wrong (and ticks which target word, or another
   word) or unclear. Every click is saved to `fixtures/verdicts.json`.
5. **Report.** `python -m tts report`: per variant, clips with every
   target right, target words wrong, median request time and characters;
   per item, the verdict of every variant.

Not in this round: pronunciation dictionaries and phoneme input.
ElevenLabs' phoneme tags cover English only. Its alias dictionaries could
respell a word that is stressed wrongly in every variant, which makes them
the fix for specific words, not a first test.

### What would decide it

- **Go** if one variant gets (almost) every target right. Stress marks
  that fix errors are fine: the engine stores a `tts` rendering with marks
  for every phrase anyway (see `docs/architecture.md`).
- **Split** if only a slow model is right: fixed lines (the opening, the
  close, recall prompts) can be rendered ahead of time with it, and the
  fast model speaks only the teacher's free turns.
- **No-go for generated speech** if every variant gets the lesson words
  wrong. Then it is recorded or dictionary-corrected audio for the fixed
  lines, and a hard look at free turns.

## Running it

Keys: `ELEVENLABS_API_KEY` (with Text to Speech access) and
`OPENAI_API_KEY`, in the environment or a git-ignored `.env` here. Locally
it is a symlink to POC 1's `.env`.

```bash
uv sync
```

```bash
uv run python -m tts render
```

```bash
uv run python -m tts listen
```

Open the printed `http://localhost:…/listen.html` in a browser on the same
machine (from Windows too, when this runs in WSL). Stop it with Ctrl+C,
then:

```bash
uv run python -m tts report
```

Audio, manifest, verdicts and report are under `fixtures/` (git-ignored).
Rendering is cached; `--variant`, `--item` and `--force` narrow or redo it.

Cost of the full render (15 items, 8 variants, 120 clips) at list prices
on 2026-09-26: ElevenLabs Multilingual v2 and v3 $0.10 per 1,000
characters (1,021 characters each, about $0.10 each), Flash v2.5 $0.05 (about
$0.05), OpenAI about $0.015 per minute of speech (about $0.03). **About $0.30
in total.**

## Answer

Pending: waiting for the listening verdicts.

## Files

- `stress_items.md`: the sentences and their target words.
- `tts/items.py`: item parser and the eight variants.
- `tts/providers.py`: the ElevenLabs and OpenAI requests.
- `tts/__main__.py`: `variants`, `render`, `listen` (with the save
  endpoint), `report`.
- `tts/listen.html`: the blind listening page.
- `tts/report.py`: the summary.
- `tests/`: parser, requests, rendering, the save endpoint and the report,
  without network.
