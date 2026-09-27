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

## Answer (2026-09-27, one listener, all 120 clips judged blind)

**Go, with ElevenLabs Multilingual v2 and stress marks, and one fix to
make.** Given the material's stress marks, Multilingual v2 put the stress
right on every one of the 28 judged words. The lesson lines are safe on
almost every variant. The traps are where the variants differ.

| Variant | Target words wrong | Clips with every target right | Other word wrong | Median request time |
| --- | --- | --- | --- | --- |
| **ElevenLabs Multilingual v2, marks** | **0/28** | 13/15 | 1 | 1.0 s |
| ElevenLabs v3, marks | 1/28 | 13/15 | 0 | 2.7 s |
| ElevenLabs v3, plain | 1/26 (one clip unclear) | 12/15 | 1 | 1.5 s |
| OpenAI `gpt-4o-mini-tts`, marks | 1/28 | 11/15 | 1 | 1.2 s |
| ElevenLabs Multilingual v2, plain | 3/28 | 11/15 | 1 | 1.0 s |
| ElevenLabs Flash v2.5, plain | 3/28 | 11/15 | 1 | 0.3 s |
| ElevenLabs Flash v2.5, marks | 4/28 | 10/15 | 1 | 0.3 s |
| OpenAI `gpt-4o-mini-tts`, plain | 4/28 | 11/15 | 1 | 1.3 s |

Request time is for the whole clip without streaming. "Clips with every
target right" also counts two verdicts for things other than stress: a
rushed «Ні, хвилин» and an unclear `щ`.

Per item (✗ = the judged word that was wrong):

| # | Judged | v2 plain | v2 marks | v3 plain | v3 marks | Flash plain | Flash marks | OpenAI plain | OpenAI marks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1–10 | 20 words in 4A lesson lines | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ два́дцять | ✗ поті́м, право́руч | ✗ перепро́шую |
| 11 | одина́дцять, чотирна́дцять | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 12 | дочка́, легки́й | ✗ дочка́ | ✓ | ✓ | ✓ | ✗ дочка́ | ✗ дочка́ | ✗ дочка́ | ✓ |
| 13 | за́мок / замо́к | ✗ замо́к | ✓ | ? | ✗ (unspecified) | ✗ замо́к | ✓ | ✗ замо́к | ✗ (unspecified) |
| 14 | кропива́ | ✓ | ✓ | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ |
| 15 | ви́хід | ✗ | ✓ | ✓ | ✗ | ✓ | ✗ | ✓ | ✓ |

What this shows:

1. **The lesson lines are not the problem.** On the 20 judged words of the
   4A lines, the eight variants got four words wrong, in three of 80 clips,
   none of them from Multilingual v2 or v3.
2. **Russian-stress traps are.** `дочка́` came out as `до́чка` in four
   variants, `кропива́` in three, `ви́хід` in three. Every plain variant
   failed at least one of them.
3. **Stress marks help Multilingual v2 and OpenAI.** v2 went from 3 wrong
   words to 0, OpenAI from 4 to 1. The marks fixed `дочка́` in both, and the
   homograph `замо́к` in v2. **Flash v2.5 does not use them** (3 plain, 4
   marked).
4. **One error is almost universal: `у ме́не` for `у мене́`.** Seven of eight
   variants said it, including v2 and OpenAI with the mark on the right
   syllable. Only v3 with marks said `мене́`. «У мене…» is a frequent lesson
   phrase, so this needs a fix of its own.
5. **Marks must be right, because models follow them.** Before `лі́воруч`
   was corrected to `ліво́руч` (see `stress_items.md`), two marked variants
   said the wrong `лі́воруч` and the listener caught it. The material audit in
   learnukrainian is a prerequisite, not a nicety.

**Decision.** The teacher's voice is ElevenLabs Multilingual v2 with the
`tts` rendering carrying stress marks (as `docs/architecture.md` already
plans), at $0.10 per 1,000 characters and about one second per clip before
streaming. Flash v2.5 is fast but ignores the marks and falls into the
Russian traps, so it is not the teacher's voice. v3 with marks is as good on
stress and is the only one to say `мене́`, but it is slower; it is a
candidate for pre-rendering fixed lines.

Still open:
- **`мене́`:** try an ElevenLabs pronunciation dictionary (alias rule) and
  v3 for lines with «у мене», in a short round 2 on the words the listener
  flagged.
- **Two ✗ without detail on item 13** (v3 marks, OpenAI marks): they do not
  change the decision.
- **Streaming first-audio latency** of Multilingual v2, measured in the
  engine (POC 5).
- **One listener, one voice per provider, 15 sentences.** Enough to choose;
  not a guarantee for every word, which is why the marks and a small
  per-word correction list matter.

Cost: the render, the re-renders after the two mark corrections and the
Scribe sanity check came to about **$0.35**.

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
