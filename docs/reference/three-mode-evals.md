# Free-conversation client and three-mode evaluation

The app offers lesson-grounded free conversation beside repetition and guided
practice. Select a lesson, Free conversation, an optional topic override and a
correction preference. Light immediate correction is the default; Feedback at
the end is the alternative. Preferences are selected before starting, as the
existing API pins them in the conversation plan.

“Practise a topic without a lesson” starts a personal Ukrainian conversation
with English explanations, without a source/course/lesson reference. A topic is
required and bounded to 500 characters. The server still checks whether dialogue
and the language policy are configured; this checkbox cannot enable a provider.
Other modes retain their lesson requirements. Provider credentials stay on the
server.

Each saved start retains mode, topic override and correction preference. Open
loads the existing owned session, including its pinned policy and topic; pause,
refresh and server restart use the existing durable controls. Changing the next
start's controls does not rewrite an existing conversation. History and evidence
use the existing progress view, with free observations separate from course
coverage. Personal review promotion remains available through the T21 API;
this change does not add promotion controls to the history panel.

## Offline regressions

```bash
uv run pytest tests/evals -q
uv run python tools/evals/run.py
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e -- free-conversation
```

The original synthetic fixtures in `tests/evals/cases.json` include valid samples
and deliberate defects. The report separates repetition, guided conversation
and free conversation. A case passes when the detected defects match its authored
expected defects; a rejected deliberately bad candidate is a passing regression,
not a claim of good model quality. It catches invented quoted words/corrections,
wrong accepted-turn references, premature hidden targets, incorrect assistance
labels, off-topic dialogue, false mastery claims and excessive reply length.
Valid corrections include an independently authored original/preferred pair.
The production feedback validator checks references; the fixture's semantic
oracle additionally catches a plausible-looking but invented correction.
These limited text checks are not pronunciation or general teaching evaluation.

The browser checks run a real temporary API/SQLite process with synthetic
speech/dialogue and mocked browser media. They select all three lesson modes,
sustain three free turns, select end feedback, pause, restart the server, refresh
and reopen the source-free topic with the original preference. Desktop and
Android emulation exercise the same paths. Physical-phone acceptance remains T19.

## Opt-in live probe and acceptance limits

```bash
uv run python tools/evals/live.py --live \
  --model google/gemini-3.8-flash --turns 3 \
  --reasoning-effort minimal --reply-tokens 512 \
  --output /private/fresh-directory --speech
```

No provider call occurs during offline evaluation or import. The live probe
requires explicit opt-in and an exact model; it checks the live catalogue and
never substitutes another model. `--turns` permits one through six; each turn
can make one dialogue and one feedback call, plus optional synthesis. No request
is automatically retried. `--reply-tokens` selects an explicit supported dialogue
budget (64–512, default 256). Operators must count attempted turns across any
manually started runs; restarting the script is not a fresh acceptance budget.

Existing environment credentials are used without printing them. Reports,
synthetic runtime state and optional speech files go in a fresh private directory
outside every Git checkout, with private modes. Partial reports survive a
provider failure. Safe HTTP status/model/finish metadata is recorded, without
credentials or raw provider errors. The script uses the existing POC voice and
Multilingual v2 defaults. It sends synthetic written inputs, so even a completed
run cannot claim human conversation, real recognition or listening acceptance.

2026-10-17 pre-merge check: the exact selected model was available in the
OpenRouter catalogue. Three manually supervised attempts used the same first
synthetic train-travel turn: default 256 tokens, 256 tokens with response metadata
outside the outer sandbox, and the supported 512-token budget. The latter two
returned HTTP 200, the exact selected model and `finish_reason: length`; the
production adapter refused the truncated replies. The first sanitized failure
has no HTTP diagnostic and cannot independently establish its finish reason.
All three stopped before an accepted turn; no feedback or speech was generated.
No model substitution occurred, and only three of the six permitted turns were
attempted. Private original reports are retained outside the checkout.

### Resumed check: three accepted turns

The owner then authorized continuing the same task/model combination. The
remaining three attempts used the unchanged exact model, explicit `minimal`
reasoning and a 512-token dialogue budget. All three accepted turns completed,
including real post-attempt feedback, and ElevenLabs Multilingual v2 generated
three nonempty private MP3 samples. Total attempted dialogue turns across all
runs: six (three initial failures, three successes). No additional live call is
authorized by restarting the probe. The successful private run and its SQLite
state remain outside Git; no learner recording was used.

Text inspection found sustained train-travel topic, brief follow-up questions,
and the correct plural correction `два квиток` → `два квитки`, attributed to the
actual third learner turn with outcome `observed`. The first turn produced no
observation; the second a neutral observation. No course mastery/completion was
inferred. Quality limits: repetitive `Чудово` praise and an unverified illustrative
fare appeared in the role-play. The third response includes the engine's English
turn-limit message. These observations are a small synthetic sample, not human
conversation acceptance or a general quality claim.

The initial resumed metadata collector observed compressed wire bytes and could
record HTTP200 only; it did not retain per-response model/finish/token fields.
The exact requested model is established by the request configuration and public
catalogue, not a retained per-response attestation. Accepted replies nevertheless
passed the actual production adapter's strict JSON, finish-reason and claim
checks. The collector now observes decoded bytes with a 64KiB cap; offline gzip
and oversized-response tests verify it. No extra paid run was used to validate
that diagnostic fix. Raw reasoning is never retained by the collector. Reasoning
budget exhaustion is a documented explanation consistent with the initial
failures; their original reports lack usage counts, so the exact spent reasoning
count cannot be reconstructed.

**Human acceptance remains incomplete.** Three generated speech files are
available privately for listening, but no intelligibility/stress judgement has
been received. Generated words do not have authored, dictionary-checked stress
guarantees. Unscripted human conversation, real microphone and physical Android
checks remain incomplete. The live integration blocker is resolved; DW3's
remaining manual acceptance has not been marked passed, and T22 stays unmerged
until required acceptance and independent approval are satisfied.
