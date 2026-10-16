"""Validate offline interchange documents and their cross-record invariants."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).parent / "v1"
SCHEMAS = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in ROOT.glob("*.json")}
REGISTRY = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in SCHEMAS.values())


class ContractError(ValueError):
    """A document cannot be accepted as this version of the contract."""


def canonical_json(value: Any) -> str:
    """UTF-8 text for hashing; preserves Unicode and rejects non-JSON values."""
    try:
        result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if json.loads(result) != value:
            raise ValueError("Python value changes during JSON serialization")
        return result
    except (TypeError, ValueError) as error:
        raise ContractError(f"$: not a JSON value: {error}") from error


def content_hash(curriculum: dict) -> str:
    return hashlib.sha256(canonical_json(curriculum).encode("utf-8")).hexdigest()


def _fail(path: str, message: str) -> None:
    raise ContractError(f"{path}: {message}")


def _shape(kind: str, value: Any) -> None:
    canonical_json(value)
    validator = Draft202012Validator(SCHEMAS[kind], registry=REGISTRY, format_checker=FormatChecker())
    error = next(validator.iter_errors(value), None)
    if error:
        # Nullable/ref alternatives can otherwise dump a private snapshot into
        # the diagnostic. Select a useful leaf location and avoid payload values.
        def leaves(problem):
            if not problem.context:
                return [problem]
            return [leaf for child in problem.context for leaf in leaves(child)]
        error = max(leaves(error), key=lambda problem: len(problem.absolute_path))
        location = "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path)
        detail = error.message if error.validator in ["required", "additionalProperties"] else f"invalid {error.validator}: expected {error.validator_value!r}"
        _fail(location, detail)


def _unique(rows: list[dict], key: str, path: str) -> dict:
    found = {}
    for index, row in enumerate(rows):
        identity = row[key]
        if identity in found:
            _fail(f"{path}[{index}].{key}", f"duplicate ID {identity!r}")
        found[identity] = row
    return found


def item_key(source_id: str, course_id: str, item_id: str) -> tuple[str, str, str]:
    """Stable identity; spelling and repository paths are not part of the key."""
    return source_id, course_id, item_id


def validate_curriculum(value: dict) -> None:
    _shape("curriculum", value)
    _unique(value["courses"], "course_id", "$.courses")
    for c, course in enumerate(value["courses"]):
        path = f"$.courses[{c}]"
        items = _unique(course["items"], "item_id", path + ".items")
        _unique(course["lessons"], "lesson_id", path + ".lessons")
        for n, lesson in enumerate(course["lessons"]):
            lp = f"{path}.lessons[{n}]"
            _unique(lesson["guided_steps"], "step_id", lp + ".guided_steps")
            _unique(lesson["recall_goals"], "goal_id", lp + ".recall_goals")
            references = [(lp + ".repetition_item_ids", lesson["repetition_item_ids"])]
            for field in ["guided_steps", "recall_goals"]:
                references.extend((f"{lp}.{field}[{i}].target_item_ids", row["target_item_ids"])
                                  for i, row in enumerate(lesson[field]))
            for at, ids in references:
                for i, identity in enumerate(ids):
                    if identity not in items:
                        _fail(f"{at}[{i}]", f"unknown course item {identity!r}")
            for mode, field in [("repetition", "repetition_item_ids"), ("guided_conversation", "guided_steps"),
                                ("free_conversation", "topic")]:
                if mode in lesson["modes"] and not lesson[field]:
                    _fail(lp + "." + field, f"required for {mode}")


def validate_catalogue(sources: list[dict]) -> None:
    for source in sources:
        validate_curriculum(source)
    _unique(sources, "source_id", "$.sources")


def _source_mode(source: dict | None, mode: str, path: str) -> None:
    if source is None and mode != "free_conversation":
        _fail(path, "only free conversation may omit a curriculum source")


def validate_session(value: dict) -> None:
    _shape("session", value)
    source = value["source"]
    _source_mode(source, value["mode"], "$.source")
    if source is None:
        if value["curriculum_snapshot"] is not None or not value["topic"]:
            _fail("$.curriculum_snapshot", "source-free conversation requires null curriculum and an explicit topic")
        return
    curriculum = value["curriculum_snapshot"]
    if curriculum is None:
        _fail("$.curriculum_snapshot", "required for a pinned source")
    validate_curriculum(curriculum)
    if source["source_id"] != curriculum["source_id"]:
        _fail("$.source.source_id", "does not match compiled snapshot")
    course = next((c for c in curriculum["courses"] if c["course_id"] == source["course_id"]), None)
    lesson = next((l for l in course["lessons"] if l["lesson_id"] == source["lesson_id"]), None) if course else None
    if lesson is None:
        _fail("$.source", "unknown course or lesson in snapshot")
    if value["mode"] not in lesson["modes"]:
        _fail("$.mode", "not supported by pinned lesson")
    for field in ["language", "instruction_language"]:
        if value[field] != course[field]:
            _fail("$." + field, "does not match pinned course")
    if content_hash(curriculum) != source["revision"]["content_sha256"]:
        _fail("$.source.revision.content_sha256", "does not match compiled snapshot")


def validate_progress(value: dict) -> None:
    _shape("progress", value)
    _source_mode(value["source"], value["mode"], "$.source")
    provenance = value["provenance"]
    if provenance["practice_source"] != value["source"]:
        _fail("$.provenance.practice_source", "must match this event's pinned source")
    original, item = provenance["original_source"], provenance["original_item"]
    if item is not None and (original is None or any(item[k] != original[k] for k in ["source_id", "course_id"])):
        _fail("$.provenance.original_item", "must identify an item in its original source/course")
    event_type = value["event_type"]
    if event_type != "state.saved" and value["turn"] is None:
        _fail("$.turn", "turn reference required")
    if event_type != "state.saved" and value["turn"]["text"] is None:
        _fail("$.turn.text", "accepted turn text required")
    if event_type in ["turn.accepted", "evidence.recorded"]:
        if value["turn"]["role"] != "learner" or value["assistance"] is None:
            _fail("$.assistance", "learner attempt requires assistance evidence and learner turn")
    if event_type.startswith("teacher.") and value["turn"]["role"] != "teacher":
        _fail("$.turn.role", "teacher event requires teacher turn")
    if event_type == "evidence.recorded":
        evidence = value["evidence"]
        if evidence is None:
            _fail("$.evidence", "required for evidence.recorded")
        if evidence["outcome"] == "independent" and (value["assistance"]["target_exposed"] or
                value["assistance"]["kind"] in ["cue", "model", "correction"]):
            _fail("$.evidence.outcome", "an exposed/cued/modelled answer cannot be independent")
    elif value["evidence"] is not None:
        _fail("$.evidence", "only evidence.recorded may carry evidence")
    if event_type == "state.saved":
        snapshot = value["snapshot"]
        if snapshot is None:
            _fail("$.snapshot", "required for state.saved")
        validate_session(snapshot)
        for field in ["learner_id", "session_id", "mode", "source"]:
            if value[field] != snapshot[field]:
                _fail("$.snapshot." + field, "does not match event envelope")
        if snapshot["event_sequence"] != value["sequence"]:
            _fail("$.snapshot.event_sequence", "must equal this state event's sequence")
    elif value["snapshot"] is not None:
        _fail("$.snapshot", "only state.saved may carry a session snapshot")
    if (event_type == "observation.superseded") != (value["supersedes_event_id"] is not None):
        _fail("$.supersedes_event_id", "required only for observation.superseded")
    if value["supersedes_event_id"] == value["event_id"]:
        _fail("$.supersedes_event_id", "event cannot supersede itself")


def validate_event_stream(events: list[dict], *, partial: bool = False) -> None:
    """Full streams start at one; an explicit partial batch may start later."""
    event_ids, sequences, identities, turns, revisions = set(), {}, {}, {}, {}
    for index, event in enumerate(events):
        validate_progress(event)
        key = (event["learner_id"], event["session_id"])
        if event["event_id"] in event_ids:
            _fail(f"$[{index}].event_id", "duplicate event ID; deduplicate before validating a stream")
        event_ids.add(event["event_id"])
        expected = sequences.get(key, event["sequence"] - 1 if partial else 0) + 1
        if event["sequence"] != expected:
            _fail(f"$[{index}].sequence", f"expected {expected} for this session")
        sequences[key] = event["sequence"]
        identity = (event["mode"], event["source"])
        if key in identities and identities[key] != identity:
            _fail(f"$[{index}].source", "a session cannot change mode or pinned source")
        identities[key] = identity
        if event["event_type"] == "state.saved":
            revision = event["snapshot"]["revision"]
            if revision <= revisions.get(key, -1):
                _fail(f"$[{index}].snapshot.revision", "saved state revisions must increase")
            revisions[key] = revision
        turn = event["turn"]
        if turn is not None:
            tk = (*key, turn["turn_id"])
            if tk in turns and turns[tk]["turn"] != turn:
                _fail(f"$[{index}].turn", "same turn ID has different contents")
            if event["event_type"] in ["turn.accepted", "teacher.reply_planned"]:
                if tk in turns:
                    _fail(f"$[{index}].turn", "duplicate accepted/planned turn ID")
                turns[tk] = {"turn": turn, "assistance": event["assistance"]}
            elif event["event_type"] != "state.saved" and not partial and tk not in turns:
                _fail(f"$[{index}].turn", "must reference an earlier accepted/planned turn")
            if event["event_type"] == "evidence.recorded" and tk in turns and event["assistance"] != turns[tk]["assistance"]:
                _fail(f"$[{index}].assistance", "must preserve the accepted attempt's assistance")
