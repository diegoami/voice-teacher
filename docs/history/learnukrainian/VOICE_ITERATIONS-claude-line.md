# Voice teacher iterations

This file tracks how well each version of the voice-teacher prompt in
[CLAUDE_VOICE_PROMPT.md](CLAUDE_VOICE_PROMPT.md) works in real sessions, so
that successive versions can be compared on evidence rather than impression.

It records **teacher behaviour only**. The learner's vocabulary and sentence
practice stay in [REVIEW_TRACKER.md](REVIEW_TRACKER.md) and
[`../review/REVIEW_QUEUE.md`](../review/REVIEW_QUEUE.md); nothing here scores
the learner.

## How an iteration works

1. `/voice-prepare` builds a package with the current prompt version.
2. The session is run in the Claude app (voice, or a typed dry run).
3. `/voice-record` records the learner's practice **and** adds one row to
   **Test runs** below, applying the adherence checklist to the transcript.
4. `/voice-iterate` reads the failed checks across recent runs, changes the
   controller for at most one or two failure types, bumps the prompt version,
   and adds a **Versions** entry stating the hypothesis to be tested.
5. The next session tests that hypothesis. Keep a change if its target checks
   pass in the next run(s); otherwise revise or revert it.

Change few things per version so that an improvement or regression can be
attributed to a specific change. Settings (model, input mode, voice language,
pace) are also variables: change them one at a time and record them.

## Adherence checklist

`/voice-record` marks each check **pass**, **fail**, or **n/a** from the
transcript alone. Cite the turn that shows a failure.

| ID | Check | Passes when |
| --- | --- | --- |
| C1 | Waits on receipt | The reply to the package is only the ready sentence. |
| C2 | Starts on command | Teaching begins only after the start command, with the teacher introduction. |
| C3 | Full opening | Every opening-review line is presented, in order, with none skipped or merged. |
| C4 | One line per turn | During the opening each teacher turn is only the next line (plus a single re-say when meaning was lost). |
| C5 | No routine praise | No praise, thanks, or evaluation after routine repetitions or answers. |
| C6 | Scope | Practice stays within the active phrase set (≤ 6) and listed weak expressions (≤ 2); no unprepared topics or vocabulary without a meaning given first. |
| C7 | Short turns | Teacher turns are one or two sentences with at most one question. |
| C8 | Correction routine | Important errors get «Виправлення: …», chunk repetition, full sentence, and later reuse with one changed detail. |
| C9 | Delayed recall | Recall prompts are asked without a model before the learner's first attempt. |
| C10 | Ukrainian first | English only when asked or after two failed Ukrainian explanations. |
| C11 | Voice formatting | No markdown, lists, emoji, labels, or spoken line numbers in teacher turns. |
| C12 | Clean close | The closing sentence is used; no summary, scores, or tracker content, even when asked. |
| C13 | Recognition repair | Garbled or cut-off learner turns get a repeat/continue request, not a grammar correction. |
| C14 | Attempt before model | In the guided sequence the learner gets to try first; if stuck, a partial cue comes before the full target sentence. (Added 2026-09-14 after the first Claude transcript.) |
| C15 | Plain spelling | Teacher turns contain no stress marks (acute accents): the brief's marks are used for pronunciation, not reproduced. (Added 2026-09-15 with v3.) |
| C16 | No meta-talk | Teacher turns never contain notes about the brief, the tools, the recording, or the teacher's own process, in any language. (Added 2026-09-25 after 4A.) |

Also note, outside the checklist, anything the learner reported about audio in
the transcript's **Test settings** block (stress, speed, cut-offs, voice).

## Settings being tested

| Setting | Current choice | Alternatives to try |
| --- | --- | --- |
| Voice language | Ukrainian | English (only if Ukrainian recognition proves worse) |
| Input mode | Push-to-talk | Hands-free |
| Speech pace | Slightly slower | Default |
| Model | Sonnet or Opus (record which) | The other one |
| Stress marks in teacher replies | Plain spelling (v3; kept in v1–v2) | Kept, if the teacher misplaces stress in copied lines without them |
| Package delivery | Pasted into an ordinary chat | Lesson connector (voice-teacher POC 0): run 1 in 3A delivered cleanly; run 2 in 4A, with step-by-step tool results, coincided with English meta-talk spoken aloud (C16). Controller as Claude Project instructions |
| Teacher app | ChatGPT Voice (prompt line g1, g2, … in `CHATGPT_VOICE_PROMPT.md`), default since 2026-09-26 after the 4A comparison | Claude voice mode (prompt line v1, v2, …), on hold while its speech recognition turns Ukrainian into Russian |

