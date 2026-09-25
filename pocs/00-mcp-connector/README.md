# POC 0 — Lesson connector (remote MCP server for the Claude app)

## Question

Can the Claude app's voice mode run a lesson through a remote MCP connector
(start the lesson, follow the opening, record every exchange, end the session)
reliably enough to replace the clipboard paste and the share-link scrape?

## What was built

A small MCP server (Python, official `mcp` SDK 2.2, Streamable HTTP) with
three tools. It reads prepared packages from a local `learnukrainian`
checkout and never edits them; it writes only to `data/` here, until you
export.

| Tool | When the teacher calls it | What it does |
| --- | --- | --- |
| `start_lesson(start_command)` | The learner says «Почнімо» or asks for a lesson. | Picks the newest `voice-sessions/` folder whose transcript is still the template (today: 3A, prompt v4), opens a session, returns the package with a short delivery note on top. |
| `turn(session_id, teacher_said, learner_said)` | After every learner turn, before speaking. | Appends the exchange to the log. During the opening it answers with the exact next line to say; afterwards (since run 2) with the current and the next Guided sequence step or Delayed recall prompt. |
| `end_session(session_id, closing, transcript)` | Just before «Заняття закінчено.» | Marks the end and stores the teacher's write-up of the whole lesson (`transcript`, since run 2) and what the tracker noticed. |

Design decisions worth knowing:

- **The opening is tracked from evidence, not intent.** The server advances
  to line *k+1* only when the teacher's reported turn contains line *k*. It
  allows one re-say per line and logs merged, skipped and re-said lines. This
  is the first test of "rules into code" (checks C3 and C4).
- **The controller is unchanged.** The package is served exactly as
  `/voice-prepare` wrote it. The only addition is the delivery note, which
  tells the teacher to skip the ready sentence and to call the tools. Results
  stay comparable with the v4 runs.
- **One call per exchange.** `turn` carries the teacher's previous turn and
  the learner's latest one, so the log is complete with a single tool call
  per learner turn.
- **Access control is a secret path.** The URL contains a random token
  stored in `data/token` (git-ignored). There is no OAuth. Anyone with the URL
  can start a lesson and write a log, and nothing else. DNS-rebinding
  protection is off because the server is reached through a tunnel.
- **Transcript provenance.** Learner text in the log is what the teacher
  copied into the tool call, not the app's own recognition output. The first
  run must compare it with the share page.

## Changes for run 2 (2026-09-24)

- `end_session` requires `transcript`: the whole lesson, one turn per line
  with `Teacher:` / `Learner:`, learner turns exactly as transcribed. The
  export writes it above the per-turn log.
- `turn` keeps returning something useful after the opening: where the
  lesson is and the next step, then the next recall prompt, then the
  instruction to call `end_session`. Progress is derived from what the
  teacher reports having said: a step advances when the teacher's turn
  contains three quarters of the words of that step's «…» line (exact match
  for one- or two-word lines), so small rewording does not stall it.
- Replayed against the teacher turns of the real 3A lesson, the tracker
  followed all ten guided steps and all six recall prompts in order and
  flagged nothing except the one real re-say (`tests/test_lesson.py`).
- `uv run pytest`: 8 passed.

## Verified before run 1 (2026-09-23)

- Unit tests of package parsing and the opening tracker against the real 3A
  package, and an end-to-end test that runs a full simulated lesson over
  HTTP with the SDK client, then exports the transcript. `uv run pytest`:
  6 passed.
- Live check through a Cloudflare quick tunnel: the SDK client listed the
  three tools at the public URL, and a request to the wrong path got 404.
- Not yet verified: that claude.ai accepts the URL as a custom connector
  without OAuth, and everything about voice mode below.

## Running a session

One-time: `uv` and `cloudflared` (installed in `~/.local/bin`). The
`learnukrainian` checkout is expected next to `voice-teacher`; otherwise set
`LEARNUKRAINIAN=/path/to/learnukrainian`.

1. In `learnukrainian`, prepare the lesson as usual with `/voice-prepare`.
   The clipboard step is no longer needed. 3A is already prepared.
2. Start the connector:

   ```bash
   ./run.sh
   ```

   It prints `Connector URL (keep it private): https://….trycloudflare.com/<token>/mcp`.
