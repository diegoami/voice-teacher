# Private files and review evidence

Everything needed for a normal development/test run is committed, including
synthetic fixtures. Downloadable private files have one durable home:
[voice-teacher on Drive](https://drive.google.com/drive/folders/1vco_myHt1RjR7U0OhdSMMZYiy4upVpfj).
The folder was created in My Drive with owner-only permissions (verified
2026-10-23); no link sharing was enabled. Keep private subfolders owner-only.

| Material | Durable home | Local working copy |
| --- | --- | --- |
| Code, setup, synthetic test fixtures, contracts | Git | This checkout |
| Review reports, synthetic check logs/builds intended for a release | GitHub release assets | `artifacts/public/` |
| Required private inputs, approved samples, original audio/history, private operator files | Private Drive folder | `.cache/private/` or `artifacts/private/` |
| Credentials and OAuth tokens | Environment secret settings | Process environment only |
| Canonical progress | Existing private progress repository | Configured private server runtime |

Use the Google Drive connector/UI, or rclone through `python3 tools/artifacts.py`:

```bash
python3 tools/artifacts.py where
python3 tools/artifacts.py pull poc2-fixtures-2026-10-23.tar.gz
python3 tools/artifacts.py push artifacts/private/unique-private-report.txt
python3 tools/artifacts.py release EXISTING_TAG artifacts/public/release-review.md
```

Drive access uses the environment secrets in [cloud setup](cloud.md); rclone is
optional and must be installed for these transfers. The helper scopes the
remote to the project folder, uses immutable copy (never sync/delete), refuses
path traversal and stores downloaded files privately. The folder setting is
NOT an OAuth permission boundary: grant credentials only to trusted sessions.
Use the connector if no rclone credentials are provisioned. Required downloads
listed in artifacts.json have SHA-256 pins; verify before extracting or using.
Extract archives only into ignored private storage, then copy an explicitly
needed POC input to its documented ignored location. No bulk automatic restore.

Optional old POC samples are kept for reproducibility, not required for the
product test suite. Import manifests/approvals and raw source records remain
private; existing private source/progress Git repositories stay canonical.
Do not upload an entire home directory, credential store, live SQLite/WAL pair
or unsanitized model runtime. T29 still owns a consistent live-runtime backup
and verified restore drill; an artifact copy is not that backup feature.

No required file may be left solely in /tmp, a sibling checkout or a Windows
path. Preserve originals until transfer and metadata/checksum verification
succeed. Existing worktrees are retained, but their code is already pushed to
GitHub; do not rely on them for cloud setup. Raw private review runtimes may
hold credentials and are not suitable release assets.

Before uploading release assets, inspect contents for private data and secrets.
Only files deliberately staged in `artifacts/public/` are eligible for the
release helper. It uses REST, requires an existing release and refuses duplicate
asset names; it never tags, publishes or overwrites an existing asset. The
release review specifies exact candidate SHA and links checks and findings.

The POC2 archive was uploaded on 2026-10-23 (128 generated MP3 samples), with
a SHA-256 verified by a complete download from Drive. Its JSON manifest sits
beside it. A separate runtime snapshot was prepared locally using SQLite's
backup API and passed integrity checks. Upload of that learner/session payload
requires specific owner approval and has not been completed; it is not listed
as a downloadable artifact. No runtime restore or cross-database atomicity is
claimed by this migration.
