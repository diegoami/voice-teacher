# Free-conversation observations and personal review

T21 adds a post-attempt feedback boundary. Dialogue generation remains separate
from observations: generated teacher text is never automatically evidence. With
an explicitly configured dialogue model, the server also configures feedback
using that model; `--feedback-model` / `VOICE_TEACHER_FEEDBACK_MODEL` can name a
separate explicit model. Feedback alone cannot enable free conversation. No
provider call occurs during configuration or health checks.

## What is accepted

A feedback request includes the current recorded learner turn ID and wording,
languages, at most six pinned relevant curriculum items and the existing
recognition-problem flag. It contains no unrelated learner profile, other session
history, credential or tool. This is a post-attempt boundary: the dialogue
provider's pre-attempt context still excludes target renderings.

Output is a closed object with at most three observations. Each has the supplied
`turn_id`, an exact original substring, optional `preferred` and `reason` together,
and optional `item_id`. Invented turn references, words absent from the recorded
turn, unknown/ambiguous item identities, identical-form corrections, duplicates,
extra fields, scores and tool calls fail. A known item requires a unique explicit
matching original or preferred rendering in the supplied pinned items.

Every accepted record has outcome `observed`, its actual accepted learner turn,
original wording, supported proposed form/reason and source/item provenance when
available. It does not become independent recall, pronunciation evidence, mastery
or course completion. Structural validation proves attribution and bounds; it
cannot prove a model's linguistic explanation is correct. T22's original offline
evaluations and user-selected live quality check remain required.

The OpenRouter adapter uses strict JSON schema, no tools/plugins, a 20-second
provider timeout, no automatic retry/redirect, 64 KiB response limit and 512 reply
tokens by default (configured 64–512). Context is capped at 64 KiB. Usage remains
unknown when absent; only finite, nonnegative supported usage fields are saved.
Provider errors are sanitized rather than returning raw response bodies.

## Timing and durable recovery

`light_immediate` is the user-selected default. Supported observations are saved
with the turn; at most one brief extra correction is spoken, avoiding repeating
a preferred form already present in the teacher reply. `end_of_session` holds
observations in private saved state until finish. Finish publishes them against
their original earlier learner turns and speaks at most three examples before
closing; all supported observations remain available in history. Finish makes no
new model call. Pause, refresh and restart retain the chosen policy and held work.

The dialogue reply is saved in the existing request journal before extraction.
SQLite version 7 adds `feedback_decisions`, scoped by learner/session/request and
bound to the pinned provider identity plus exact context. Calls occur outside
SQL transactions. A feedback failure retries the already saved dialogue reply;
a saved feedback decision can be replayed in a fresh process without either
provider. Observations, history, state and export jobs then commit together.
Committed delivery retries do not add another accepted attempt or observation.

New feedback-enabled conversations use coordinator capsule 6 around the existing
strict native free-session snapshot. Older capsule 5 conversations remain readable
and retain their original behavior. Pinning prevents a changed feedback provider
from generating a new turn; already saved decisions still recover without a
configured provider. Native dialogue history and its saved last reply are not
rewritten into a correction transcript. Immediate feedback adds a second bounded
provider call to a normal turn; latency/cost measurement remains T27.

Recognition uncertainty is not a confidence score. A later learner report keeps
the original observation immutable while the history view marks it uncertain,
suppresses its correction label and removes unsupported course credit. Held
feedback is not spoken as a learner correction after a report. Disputed and
superseded observations cannot create new personal review work.

## Explicit personal review

An observation is not automatically a review target. The learner explicitly
chooses its original or preferred form and supplies a review meaning. The
promotion retains the actual observation/session/turn and any known authored
provenance. It is idempotent, adds no learner or teacher utterance and changes no
practice step. A saved choice cannot silently overwrite its wording or meaning;
identical retries return the same target. Each conversation permits at most 90
choices. Held, disputed, uncertain, unknown or superseded observations cannot be
promoted. A later dispute removes a target from new practice while preserving the
original saved choice and history.

- `GET /api/v1/review-targets` lists this learner's active personal targets.
- `POST /api/v1/sessions/{id}/review-targets` takes `request_id`,
  `expected_revision`, `observation_id`, `form` (`original` or `preferred`) and
  `meaning`, returning the target and new revision.
- `POST /api/v1/sessions` with `mode: repetition` and `personal_target_ids`
  starts one or two selected targets. `recall_before_model` is optional. Omit
  repository references and conflicting lesson/free-conversation settings.

Personal practice compiles a private canonical snapshot in memory under the
app-owned `private-review-…` source namespace. It registers no lesson source and
writes no curriculum/vocabulary file or repository. The normal repetition engine
and strict trusted-plan validation perform practice. For an authored item, only
an exact pinned rendering and meaning retain that authored identity; an explicitly
changed meaning becomes a distinct private item. A novel expression has a private
item identity and retains its original free-conversation turn. Do not infer
identity by matching phrases across repositories.

Private review is a queue, not an invented lesson course. History shows its saved
sessions as Personal review and excludes its implementation snapshot from course
positions. Explicit repetition of a supported authored item can contribute its
normal item-practice evidence; the preceding free observation cannot.

The paired learner determines ownership. Other learners cannot promote an
observation or practise a guessed target ID; response models expose no private
engine/provider/profile state. T22 owns the app's free-conversation and review
controls. The API path above is already functional and tested independently.

## Archive and verification

Committed observations, held feedback and explicit target choices travel in the
existing private event/checkpoint archive. A restored held conversation can finish
without providers; a restored target can start a new repetition session with its
original provenance. Pending provider caches and HTTP request receipts are runtime
state, as before; Git export is not a backup of uncommitted work. T29 owns complete
database recovery. No personal destination is selected or pushed by this feature.

```bash
uv run pytest tests/progress/test_free_evidence.py tests/providers/test_feedback.py -q
uv run pytest tests -q
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e -- progress
```

Checks use synthetic dialogue/feedback/speech, recordings, grants and temporary
archives only. They cover real fresh-process replay, before-commit failure,
end-feedback archive restore, fabricated references, provider pinning, known and
novel item provenance, deliberate promotion, actual repetition, ownership and
stale-input rejection, late recognition reports and atomic version 6→7 migration
failure/retry. Live semantic quality, generated stress and real-phone behavior
remain T22/T19 gates, rather than claims made by these fixtures.