3. On claude.ai (web): Settings → Connectors → Add custom connector. Name it
   `Ukrainian lessons` and paste the URL. The quick-tunnel host changes on
   every run, so edit or re-add the connector each time.
4. On the phone: new chat, check in the tools menu that the connector is on,
   enter voice mode (push-to-talk, voice language Ukrainian), say «Почнімо».
5. If the teacher does not call `start_lesson` (it greets you or asks what
   you mean), stop and try variant B: in text, type `Почнімо урок` first,
   then switch to voice. Variant C, if B also fails: a Claude Project whose
   instructions are the text below, and start the chat inside the Project.

   ```text
   Every chat in this project is a spoken Ukrainian lesson. On the learner's
   first message, whatever it says, call start_lesson from the Ukrainian
   lessons connector and follow the package it returns.
   ```
6. After the close, also share the chat and keep the link: this first run
   compares the connector's log with the app's own transcript.
7. Back here:

   ```bash
   uv run python -m connector sessions
   ```

   ```bash
   uv run python -m connector report <session id>
   ```

   ```bash
   uv run python -m connector export <session id> --write
   ```

   The last command writes `voice-sessions/<folder>/transcript.md` in
   `learnukrainian` (only if it is still the template). Then run
   `/voice-record pimsleur-review/voice-sessions/<folder>` there as usual.

## What to observe

Run 1: 2026-09-23, Session 3A, prompt v4, connector session
`2026-09-15-session-3A-39598d`. Filled from the connector log, the share page text
pasted by the learner, and the learner's answers.

| Observation | Result |
| --- | --- |
| claude.ai accepted the URL without OAuth | Yes. The connector also synced to Claude Code sessions on the same account. |
| Other connectors | The lesson started only after **all other connectors were switched off** in the chat. |
| Variant that started the lesson | B: `Почнимо урок` typed, then voice. Variant A (spoken start) not tried yet. |
| Opening followed the server's instructions | Yes. All 11 lines, in order, one per turn; line 1 re-said once after the garbled `Точно има.`; no merged or skipped lines; no stress marks in teacher turns. |
| `turn` called after every learner turn | **No.** 15 calls: all 13 of the opening plus 2 of the guided sequence. At least one exchange is missing between calls 14 and 15, and after 21:48:43 there is no call for five minutes until `end_session` at 21:53:50. |
| Learner text in the log identical to the share page, or tidied | Identical on all eight overlapping learner turns, garbled ones included (`Точно има.`, `Ho cotrigo, Dini.`). |
| Share page complete | **No, as copied.** Each copy of the page captured only part of the conversation (two copies, two different parts). |
| Teacher's write-up on request | **Complete and faithful.** Asked after the close to write the lesson down, the teacher produced every turn; it matches the log and both page copies word for word where they overlap. It also said, unprompted, that it had stopped sending turns to the connector partway through the guided part. |
| Delay added by the tool calls | None noticed by the learner. Median 11 s between calls, which includes speaking and answering. |
| `end_session` called, clean close | Yes, with «Заняття закінчено.». |
| Teacher mentioned tools, recording or the session id aloud | No. |

## Answer (after run 1)

**Partly yes.** The connector replaces the paste completely: the package was
delivered by the tool and the lesson started on the learner's command. While
the tool result told the teacher what to say next, the teacher called it on
every turn and followed it exactly, so the opening was the cleanest yet (C3,
C4). Once the result became a bare «Recorded.», the teacher skipped a call,
then stopped calling altogether. The log is therefore not a complete
transcript, and copying the share page gives only fragments. The complete
record came from asking the teacher, after the close, to write the lesson
down; it matched every raw source where they overlap. Session 3A is
recorded in learnukrainian from all four sources side by side.

Changes for run 2, one per purpose:

1. **Transcript:** `end_session` takes a `transcript` argument, and the
   delivery note asks for the whole lesson in the same format as the
   write-up above. The connector then holds the complete record without a
   copy step, and the per-turn log remains a raw cross-check.
2. **Opening and pacing (hypothesis):** the teacher calls a tool when its
   result helps with the next turn. If `turn` keeps returning the next
   Guided sequence step, then the next Delayed recall prompt, calls should
   continue to the end. That is also the first step of POC 5, where the
   server hands out the brief one step at a time.

