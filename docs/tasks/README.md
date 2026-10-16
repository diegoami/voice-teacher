# Product task backlog

This backlog turns the [production plan](../production-plan.md) into separate
GitHub PRs. The main session implements by default or delegates a bounded task
to a native same-family subagent. Each PR is reviewed by an independently
chosen different-family OpenCode model through the CLI. See the
[process](../process.md) and [task template](TEMPLATE.md).

Dependencies below are merge requirements, not live statuses. GitHub issues
carry status labels and actual model/PR assignments. Creating these tasks does
not start implementation. Initial issues remain in backlog until this planning
baseline is merged and main-session preflight marks eligible work ready.
Future commands are acceptance specifications; they are not available checks
or completed validations today. Required real-device checks need learner
participation and private-data operations need a verified destination.

## Release boundaries

- **Review workflow:** T01–T02 verify the installed OpenCode integration and
  independently reviewed publication pipeline. Use the supervised bootstrap
  procedure in the process until these land.
- **Durable external-source session:** T03–T12 establish contracts, the durable
  engine/API, external lessons and separate private progress. This is the first
  server-side end-to-end slice.
- **Daily-use two-mode beta:** T13–T19 plus T28 provide repetition and guided
  conversation, phone controls, resume, history and stable local HTTPS.
- **Three-mode local release:** T20–T30 add free conversation, remote source
  refresh, historical migration, privacy, limits and tested restore. T30 is the
  acceptance gate for the complete requested local product.
- **Later hosting:** T31–T32 select and deploy an always-on target only after
  local measurements and the owner's decision.

Numbers identify tasks; dependency edges define valid order. In particular T28
must land before the real-phone T19 gate, and T11/T12 can proceed alongside
client work once their contracts exist. Keep shared file ownership coordinated;
use parallel native implementers only for independent contracts and worktrees.

## Task contracts

