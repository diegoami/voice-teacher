# Local source registry

T08 adds `voice_teacher.content.registry.SourceRegistry`. Register operator-owned
local checkouts, with an explicit allowed content subdirectory. Sources and
courses have separate stable namespaces: lesson `4B` in source A is independent
of lesson `4B` in source B. The registry never clones, pulls, checks out or writes
to a content repository.

```python
from voice_teacher.storage import Store
from voice_teacher.content.registry import SourceRegistry, SourceSpec

store = Store("/private/server-data")
registry = SourceRegistry(store)
registry.register(SourceSpec(
    "uk-course", "Ukrainian", "/local/lesson-checkout",
    subdirectory="content", manifest="voice-teacher.json",
))
snapshot = registry.refresh("uk-course")
catalogue = snapshot.curriculum
reference = snapshot.source_ref("basics", "4B")
```

The default `canonical_json` adapter reads a bounded version-1 curriculum JSON
manifest. The `legacy` adapter takes the reviewed mapping described in
[legacy-adapter.md](legacy-adapter.md), through `SourceSpec(mapping=...,
adapter="legacy")`. Configuration and compiled private inputs live only in the
private runtime database. Keep that database outside every registered checkout;
a managed source-cache directory below the data directory is supported when it
does not contain the database itself. These are trusted server APIs; pairing and
operator authorization are supplied by T09.

Refresh compiles and validates outside the database transaction, then atomically
records the version and switches the active pointer. Failure retains the last
valid version across restarts and records an error. A concurrent source
configuration or HEAD change rejects activation. Reusing an already known
source/course/item/revision with a different definition requires an explicit
item revision bump. A rollback to a previously known definition is allowed.
Returned catalogues and prepared plans are independent copies.

The snapshot records the checkout commit, exact input SHA-256 hashes, mapping
hash and dirty status. Its version ID hashes the complete compiled payload,
including private inputs. Session source references use the version-1 canonical
curriculum hash and commit/dirty fields. The coordinator stores the actual
prepared lesson/profile inside the private session snapshot, so refreshes and
source selection cannot change an existing session's targets or evidence refs.
Resumption needs no access to the original checkout.

Only consumed files determine dirty status; unrelated untracked files do not
make lesson content dirty. Raw bytes are compared with Git blobs at HEAD using
fixed plumbing commands. Hooks, filters, fsmonitor, aliases and repository
scripts are never invoked. CRLF normalization can conservatively mark content
dirty even when ordinary Git status would consider it clean. Dirty/untracked,
unborn and non-Git sources require `allow_dirty=True`; they are hashed and labelled
dirty, with the base commit or `None`, never claimed to equal committed bytes.
The externally reviewed legacy mapping is bound by its separate mapping hash;
it is configuration, not a claim that the checkout contains that mapping.
Relative paths cannot escape the configured root; input/subdirectory symlinks
are refused. Configure the actual Git checkout root and use `subdirectory` for
nested content. Source trees must not be actively modified while refreshing;
this is a read-only importer, not a filesystem isolation boundary against a
hostile concurrent local process.

`list_sources()` exposes names, active version IDs and refresh errors, without
configuration paths. `active(source_id)` returns the last validated cached
version. Public consumers receive only `snapshot.curriculum`, not the private
snapshot payload. `prepared_lesson(...)` removes historical private introduction
and settings by default. `private_session_inputs(...)` is an explicit trusted
operator API for later learner-associated import; source selection alone must
never assign somebody else's historical context to the current learner.

The current extracted engine needs opening, guided steps and recall together.
A canonical lesson with all three authored phases can produce a prepared plan;
other valid catalogues can be activated but require the independent mode planners
in T13/T14 before starting. The registry never invents missing targets or phases.
This task does not implement progress aggregation or fix the accepted-variant
engine attribution tracked in [#44](https://github.com/diegoami/voice-teacher/issues/44).

Verification uses synthetic, network-disabled fixtures:

```bash
uv run pytest tests/content/test_registry.py -q
uv run pytest tests/content tests/integration tests/storage tests/engine tests/contracts -q
```

Coverage includes colliding lesson IDs, evidence namespaces, valid/invalid updates,
resumption after checkout changes, explicit dirty policies, unsafe paths, hostile
Git hook/filter configuration, item revision conflicts, private-context handling,
concurrent configuration/HEAD changes and transactional v3-to-v4 migration failure.
