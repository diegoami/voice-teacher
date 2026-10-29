# 2. Options for turning the loop into software

Criteria used throughout: **automatic** (no human carrying text),
**portable** (works from a phone, no repo), **scalable** (many learners,
many languages, many sources), **controllable** (can the lesson structure be
enforced rather than requested), **marketable** (could someone else use and
pay for it), **effort**.

## Option A — Keep the Claude app; add a remote MCP connector ("Claude companion")

Since July 2026 Claude's voice mode can call connected apps (Gmail, Calendar,
Notion, and custom remote MCP servers configured on claude.ai and synced to
mobile). That makes a "lesson server" possible:

```
 Claude app (voice)  ──MCP──►  lesson-server (remote, HTTPS)  ──►  database
   tools exposed to the chat:                                    (or the repo)
     start_next_lesson()      → returns the brief (controller stays in a Project)
     next_opening_line()      → returns line k; server tracks k
     record_turn(text, role)  → appends to the session transcript
     end_session()            → closes the session
```

Then the per-session workflow becomes: open the Project chat, say «Почнімо».
No clipboard, no share link. `/voice-record` reads the transcript from the
server (or the server commits it to the repo), and `/voice-prepare` can run
as a scheduled agent.

| Criterion | Assessment |
| --- | --- |
| Automatic | Mostly. Transport disappears; recording still needs an agentic run, but it can be scheduled. |
| Portable | Yes for you (phone with Claude app). Each other user needs a Claude subscription and the connector added to their account. |
| Scalable | No. One connector per Claude account, configured on the web; free tier is limited to one connected app and Haiku. |
| Controllable | Partly. The server can enforce the opening sequence (`next_opening_line` is deterministic) and can withhold the learner's target until an attempt is recorded — but only if the model calls the tools, which is itself a prompt-adherence question. Speech recognition, TTS and turn-taking remain the app's. |
| Marketable | No. It is a personal automation. |
| Effort | Low (days). A small FastAPI/Node MCP server, one Claude Project. |

**Verdict:** the right *first* step and the best value for effort. It removes
the two transport failures the iteration log complains about, and the tool
calls give you a cleaner transcript than a share page. It does not fix the
voice layer.

## Option B — Browser extension

Content script on claude.ai (or chatgpt.com): inject the package, scrape the
conversation DOM as it grows, keep state in IndexedDB, maybe drive the voice
button.

| Criterion | Assessment |
| --- | --- |
| Automatic | Only on the desktop browser; the phone app is unreachable. |
| Portable | No. |
| Scalable | No; and it breaks whenever the DOM changes, and it sits in a grey zone of the provider's terms. |
| Controllable | No. It still just types into someone else's chat. |
| Marketable | Very weak. |
| Effort | Medium, and permanent maintenance. |

**Verdict:** not worth it. Everything a browser extension would do, an MCP
connector does with an official interface, and everything it cannot do
(voice layer) needs Option C.

## Option C — Your own voice loop

A web app (desktop first, then installable on the phone as a PWA, or a small
native app later) that owns the whole session:

```
 mic ──► speech-to-text (language-locked uk) ──► session engine ──► Claude Messages API
                                                  (state machine,        (teacher turn,
                                                   DB, clock,             tool calls to
                                                   rules)                 record evidence)
 speaker ◄── text-to-speech (Ukrainian voice, stress) ◄──────────────────────┘
```

The Claude API has no audio input or output; the teacher is a text model
between two speech services. That is not a weakness here: it is exactly the
separation that lets you lock recognition to Ukrainian, choose a TTS that
handles stress, and put the lesson structure in code.

Speech services with confirmed Ukrainian support (September 2026, verify
prices before committing): ElevenLabs Scribe v2 for recognition (published
3.1% word error rate on FLEURS Ukrainian, a realtime variant exists),
Deepgram Nova-3 (cheaper, faster, weaker on Ukrainian), OpenAI
`gpt-4o-transcribe`/Whisper; for synthesis ElevenLabs, Google Cloud TTS,
Azure Neural TTS all list Ukrainian voices. OpenAI's Realtime API
(speech-to-speech, ~$0.06/min in and ~$0.24/min out) is the alternative that
skips the two services, but it removes your control over the teacher model,
turn structure and stress, and costs several times more per session.

| Criterion | Assessment |
| --- | --- |
| Automatic | Fully. Prepare, teach, record and evaluate are one pipeline. |
| Portable | Yes: a URL. Works on a phone. No Claude account needed by the learner. |
| Scalable | Yes: multi-user by construction, language-agnostic engine. |
| Controllable | Fully. Opening as a state machine; targets withheld until an attempt; praise filtered; turn budget by clock; stop button; audio retained so pronunciation becomes assessable later. |
| Marketable | This is the only option that is a product. |
| Effort | Medium to high (weeks for a solid single-user version, more for multi-user, billing, content tooling). |

**Verdict:** the destination. Details in file 03.

## Option D — Hybrid: Claude Code as author and evaluator, own app for sessions

Not a separate option so much as the sensible division of labour inside C:

- **Claude Code (or a scheduled Managed Agent)** authors lesson parts from
  material and the database, reviews transcripts against the checklist, and
  proposes prompt changes: exactly the `/voice-prepare`, `/voice-record`,
  `/voice-iterate` skills, but reading and writing a database through tools
  instead of Markdown.
- **The app** runs the session and writes structured evidence as it goes,
  so "record" becomes verification rather than extraction.

## Comparison

| | A · MCP connector | B · Extension | C · Own voice loop | D · C + agent tooling |
| --- | --- | --- | --- | --- |
| Removes clipboard / share link | ✔ | desktop only | ✔ | ✔ |
| Fixes recognition drift | ✘ | ✘ | ✔ | ✔ |
| Enforces lesson structure | partly | ✘ | ✔ | ✔ |
| Phone without Claude account | ✘ | ✘ | ✔ | ✔ |
| Multi-user / multi-language | ✘ | ✘ | ✔ | ✔ |
| Keeps the eval loop | ✔ | ✔ | ✔ | ✔ (automated) |
| Effort | days | weeks + upkeep | weeks | weeks + |

## Recommendation

Do A now, because it costs days and immediately makes the current practice
less painful; treat everything learned from it (which tool calls the voice
model actually makes, what a tool-recorded transcript looks like) as
requirements for C. Then build C in the phases described in file 03, with D
as its authoring and evaluation back end. Skip B.