| Task | Outcome | Milestone | Merge after | GitHub issue |
| --- | --- | --- | --- | --- |
| [T01](T01.md) | Verify the OpenCode CLI and isolated reviewer policy | Review workflow | — | [#1](https://github.com/diegoami/voice-teacher/issues/1) |
| [T02](T02.md) | Run and publish reviews against the exact PR head | Review workflow | T01 | [#2](https://github.com/diegoami/voice-teacher/issues/2) |
| [T03](T03.md) | Define versioned curriculum and progress contracts | Durable foundation | — | [#3](https://github.com/diegoami/voice-teacher/issues/3) |
| [T04](T04.md) | Extract the tested engine into a product Python package | Durable foundation | T03 | [#4](https://github.com/diegoami/voice-teacher/issues/4) |
| [T05](T05.md) | Persist sessions and events transactionally in SQLite | Durable foundation | T04 | [#5](https://github.com/diegoami/voice-teacher/issues/5) |
| [T06](T06.md) | Make turn processing resumable and safe to retry | Durable foundation | T05 | [#6](https://github.com/diegoami/voice-teacher/issues/6) |
| [T07](T07.md) | Read existing lesson packages through a compatibility adapter | Selectable sources | T03, T04 | [#7](https://github.com/diegoami/voice-teacher/issues/7) |
| [T08](T08.md) | Register local sources and pin validated lesson revisions | Selectable sources | T07 | [#8](https://github.com/diegoami/voice-teacher/issues/8) |
| [T09](T09.md) | Expose an authenticated session and catalogue API | Selectable sources | T06, T08 | [#9](https://github.com/diegoami/voice-teacher/issues/9) |
| [T10](T10.md) | Connect speech providers to the durable turn pipeline | Durable voice loop | T09 | [#10](https://github.com/diegoami/voice-teacher/issues/10) |
| [T11](T11.md) | Export private progress events and rebuild history | Private progress | T03, T05 | [#11](https://github.com/diegoami/voice-teacher/issues/11) |
| [T12](T12.md) | Synchronize progress through a recoverable Git outbox | Private progress | T11 | [#12](https://github.com/diegoami/voice-teacher/issues/12) |
| [T13](T13.md) | Offer repetition as an independent practice mode | Two-mode app | T06, T10 | [#13](https://github.com/diegoami/voice-teacher/issues/13) |
| [T14](T14.md) | Offer guided practice in short resumable activities | Two-mode app | T06, T10 | [#14](https://github.com/diegoami/voice-teacher/issues/14) |
| [T15](T15.md) | Build the web app shell and source selection | Two-mode app | T08, T09 | [#15](https://github.com/diegoami/voice-teacher/issues/15) |
| [T16](T16.md) | Build reliable recording and teacher playback controls | Two-mode app | T13, T14, T15 | [#16](https://github.com/diegoami/voice-teacher/issues/16) |
| [T17](T17.md) | Expose pause and resume across refresh and server restart | Two-mode app | T06, T16 | [#17](https://github.com/diegoami/voice-teacher/issues/17) |
| [T18](T18.md) | Show evidence history and course-specific progress | Two-mode app | T11, T16 | [#18](https://github.com/diegoami/voice-teacher/issues/18) |
| [T19](T19.md) | Validate repetition and guided practice on Android | Two-mode beta acceptance | T12, T17, T18, T28 | [#19](https://github.com/diegoami/voice-teacher/issues/19) |
| [T20](T20.md) | Add bounded free-conversation dialogue generation | Three-mode release | T03, T14 | [#20](https://github.com/diegoami/voice-teacher/issues/20) |
| [T21](T21.md) | Record free-conversation evidence and corrections | Three-mode release | T11, T20 | [#21](https://github.com/diegoami/voice-teacher/issues/21) |
| [T22](T22.md) | Expose free conversation and evaluate all three modes | Three-mode release | T17, T18, T21 | [#22](https://github.com/diegoami/voice-teacher/issues/22) |
| [T23](T23.md) | Refresh lesson sources from configured Git remotes | Source portability | T08, T09 | [#23](https://github.com/diegoami/voice-teacher/issues/23) |
| [T24](T24.md) | Preview historical progress migration without writes | History migration | T07, T11 | [#24](https://github.com/diegoami/voice-teacher/issues/24) |
| [T25](T25.md) | Apply and reconcile a verified historical import | History migration | T12, T24 | [#25](https://github.com/diegoami/voice-teacher/issues/25) |
| [T26](T26.md) | Control recording retention and private artifact access | Operational release | T10, T11 | [#26](https://github.com/diegoami/voice-teacher/issues/26) |
| [T27](T27.md) | Bound provider work and measure actual voice latency | Operational release | T10, T16 | [#27](https://github.com/diegoami/voice-teacher/issues/27) |
| [T28](T28.md) | Run the app locally through stable HTTPS | Local operation | T09, T16 | [#28](https://github.com/diegoami/voice-teacher/issues/28) |
| [T29](T29.md) | Back up and restore runtime state and pending progress | Operational release | T12, T26 | [#29](https://github.com/diegoami/voice-teacher/issues/29) |
| [T30](T30.md) | Accept and package the local three-mode release | Local release acceptance | T19, T22, T23, T25, T26, T27, T28, T29 | [#30](https://github.com/diegoami/voice-teacher/issues/30) |
| [T31](T31.md) | Choose an always-on hosting target using measured requirements | Later hosting | T30 | [#31](https://github.com/diegoami/voice-teacher/issues/31) |
| [T32](T32.md) | Deploy the accepted service to the chosen always-on host | Later hosting | T31 | [#32](https://github.com/diegoami/voice-teacher/issues/32) |

## Preflight decisions

Use the existing private `language-learning-data` repository under an isolated
namespace, or a dedicated private progress repository; make the destination
configurable. Confirm the Android web-client assumption before T15 and whether
screen-locked/headset use requires a separate native-client task. Confirm the
free-conversation correction default before T20. These choices do not block
schema, engine or review-tooling work.

This backlog assumes one personal learner and one active writer server.
Accounts for other learners, billing, app-store packaging and automatic lesson
authoring require separately scoped tasks if requested. T31 does not silently
expand the release into a multi-user service.
