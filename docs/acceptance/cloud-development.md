# Claude cloud development verification

## Owner-relayed report, 2026-10-23

The owner supplied the following results from an actual Claude cloud session.
This is owner-relayed acceptance evidence, not an independently repeated cloud
run by the local Codex session. The tested commit SHA and Claude session URL
were not supplied with the report; requested separately. Do not infer the tested
SHA from the current PR head.

| Check | Reported result |
| --- | --- |
| `bash tools/cloud_setup.sh` | Exit 0, Ready message |
| `source .cache/cloud.env` | Exit 0 |
| GitHub REST repository lookup | Returned `diegoami/voice-teacher` |
| `rclone version` | v1.75.2 |
| POC2 artifact download through `tools/artifacts.py` | Exit 0; downloaded SHA-256 rechecked against artifacts.json and matched |
| Web production build | Passed, 1.5 seconds |
| `tools/cloud/check_setup.py` | Passed |
| Cloud tooling unittest suite | 9 tests passed |
| Web unit suite | 5 tests in 2 files passed |
| Catalogue browser smoke, 2 workers | 16 passed, 13.2 seconds |

The reporter also confirmed a clean Git tree, no commits/merges, no runtime
restore, no paid provider calls, and no printed credentials, environment
variables or private contents. The download used the synthetic/generated POC
archive, not the private learner runtime snapshot.

## Scope and remaining checks

This verifies cloud development setup, GitHub REST access, authenticated Drive
download/checksum, production build, unit checks and desktop/Android-emulated
catalogue smoke. The reported cloud checks did not include the full backend or
full browser suites; their separate local/CI results remain separate evidence.

The cloud setup script was invoked explicitly. Automatic SessionStart/resume
hook execution was tested locally, but an actual cloud hook trace was not
included in this report. Do not mark that separately observed based solely on
the manual script result.

Rclone reported use of its shared Google OAuth client. Downloads work in this
report; migration to an owner-controlled Desktop OAuth client remains an
operational follow-up (see [rclone setup](../rclone.md)).

This is not real-phone, human microphone/conversation, backup restore or release
acceptance. T19/T28/T29/T30 retain their respective gates. Earlier live provider
and owner listening checks remain recorded separately under T22.

The initial cloud-start failure (exit 127, repository-relative setup file not
found) remains recorded in [T38](../tasks/T38.md). The corrected procedure keeps
the early environment setup empty/`true`, with repository setup after checkout.