## Run 2 (2026-09-25, Session 4A)

Connector session `2026-09-24-session-4A-d7bd84`, prompt v4, start typed,
other connectors off. Recorded in learnukrainian with all three records.

| Observation | Result |
| --- | --- |
| Lesson started from the tool | Yes, second time out of two. |
| `turn` called to the end | **No.** 14 calls: the opening and two conversation turns. Four were filed in a burst after the teacher said aloud «I owe the connector a turn call… Let me log them now». The step tracker never got past guided step 1. |
| Step-by-step tool results kept the calls going | **No.** Calls stopped earlier than in run 1. |
| Teacher spoke about tools or its process | **Yes, in six turns, in English** («…the tool instruction says to repeat only if unintelligible or meaning-changing…», «Note: I owe the connector a turn call…»). The first leak was deliberation over the conditional opening instruction. |
| `end_session` transcript | Sent, all turns present, but **tidied**: no English asides, no stop speech, one re-say dropped, the cut-off turn replaced by a placeholder. |
| Write-up on request after the close | Complete and candid: it kept the asides and listed the teacher's own failures. |
| Pause before the close | Acceptable to the learner. |
| Recognition | Learner turns arrived almost entirely in Russian spelling, with the app's voice language set to Ukrainian; the teacher stopped the lesson over it. |

## Answer (after run 2)

**The connector is good at one thing: delivering the lesson.** Twice out of
two, `start_lesson` replaced the paste cleanly.

**It does not work as a recorder or as a steering channel.**

- The teacher stops calling a per-turn tool early, whatever the tool
  returns.
- In voice mode, anything the model reads can end up spoken. Longer English
  tool results with conditions made it deliberate aloud in English. Steering
  through tool results made the lesson worse, not better.
- Transcripts the teacher writes for a tool are tidied: they are fine for
  vocabulary and sentences, but not as evidence of the teacher's own
  behaviour. A free-text write-up on request was more candid than the tool
  copy.

For the architecture this is the strongest argument yet for POC 5. Lesson
structure cannot be enforced from outside a general-purpose voice chat; the
opening, the step order and the recording have to live in an engine that
owns the turn loop.

## Run 3 setup: delivery only (built 2026-09-25)

`serve --mode delivery` is now the default (`./run.sh --mode full` restores
run 2). The app sees one tool, `start_lesson`. It returns the package behind a
two-sentence note: skip the ready sentence, begin the opening. There is no
session id, no mention of tools or recording, no per-turn call and no
end-of-lesson call, so prompt v4 runs as it would after a paste. The server
logs only the start.

Run 3 reruns Session 4A from the folder `2026-09-25-session-4A` (same package
as the stopped 4A). After «Заняття закінчено.», leave voice mode and type:

```text
Write down the whole lesson, every turn in order from your introduction to the
closing sentence. Put my lines exactly as speech recognition transcribed them,
and include anything that went wrong.
```

Paste the answer to Claude Code in learnukrainian to record the lesson.

What run 3 should show: whether the leaks (C16) disappear without tool
results, and how prompt v4 does on 4A on its own. Check the app's voice
language is still Ukrainian (it was in run 2, and recognition still drifted
to Russian).

## Known limits

- The server runs on your machine: the computer must be on and `run.sh`
  running during the lesson.
- The quick-tunnel URL changes on every start. A stable URL needs an ngrok
  free static domain or a Cloudflare named tunnel on your own domain.
- Voice-mode connector support is in beta (July 2026). The free plan allows
  only Haiku and one connected app.
- If the teacher stops calling `turn` mid-lesson, the log has a gap. The
  share link remains the fallback transcript.

## Files

- `connector/lesson.py`: package parsing, plain spelling, opening tracker.
- `connector/server.py`: the three tools and the HTTP app.
- `connector/store.py`: append-only JSON Lines log per session.
- `connector/export.py`: transcript export and the POC report.
- `connector/__main__.py`: `serve`, `sessions`, `report`, `export`.
- `run.sh`: server plus tunnel.
- `tests/`: unit and end-to-end tests.