## Versions

### v0 — ChatGPT Voice (baseline, until 2026-09-13)

Prompt: former `CHATGPT_LIVE_PROMPT.md` (see git history). Preparation and
recording ran through a GitHub-connected ChatGPT chat.

Observed problems, from the Session 2A process note in `REVIEW_TRACKER.md`:

- Presented the teacher introduction but only the first of eleven opening
  lines (C3 fail).
- Repeated that line unnecessarily (C4 fail).
- Praised routine repetitions (C5 fail).
- Moved into changing orders, prices, and a shop before the focused café
  practice was complete (C6 fail).
- Asked for an overloaded multi-step summary sentence that the learner could
  not produce (C6/C7 fail).

Earlier iterations of the ChatGPT prompt (2026-09-09 to 2026-09-12) also
removed Voice-generated tracker updates and scores because they were not
reliable; the transcript became the only evidence.

### v1 — Claude voice mode (2026-09-14)

First Claude version. Changes relative to v0 and the hypothesis behind each:

- **Written for text-to-speech.** Plain sentences only; no markdown, lists,
  labels, or spoken numbers (C11). Claude voice reads its text reply aloud, so
  formatting would be spoken or would break pacing.
- **Opening folded into fewer turns.** Introduction, the listen-and-repeat
  instruction, and line 1 in the first turn; afterwards each turn is only the
  next line. The brief numbers the lines and states the count so the teacher
  can keep its place (targets v0's C3/C4 failures).
- **Explicit no-praise list** with named Ukrainian and English praise words
  (targets C5).
- **No multi-step summaries** (targets the v0 overload).
- **Speech-recognition repair**: garbled or cut-off learner turns get
  «Повторі́ть, будь ла́ска.» / «Продо́вжуйте.» instead of a correction (C13).
- **Turn counts instead of minutes**, because the model cannot see a clock.
- **Learner profile** in the brief so gendered forms and personal details are
  consistent.
- **Mechanical copying.** `tools/voice_package.py` copies the controller,
  introduction, and opening lines exactly and rejects packages with altered
  stress marks or oversized phrase sets.

Test results (2026-09-14, Session 2B, one voice run — see Test runs):

- **Fixed v0's main failures:** all eleven opening lines, in order, one per
  turn (C3 pass); no routine praise (C5 pass); short turns, Ukrainian only,
  no formatting (C7, C10, C11 pass).
- **C2:** the English trigger was misrecognised («Тарт з сещо.»); the teacher
  correctly asked for a repeat and started on «Почнімо!». Addressed in v2.
- **C13 fail:** plausibly valid but garbled answers were "corrected" instead
  of re-asked — `Ях у тих би гриби, суп` (likely `Я хотів би грибний суп`) was
  replaced with a different target, and `бігабу` (likely `би каву`) got
  «Скажі́ть пові́льно: «ка́ву»», which is a pronunciation correction.
- **C14 fail:** full target sentences were supplied before the learner tried —
  «А яки́й суп у вас є? Скажі́ть це.» and «І ще скля́нку води́?».
- **C4/C8 minor:** during the opening, line 3 got a three-turn correction
  routine instead of one re-say; «Негазо́ваної. Скажі́ть це.» dropped the
  «Виправлення:» label and the chunk → sentence → reuse steps.
- **Design observation:** opening lines that are questions (`Що бу́дете
  замовля́ти?`, `У вас є борщ?`) invited answers instead of repetitions.

Candidates for the next version: C13 and C14.

### v2 — Ukrainian-only spoken triggers (2026-09-14)

Targets **C2** (starts on command) and, pre-emptively, **C12** (clean close):
both depended on English passing through Ukrainian speech recognition or
Ukrainian text-to-speech.

- **Start:** the learner says «Почні́мо», and the teacher treats *any* first
  voice turn as the start command, however it was transcribed, instead of
  matching a phrase. The ready reply tells the learner to say «Почні́мо».
- **Close:** Ukrainian only («Заня́ття закі́нчено.»); the English hand-back
  instruction was removed, because a Ukrainian voice would read it aloud and it
  was for the learner, who already knows the workflow.
- **Asking for English:** the learner says «Англі́йською, будь ла́ска»; the
  teacher is told that learner English may arrive as Ukrainian-looking
  nonsense.

Kept in English on purpose: the controller instructions. The failure was in
speech recognition, not in how Claude reads its instructions, and English
instructions stay easy to review. A fully Ukrainian controller remains a
possible later experiment, changed on its own.

Hypothesis: with v2 the lesson starts on the first voice turn (C1–C2 pass) and
ends with a clean Ukrainian close (C12 pass). Watch next: whether the teacher
also begins correctly when the first turn is a greeting rather than «Почні́мо».

Test results (2026-09-15, Session 2C, run on v3, which keeps the v2 wording —
see Test runs): C1, C2 and C12 pass. The ready reply was exact, the lesson
started on the first voice turn («Počnimo.», transcribed in Latin script),
and the close was «Заняття закінчено.» when the learner said «Eh,
zakończymy.». Keep.

### v3 — Plain spelling in teacher replies (2026-09-15)

A settings change requested by the owner, not a fix for a failed check: the
row **Stress marks in teacher replies** moves from *Kept* to *Plain spelling*.

- **Controller rule replaced.** "Keep the Ukrainian stress marks exactly as
  written in the brief" became: the brief's acute accents tell the teacher
  where the stress falls; the teacher writes every turn, including the copied
  opening lines and any phrase taken from the brief, in plain spelling, and
  never mentions the marks.
- **Fixed phrases written plain.** The ready reply, the repair requests, the
  opening cue, and the close inside the controller no longer carry marks, so
  the examples match the rule. The `«Почні́мо»` in the human-facing setup text
  is unchanged.
- **The brief keeps its marks.** `skeleton` still copies the introduction and
  opening lines from `VOICE_OPENINGS.md`, and `check` still rejects altered
  marks. No material file changes.
- **New check C15** (plain spelling) so that `/voice-record` can measure the
  rule instead of noting it in prose.

Hypothesis: text-to-speech reads plain words naturally, and the teacher still
stresses the copied lines correctly because the brief shows where the stress
is. Watch next: accents leaking into teacher turns (C15), and whether the
learner hears misplaced stress in the opening lines or the guided questions.

v2 has no test run yet, so the next session tests v2's start and close
changes (C1, C2, C12) and this change together. If a start or close check
fails, attribute it to v2's wording, not to the spelling.

Roll back: restore the v2 controller from git (commit `3de56e3`), revert the
settings row, and drop C15.

Test results (2026-09-15, Session 2C, one voice run, Opus 5 — see Test
runs): C15 pass — no stress marks in any of the 44 teacher turns, and the
learner reported nothing about the audio. C14 failed again (second run in a
row): the guided sequence was run as listen-and-repeat. The teacher supplied
«Дайте три яблука і один банан.», «Так. Скільки це коштує?», «Можна
заплатити карткою?», «Дякую. До побачення.» and the whole cycle-2 order
before any attempt, often adding «Скажіть це.». C8 misuse: «Виправлення:»
was used to redirect valid learner sentences («Я хотів би каву») to the
brief's item. Candidate for v4: C14, together with the brief wording "The
learner asks for…", which the teacher may read as lines to speak.

### v4 — The teacher stops saying the learner's lines (2026-09-15)

Targets **C14** (attempt before model), failed in both Claude runs so far, and
the **C8** misuse seen in 2C.

Diagnosis from the 2C turns: the teacher treated the brief as a script. Steps
written as "The learner asks for two small bottles" were spoken by the teacher,
often followed by «Скажіть це.», so ten of the shop turns were models to
repeat and the learner produced almost nothing without one. The same reading
made «Я хотів би каву» look like an error to correct («Виправлення: У вас є
вода?»), although it was correct Ukrainian and a good shop opening — the
learner's one independent contribution in the session.

- **New Guided-sequence rule.** A step names the teacher's line and then what
  the learner is to say; the teacher speaks only its own line and waits. Says
  explicitly that the Active phrase set is what the learner must produce, not a
  list for the teacher to read, and that telling the learner to repeat a
  sentence the teacher just said belongs to the opening, not the lesson.
- **Cue ladder.** No answer, or an answer in the wrong language, gets a partial
  cue (the first word or two, or the question form) first; the whole sentence
  comes only after a second failed attempt.
- **Correction narrowed.** Correct only wrong Ukrainian. A correct sentence
  that orders something other than the step expected is accepted and the
  conversation continues from it.
- **Delayed recall** now says one prompt at a time, no model *and no cue*
  before the first attempt.
- **Brief wording, in `/voice-prepare`.** The learner's part must be written as
  an outcome ("Wait for the learner to ask for two small bottles"), never as a
  Ukrainian sentence, because a Ukrainian sentence in a step is read as a line
  to say. This is half the fix: the controller change alone would still meet
  briefs that hand it the learner's words.

Hypothesis: with the script reading removed, the learner attempts each target
before hearing it, and the transcript shows cues rather than full models
(C14 pass), while the opening still works as listen-and-repeat (C3, C4 pass).
Watch next: whether the teacher now waits too long or drifts off the sequence
when an accepted sentence differs from the step, and whether refusing to
correct a valid off-step sentence loses the lesson's focus (C6).

Roll back: restore the v3 controller from git (commit `9a06ef4`) and revert
the `/voice-prepare` bullet.

Test results (2026-09-23, Session 3A, one voice run delivered by the lesson
connector — see Test runs): **C14 pass on every step in the record.** The
learner answered the first two guided questions before any model
(`Ні, я не вільний сьогодні ввечері.`, `А завтра я вільний.`), and the
teacher gave only its own lines. C3, C4 and C15 pass: all eleven opening
lines, one per turn, one re-say, plain spelling; the connector also told the
teacher each next line. C9 pass: every recall prompt was answered before any
model. **C8 fail, third run in a row:** in recall the teacher redirected
three valid sentences to the brief's wording — `Сустрінемося завтра о
сьомій.` → «Виправлення: може, зустрінемося завтра о сьомій?», `Може,
пообідаємо разом.` → «Виправлення: хочете пообідати разом?», `Так, до
завтра.` → «Виправлення: домовилися.». v4's "correct only wrong Ukrainian"
did not hold once the prompt asked for a specific function. The same
happened in the guided sequence: `Так, я запрошу друга.` got «Відповідь була
ствердна, а тут треба заперечна. Скажіть: я не запрошу друга.», because the
brief's step demanded a negative answer to a yes/no question, and `На
станции метро.` was redirected to `біля` (valid if said `на станції`).
The four «Виправлення: так.» after Russian `да` were proper corrections.
**C14 minor:** after two garbled answers at the `зайнятий` step the teacher
went from «Повторіть, будь ласка.» and a rephrase straight to the full
sentence, without a partial cue. **C7 minor:** «А тепер я читатиму по
одному завданню.» announced the recall. C6 pass: the teacher followed all
ten steps and stayed in scope, including when the learner invited it to
the theatre instead of lunch. Candidate for v5: C8 (redirecting valid
sentences), together with the `/voice-prepare` rule that a step must not
prescribe the learner's answer, such as its polarity.

Test results (2026-09-25, Session 4A, one voice run, lesson connector run 2 —
see Test runs): a failed lesson, and not a clean test of v4. **C16 fail, new:**
the teacher spoke English notes about the tool instructions and its own
process in six turns. The first leak was deliberation over the connector's
conditional opening instruction («…the tool instruction says to repeat only
if unintelligible or meaning-changing…»), and later ones were about owing
`turn` calls. The connector's run 2 change (longer English tool results after
every learner turn) is the likely trigger, since run 1 had the same
controller and no leaks; attribute C16 to the connector, not to v4. C4, C13
and C14 also failed, and the teacher stopped the lesson itself after the
first route. Almost every learner turn arrived in Russian spelling, which
made correction impossible; the voice language was set to Ukrainian, so this
is the app's speech recognition, not a setting and not the prompt. Next run: rerun 4A with a connector that returns no instructions
(delivery only), so that v4 is tested alone.

### g1 — ChatGPT Voice comparison (2026-09-25)

A second prompt line in [CHATGPT_VOICE_PROMPT.md](CHATGPT_VOICE_PROMPT.md),
started because Claude voice mode's speech recognition turned almost every
learner turn in 4A into Russian spelling although its voice language was
Ukrainian. ChatGPT Voice hears audio directly instead of reading a
transcript.

g1 is Claude v4 with only the platform parts changed: ROLE names ChatGPT
Voice; the plain-spelling rule becomes "pronounce with the marked stress"
(C15 does not apply); the recognition-repair rule becomes "if you did not
understand, ask for a repeat"; and two lines are added, no spoken notes about
the instructions (C16) and "let the learner finish". OPENING, LESSON, CLOSE
and the brief are v4 word for word, so a 4A run on each app compares the apps
rather than the prompts.

What to compare with the Claude 4A runs: misrecognised learner turns, learner
sentences produced without a model, and the failed checks. Record the run in
the table below with Mode `voice, ChatGPT`.

**Comparison run (2026-09-26, 4A):** by mistake the Claude v4 package was
pasted into ChatGPT, which made it a clean comparison: same prompt, same
brief, different app. Recognition decided it. All 27 learner voice turns
arrived as Ukrainian (two unclear), against almost all Russian-spelled turns
in the Claude 4A run. The opening was the cleanest yet: twelve lines, one per
turn, no re-says, no comments. ChatGPT also had no meta-talk (C16). It still
failed C14 twice, as Claude did before v4: it modelled `Після перехрестя
направо` after one unclear answer, and asked «А чи це далеко?» itself. It
skipped guided step 3, said «Майже.», and brought in `направо` instead of the
brief's `праворуч`. The CLOSE rule made it refuse a request to write the
lesson down, so the transcript comes from the share link
(`tools/chatgpt_share.py`).

Decision: ChatGPT Voice is the default teacher from 2026-09-26; the next
package uses g1. Test results for g1 itself: pending.

**Stress fix (2026-09-27).** g1 tells the teacher to pronounce the marked
stress, and the material marked «лі́воруч» instead of «ліво́руч» (СУМ-20,
goroh). The 4A packages sent to Claude and ChatGPT carried it five times;
the ChatGPT run pronounced the brief's stress, while Claude v4 used plain
spelling. A dictionary audit then corrected 33 more words, several of them
spoken in openings (`по́тім`, `запита́єте`, `поя́снювати`, `вказіво́к`,
`хо́чу`, `мо́жу`, `дале́ко`). The 4B package was fixed before its first run.
See [STRESS_AUDIT.md](STRESS_AUDIT.md).

## Test runs

| Date | Session | Prompt | Mode | Model | Input | Failed checks | Notes | Folder |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-09-14 | 2B | v1 | voice | not recorded | not recorded | C2 (English trigger «Тарт з сещо.»; started on «Почнімо!»); C13 (`Ях у тих би гриби, суп` replaced, `бігабу` → «Скажі́ть пові́льно»); C14 («А яки́й суп у вас є? Скажі́ть це.», «І ще скля́нку води́?»); C4/C8 minor (line 3 routine; «Негазо́ваної» without label) | All 11 opening lines; no praise. Learner stopped before the change-of-order cycle, so C9 n/a. Several learner turns arrived as two messages (possible cut-offs). Transcript from share link; terminal paste lost half. | [2026-09-14-session-2B](voice-sessions/2026-09-14-session-2B/) |
| 2026-09-15 | 2C | v3 | voice | Opus 5 | not recorded | C14 (targets supplied before any attempt in both cycles: «Дайте три яблука і один банан.», «Так. Скільки це коштує?», «Можна заплатити карткою?», «Дякую. До побачення.», «Одна велика пляшка води і два банани. Скажіть це.»); C8 minor («Виправлення: У вас є вода?» and «Виправлення: хліб» corrected valid sentences that only differed from the brief) | v2 confirmed: started on «Počnimo.», closed with «Заняття закінчено.» on «Eh, zakończymy.». C15 pass: no stress marks in any teacher turn. All eleven opening lines, one per turn, single re-says for lines 4, 5 and 7; no praise; garbled turns got «Повторіть, будь ласка.». Learner stopped at the start of cycle 3, so C9 n/a. Recognition switched scripts often (German, Greek, Polish, Latin); one double learner message. Transcript pasted by the learner; the remote session could not read the share page. | [2026-09-15-session-2C](voice-sessions/2026-09-15-session-2C/) |

| 2026-09-23 | 3A | v4 | voice, lesson connector | not recorded | not recorded | C8 (valid answers redirected to the brief's wording: `Сустрінемося завтра о сьомій.`, `Може, пообідаємо разом.`, `Так, до завтра.` in recall; `Так, я запрошу друга.` at step 9); C14 minor (full sentence after two garbled turns at the `зайнятий` step, no partial cue); C7 minor («А тепер я читатиму по одному завданню.») | Package delivered by the `start_lesson` tool, start command typed. All eleven opening lines in order, one per turn; line 1 re-said once after `Точно има.`. C14 pass on guided steps 1–2; C9 pass on all recall prompts in the record. No praise, no stress marks, no mention of tools. Close «Заняття закінчено.» via `end_session`. Other connectors had to be off. Two learner turns arrived split in two messages. Guided steps 3–10 come only from the teacher's write-up after the lesson, which matches the raw sources where they overlap. | [2026-09-15-session-3A](voice-sessions/2026-09-15-session-3A/) |

| 2026-09-25 | 4A | v4 | voice, lesson connector run 2 | not recorded | push-to-talk | C16 (English working notes spoken in six turns: «The learner's repetition changed the meaning noticeably, but the tool instruction says…», «Note: I owe the connector a turn call…», «I should note the learner greeted back…»); C4 (line 4 presented three times, line 7 twice); C14 («Перепрошую...» begun for the learner; «Після перехрестя? Запитайте мене про це.» then said it; «Це далеко?», «Дуже дякую» said for the learner); C13 (`Правую руку.` for `праворуч` corrected three times as an error; «Праворуч. Одне слово: пра-во-руч.»); C12/C6 (the teacher stopped the lesson itself after the first route with a speech about recognition, then closed) | All twelve opening lines presented in order; no praise; no stress marks. Learner turns arrived almost entirely in Russian spelling, although the voice language was set to Ukrainian (confirmed afterwards). Connector: `turn` calls stopped after the second conversation turn; four were filed in a burst after the teacher said it owed them; the `end_session` transcript left out the asides and the stop speech. The teacher's write-up on request listed its own failures. | [2026-09-24-session-4A](voice-sessions/2026-09-24-session-4A/) |

| 2026-09-26 | 4A | v4 | voice, ChatGPT | `bidi` voice model (`gpt-5-6` for text) | not recorded | C14 («Скажіть, будь ласка: «Після перехрестя направо».» after one unclear answer, no partial cue; «А чи це далеко?» asked by the teacher instead of the learner); C6 minor (guided step 3 skipped; `направо` brought in for the brief's `праворуч`); C5 minor («Майже.»); C8 minor («Майже. Скажіть так: …» without «Виправлення:», for a repetitive rather than wrong route) | Comparison with Claude on the same v4 package. All twelve opening lines, one per turn, no re-says or comments; no meta-talk; «Я не зовсім зрозумів.» for an unclear turn. All 27 learner voice turns arrived as Ukrainian (two unclear). The learner ended the lesson at step 5 with «Закінчимо», so C9 n/a. Refused «Can you write the full script of the chat?» with «Заняття закінчено.» per CLOSE. Transcript read from the share link. | [2026-09-25-session-4A-chatgpt](voice-sessions/2026-09-25-session-4A-chatgpt/) |

<!-- /voice-record adds one row per transcript. Mode: voice | text dry run.
Failed checks: list IDs with a turn reference, or "none". -->
