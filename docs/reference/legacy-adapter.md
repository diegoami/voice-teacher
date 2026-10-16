# Read-only legacy lesson adapter

`LegacyAdapter(mapping).load(root, source_id=...)` reads existing learnukrainian
`package.md` session briefs plus explicitly reviewed POC5 lesson JSON. It returns
an `AdaptedCatalogue` with three separate outputs:

- `curriculum`: validated version-1 reusable catalogue, with curated public titles,
  explicit source/course/lesson/item IDs, speech/display renderings, guided goals,
  recall prompts and supported modes.
- `session_inputs[(course_id, lesson_id)]`: private prepared T04 lesson and legacy
  learner/context fields. `prepared_lesson(course, lesson)` returns a fresh runtime
  Lesson. This output includes the authored introduction and private context; it
  must not be returned as a public catalogue or committed to the code repository.
- `input_hashes`: SHA-256 of the exact package and prepared bytes that were read.

The adapter copies no personal-profile fields into the catalogue. The legacy
learner description, weak-expression selection, scenario and main goal are private
session context. Unrelated preparation metadata/usage is ignored. Curated public
lesson titles are explicit rather than copied from a possibly personal title.
Known full learner-description text embedded in a reusable field causes refusal.
This is field separation plus an exact-description guard, not a general detector
of every personal name or sensitive phrase. Review reusable authored material
before publishing it anywhere. Selecting an old package does not authorize applying
its learner context to another learner; the server must explicitly choose private
session inputs for the correct profile.

## Explicit preparation and identity mapping

The adapter never calls a model or runs package scripts. A package without targets
is not session-ready. Preparation is an operator action before activation:

1. Build the POC5 lesson JSON explicitly from the chosen package (the retained
   `python -m engine lesson <folder>` preparation command), then review its target
   sentences, stress and private context. This is not run by the product adapter.
2. Place the reviewed JSON in the configured source material, or create a separate
   reviewed source snapshot containing package + preparation. The adapter needs
   only read access; it never writes to either source. No source relocation or
   private-data copy is performed automatically.
3. Supply a mapping with exact raw-file hashes and stable IDs. The prepared JSON
   must match the deterministic package fields, steps and recall prompts; an
   outdated preparation is refused even when its file hash is updated.
4. Review a changed rendering deliberately: preserve its ID for a spelling change,
   increment `item_revision`, update the speech hash and the input hashes. A change
   of meaning needs a new ID or an explicit reviewed migration. Never infer identity
   by text or silently merge two source items.

Mapping version 1 has these exact fields:

```json
{
  "format_version": 1,
  "source_id": "synthetic-source",
  "title": "Reusable catalogue title",
  "courses": [
    {
      "course_id": "basics",
      "title": "Basics",
      "language": "uk",
      "instruction_language": "en",
      "items": [
        {
          "item_id": "hello",
          "item_revision": 1,
          "meaning": "Greet someone",
          "speech_sha256": "SHA-256 of the exact UTF-8 target rendering"
        }
      ],
      "lessons": [
        {
          "lesson_id": "4B",
          "title": "Greetings",
          "legacy_part": "4B",
          "package": "voice-sessions/example-4B",
          "prepared": "prepared/4B.json",
          "package_sha256": "SHA-256 of package.md bytes",
          "prepared_sha256": "SHA-256 of prepared JSON bytes",
          "opening_item_ids": ["hello"],
          "steps": [{"number": 1, "step_id": "greet", "target_item_ids": ["hello"]}],
          "recall": [{"number": 1, "goal_id": "recall-hello", "target_item_ids": ["hello"]}],
          "topic": null
        }
      ]
    }
  ]
}
```

Hash descriptions in this example are placeholders: real hashes must be lowercase
64-character hex strings. IDs and revisions are curated metadata, not positional
hashes. Numbered mapping slots align with the source/prepared rows, while `step_id`
and `goal_id` remain explicit if lesson positions change. Each rendering occurrence
has an explicit item ID. Reusing an ID requires the exact same rendering; identical
text under distinct IDs stays distinct. Courses keep independent scopes even when
each has a lesson named 4B. Unknown source IDs and missing/unused item mappings fail.

The legacy adapter supports the measured uk/en format. It exposes repetition and
guided capabilities from the package; a separately curated non-null `topic` adds
free-conversation availability without leaking the private scenario. This is a
content capability, not an implemented free-conversation engine. The public
repetition set includes mapped opening and guided-target items; the private
combined routine preserves original opening order and per-step target sets.

Paths must remain within the configured source root, including after symlink
resolution. Reads are bounded (default 4 MiB per file), UTF-8 and read-only. Raw
input hashes bind explicit preparation; the canonical curriculum hash used by T03
is a separate value. T08 owns Git revision/dirty-state activation, while the full
private runtime lesson/profile are pinned by the coordinator capsule for resume.
The adapter does not activate sources, generate targets, choose a learner, export
private data or infer progress.

```bash
uv run pytest tests/content/test_legacy_adapter.py -q
```

Fixtures are synthetic. Tests cover expected outputs and stress, malformed counts,
missing/stale targets, explicit identities, multiple course scopes, private-field
separation, read-only source hashes, no script execution and no network access.
