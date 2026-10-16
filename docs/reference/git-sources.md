# Managed Git lesson sources

T23 adds explicit operator-managed lesson repositories. Learners select the same
safe source IDs and catalogues as local sources; they never supply clone URLs,
credentials, checkout paths or commands. Content and private progress remain
separate. Source operations only fetch: they do not push or edit remote refs.

## Enable the manager

The optional manager requires Linux, Git and util-linux `prlimit` in
`/usr/bin` or `/bin`. Leave it unconfigured to keep Git source endpoints disabled
(503) while ordinary local sources continue to work. Startup reads policy but
never contacts remotes. Refresh is an explicit operator operation.

Create an absolute, private JSON file outside Git checkouts, registered content
and the managed cache. Its file mode must be 0600 (or stricter), with no symlink
components. For example, a server-owned configuration directory may contain:

```json
{
  "schema_version": 1,
  "allowed_remotes": ["https://github.com/example/lessons.git"],
  "allowed_local_roots": [],
  "timeout": 30,
  "max_file_bytes": 67108864,
  "max_cache_bytes": 268435456,
  "max_entries": 50000
}
```

Pass its absolute path with `uv run python -m voice_teacher --git-source-policy PATH` or
`VOICE_TEACHER_GIT_SOURCE_POLICY`. The existing data-directory, origin, provider
and operator-token settings still apply. Do not put credentials in URLs, CLI
arguments or this repository.

Remote URLs must exactly match one of one to 32 policy entries. Only HTTPS
without userinfo, query or fragment, or absolute local remotes, is supported.
Redirects, SSH, Git protocol, file URLs, relative paths and external transports
are refused. Local remotes additionally require an explicit absolute
`allowed_local_roots` entry, cannot use symlink components and cannot overlap
application code or runtime storage. An allowed HTTPS host is an operator trust
decision; this is not an arbitrary public clone service.

For a private HTTPS repository, policy may specify `credential_askpass` as the
absolute path of an operator-owned executable. It must be outside Git checkouts,
registered/allowed local content and the managed source cache; symlinks, shell
metacharacters in its path and group/world-writable files are refused. The helper
is trusted server code: it should obtain credentials from private server
configuration, recognize Git's username/password prompts and avoid logging them.
No credential helper is inherited from the user's global Git configuration.
Without this explicit helper, Git prompts fail immediately. This task's offline
checks use synthetic local remotes, not a live private HTTPS credential.

## Register and refresh

Authenticate using the existing operator bearer token, supplied privately by
your administrative client. Send `PUT /api/v1/operator/git-sources/ukrainian`:

```json
{
  "name": "Ukrainian lessons",
  "remote": "https://github.com/example/lessons.git",
  "ref_kind": "branch",
  "ref_name": "main",
  "subdirectory": "lessons",
  "adapter": "canonical_json",
  "manifest": "voice-teacher.json"
}
```

`ref_kind` also accepts `tag`; refs must be valid branch/tag names, never command
options. Paths are repository-relative, cannot escape via `..` or select `.git`,
and must pass the registry's containment and symlink checks. Defaults are branch
`main`, subdirectory `.`, canonical JSON and `voice-teacher.json`. The `legacy`
adapter accepts the existing reviewed `mapping` format from the
[legacy adapter](legacy-adapter.md); it cannot run preparation scripts.

Send `POST /api/v1/operator/git-sources/ukrainian/refresh` to fetch again using
saved settings. Registration and refresh return only source ID, display name,
validated version and availability. Unknown fields, including client-supplied
credentials/helper/checkout settings, are rejected. Learner credentials cannot
use either route. Errors contain no Git stderr, internal paths or remote URL.

## Validation, recovery and limits

Checkouts and descriptors live privately under `DATA_DIR/lesson-sources/`.
A nonblocking manager lock serializes administrative changes. Each configuration
has its own managed checkout; reconfiguration retains earlier caches. Never use
these checkouts as editable workspaces. Local changes, including ignored files,
unexpected configuration changes and symlinks cause refusal without overwriting
that data. The manager never force-checks-out, resets, cleans or automatically
removes cached repositories.

Fetch selects one branch/tag with shallow history, disables submodule recursion,
Git hooks, fsmonitor, inherited configuration and redirects, and uses a fixed
argument vector without a shell. Repository scripts and attributes are content;
no repository-provided filter command is configured. Each Git subprocess has a
timeout and hard per-file size limit, captures bounded output privately, and
terminates its process group. Cache bytes and entry counts are checked around
operations. The aggregate cache limit is a checkpoint limit, not a filesystem
quota: an operation may exceed it before the next check. Use an OS disk quota
for a hard aggregate ceiling. Defaults are 30 seconds per command, 64 MiB per
file, 256 MiB aggregate cache and 50,000 entries. Very large catalogues can be
refused even if valid; raising limits requires an operator policy change.

Only a completely validated catalogue updates the active source version.
Unavailable remotes, invalid manifests, unsupported schemas, unsafe paths,
changed item text without a new item revision and budget failures retain the
previous compiled catalogue. Running sessions keep their original immutable
content and provenance, even after successful updates. A failed first
registration has no validated catalogue yet. Failed registration retains its
requested managed configuration so an operator can retry or replace it.

After a failure, inspect server-side configuration and managed files privately.
Correct remote material or policy and retry. An invalid fetched checkout may
remain on disk while its last validated snapshot stays active in SQLite. If
unexpected local data or an exceeded budget prevents retry, retain it for
inspection and choose an explicit maintenance/reconfiguration action; the API
will not delete it. No private progress destination is selected or written by
source registration. See [source registry](source-registry.md) for snapshot
identity and [progress sync](progress-sync.md) for the separate archive writer.
