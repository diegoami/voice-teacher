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
| `turn(session_id, teacher_said, learner_said)` | After every learner turn, before speaking. | Appends the exchange to the log. During the opening it answers with the exact next line to say. |
| `end_session(session_id, closing)` | Just before «Заняття закінчено.» | Marks the end and stores what happened during the opening. |

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

## Verified so far (2026-09-23)

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
`2026-09-15-session-3A-39598d`. Filled from the connector log; rows marked
*pending* need the share page.

| Observation | Result |
| --- | --- |
| claude.ai accepted the URL without OAuth | Yes. The connector also synced to Claude Code sessions on the same account. |
| Other connectors | The lesson started only after **all other connectors were switched off** in the chat. |
| Variant that started the lesson | Start command `Почнимо урок`; *pending*: typed or spoken. |
| Opening followed the server's instructions | Yes. All 11 lines, in order, one per turn; line 1 re-said once after the garbled `Точно има.`; no merged or skipped lines; no stress marks in teacher turns. |
| `turn` called after every learner turn | **No.** 15 calls: all 13 of the opening plus 2 of the guided sequence. At least one exchange is missing between calls 14 and 15, and after 21:48:43 there is no call for five minutes until `end_session` at 21:53:50. |
| Learner text in the log identical to the share page, or tidied | Looks untidied (`Сара са 8.`, `Ho cotrigo, Dini.`, `Я записнуюся.` kept as recognised); *pending* comparison. |
| Delay added by the tool calls | Median 11 s between calls, which includes the teacher speaking and the learner answering; *pending*: perceived delay. |
| `end_session` called, clean close | Yes, with «Заняття закінчено.». |
| Teacher mentioned tools, recording or the session id aloud | *Pending.* |

## Answer (after run 1)

**Partly yes.** The connector replaces the paste completely: the package was
delivered by the tool and the lesson started on the learner's command. While
the tool result told the teacher what to say next, the teacher called it on
every turn and followed it exactly, so the opening was the cleanest yet (C3,
C4). Once the result became a bare «Recorded.», the teacher skipped a call,
then stopped calling altogether. The log is therefore not yet a complete
transcript and the share page is still needed.

Hypothesis for run 2: the teacher calls a tool when its result is useful for
the next turn. If `turn` keeps returning something needed after the opening
(the next Guided sequence step, then the next Delayed recall prompt), calls
continue to the end. That is also the first step of POC 5: the server hands
out the brief one step at a time. Change only this for run 2.

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
