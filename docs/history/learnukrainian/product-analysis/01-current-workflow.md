# 1. The workflow as it is today

## The loop

One lesson part goes through six hand-offs across two disconnected
environments. Nothing in the loop shares state except the git repository and
the human carrying text between windows.

```
 Claude Code (repo)                 Claude app (no repo access)          Claude Code (repo)
 ─────────────────                  ──────────────────────────           ─────────────────
 /voice-prepare                                                          /voice-record <link>
   read tracker, queue,                                                    open share page in
   plan, material, openings                                                Chrome, scrape text
   skeleton (tool copies            paste package ──► "Ready for voice"    (or accept a paste)
     controller + accented          switch to voice, say «Почнімо»         save transcript.md
     opening lines)                 15–25 min lesson                       update tracker tables
   LLM fills 5 brief fields         «Заняття закінчено.»                   update shared queue
   `check` validates                Share → copy link                      apply checklist C1–C15
   copy to clipboard ──────────►                              ──────────►  add test-run row
   commit package                                                          commit
                                                                         /voice-iterate (when needed)
                                                                           edit controller, bump vN
```

Files that hold state, and what they are really:

| File | Role in a normal system |
| --- | --- |
| `REVIEW_MATERIAL.md`, `VOICE_OPENINGS.md`, `REVIEW_PLAN.md` | Curriculum content and syllabus (static, seed data). |
| `CLAUDE_VOICE_PROMPT.md` (controller, v4) | The teacher's system prompt, versioned by hand. |
| `voice-sessions/<date>-session-<N><part>/package.md` | A rendered, per-session prompt (controller + brief). |
| `voice-sessions/.../transcript.md` | The raw session log; the only evidence. |
| `REVIEW_TRACKER.md` | Three database tables (vocabulary evidence, sentence evidence, coverage status) plus an append-only session journal. |
| `review/REVIEW_QUEUE.md` | A cross-source spaced-repetition queue with provenance and a repetition history table. |
| `VOICE_ITERATIONS.md` | An eval log: checklist definition, settings under test, version hypotheses, test-run results. |
| `tools/voice_package.py` | The only piece of deterministic code: render skeleton, validate, refresh. |

Everything in the middle column of the table above is a relational schema
written as Markdown and maintained by an LLM. That works for one learner and
about ten sessions; the git log shows it took ~60 commits over five days to
get the rules right, and every session still costs two long agentic runs.

## What is genuinely valuable and should survive any rewrite

- **The lesson shape.** Presentation (listen and repeat the authoritative
  opening) → guided substitution of 4–6 closely related functions, one detail
  changed at a time → delayed recall without a model → neutral close. This is
  a sound, Pimsleur-like spoken-production design and it is independent of
  Ukrainian.
- **Coverage, not mastery.** "Covered" means the topic appeared in the
  accumulated transcripts; weak items go to the queue and return in a later
  lesson where they fit. This avoids the classic failure of AI tutors that
  loop on the same lesson forever.
- **Evidence labels instead of scores.** modelled / repeated / cued /
  independent / corrected-and-repeated are all observable in a transcript;
  they are honest and they compose over time. The explicit refusal to infer
  pronunciation from a transcript is correct and unusual.
- **Provenance everywhere.** Every queue target keeps its original source and
  every later practice source. This is what makes several learning tracks
  coexist without merging into a vocabulary dump.
- **The teacher is measured.** The C1–C15 checklist, the "one or two failure
  types per version" rule, the stated hypothesis and roll-back per version,
  and the test-run table are a real prompt-evaluation loop. Most language
  apps do not have this.
- **Mechanical safeguards.** The package tool copies accented text verbatim
  and rejects altered stress marks or oversized phrase sets. This is the
  right instinct: rules that can be code should be code.

## Where the friction actually comes from

### Transport
Clipboard (PowerShell on WSL), paste into a chat, a share link that renders
only with JavaScript, a browser-automation read, and a documented fallback
because "the remote session could not render the share page" and "a terminal
paste lost half of the first transcript". Every hand-off is a place to lose
turns, and none of it is portable to a phone-only user.

### Storage
Markdown tables edited by an LLM. Fine for reading; fragile for writing.
Every `/voice-record` re-derives the whole learner record from prose rules,
which is expensive and not idempotent. There is no query ("which queue
targets are Active and fit Session 3?") that is not an LLM reading a file.

### The voice layer is a black box you can only prompt at
The evidence is in the transcripts and the iteration log:

- **Speech recognition is not language-locked.** Learner turns arrive as
  `Und was? Ihr Borscht`, `Θεύσε`, `zakończymy`, `Skilki se kosztuje`,
  `Dve malenki plaški`. The teacher then has to guess whether to repair or
  correct (C13), and the record cannot say whether `хотел бы` was speech or
  transcription. A dedicated speech-to-text call with `language=uk` removes
  this class of problem outright.
- **Turn-taking is the app's, not yours.** Hands-free answers at pauses;
  push-to-talk is a workaround. Learner turns arrive split in two messages.
- **No clock, no counters.** The controller paces by "turn counts in the
  brief" because the model cannot see time. Code can.
- **Text-to-speech and stress marks.** v3 exists only because the app's
  TTS "reads accented letters badly". A TTS you call yourself can be given
  stress information in the form it understands, and the learner-facing text
  can still be plain.
- **The teacher says the learner's lines (C14, failed twice).** v4 tries to
  fix this with wording. The robust fix is structural: do not give the model
  the learner's target sentence until the learner has attempted it. A model
  cannot leak what it does not have.
- **The opening is a script pretending to be a conversation.** Eleven
  listen-and-repeat lines, one per turn, no comments: this is a state
  machine, and three checks (C3, C4, C5) exist only to make an LLM behave
  like one. In your own app the opening does not need a model at all.
- **Two of four prompt versions addressed environment, not pedagogy.** v2
  (start and close phrases that survive Ukrainian recognition) and v3 (plain
  spelling for TTS) are pure workarounds for the general-purpose voice chat.

### Scale and portability
- One learner, hard-coded in the tool (`LEARNER = "Діє́го…"`).
- One language, though nothing in the design is Ukrainian-specific except
  the content and the stress-mark handling.
- Each new user would need: a Claude subscription, the Claude app, a
  Claude Code session on a machine with the repo, and the patience to run
  three slash commands per lesson. That is not a product; it is a lab bench.

## What the transcripts say about the learner side (for product design)

- The learner produced almost nothing independently in 2C because the
  teacher modelled everything. The one unprompted sentence («Я хотів би
  каву») was "corrected". The lesson design is fine; the runtime broke it.
- Sessions end early (2B before the change-of-order cycle, 2C at cycle 3).
  Fifteen to twenty-five minutes of push-to-talk against a chat app is
  tiring. A product should make ten-minute sessions the default unit.
- The learner asks to stop in Ukrainian and is transcribed in Polish. Any
  app you own should have a stop button.
