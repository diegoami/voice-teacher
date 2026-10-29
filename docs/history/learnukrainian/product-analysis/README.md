# From a manual loop to a product — reflections

Written 2026-09-23 after reading the whole `pimsleur-review/` track (material,
plan, tracker, controller prompt v1–v4, the adherence log, the three recorded
voice sessions, the skills and the package tool) and the shared `review/`
queue. The vocabulary track was deliberately left aside.

These notes answer one question: **what would it take to turn the current
Claude-Code ↔ Claude-voice ↔ Claude-Code loop into software that is
automatic, portable, scalable and, possibly, sellable?**

| File | What it covers |
| --- | --- |
| [01-current-workflow.md](01-current-workflow.md) | How the loop works today, what in it is genuinely valuable, and where the friction and the failures actually come from (with evidence from the transcripts). |
| [02-options.md](02-options.md) | The candidate shapes for a product — Claude connector ("companion"), browser extension, own voice app, hybrids — compared on the same criteria. |
| [03-target-architecture.md](03-target-architecture.md) | The recommended architecture: data model, the session engine that moves rules from prompt into code, cost per session, a phased roadmap, and an honest look at marketability. |

## The short version

1. **The valuable part is not the plumbing.** It is the pedagogy (presentation
   → guided substitution → delayed recall, coverage not mastery, evidence
   labels, a shared weak-point queue with provenance) and the fact that the
   teacher is *measured* (checklist C1–C15, versioned prompt, one hypothesis
   per version). That is an evaluation harness for a voice tutor. Keep it.
2. **The friction is all in transport and storage:** clipboard, paste, share
   link, scraping a JavaScript page, and Markdown tables edited by an LLM as
   the database. All of it is replaceable.
3. **The real ceiling is the voice layer, not the prompt.** Two of the four
   prompt versions fixed things a general-purpose voice chat cannot be relied
   on for (start command, saying the learner's line), and the transcripts
   show the app's speech recognition drifting into German, Greek, Polish and
   Latin script. A teacher you control (language-locked recognition, your own
   push-to-talk, a lesson state machine) removes whole classes of failure
   instead of prompting around them.
4. **Recommendation:** in the short term, replace clipboard and share link
   with a remote MCP connector that the Claude app's voice mode can call (that
   became possible in July 2026). In the medium term, build your own voice
   loop (speech-to-text → Claude Messages API → text-to-speech) on top of a
   real database, with the lesson structure enforced in code. Claude Code
   remains the offline "curriculum author" and evaluator. Details and a
   phased plan are in file 03.

## Where the work continues

The architecture and the proofs of concept live in a separate repository,
[diegoami/voice-teacher](https://github.com/diegoami/voice-teacher)
(private, created 2026-09-23). `docs/architecture.md` there is the living
copy of file 03; this directory keeps the original analysis. Curriculum,
prompt, sessions, tracker and queue stay here.
