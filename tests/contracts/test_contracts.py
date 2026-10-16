from copy import deepcopy
import json
import socket
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from schemas.validate import (
    SCHEMAS, ContractError, canonical_json, content_hash, item_key,
    validate_catalogue, validate_curriculum, validate_event_stream,
    validate_progress, validate_session,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / (name + ".json")).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["repetition", "guided", "topic"])
def test_all_supported_content_shapes(name):
    validate_curriculum(load(name))


def test_schemas_are_valid_and_references_resolve_without_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("contract validation attempted a network connection")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    for schema in SCHEMAS.values():
        Draft202012Validator.check_schema(schema)
    validate_session(load("session"))
    validate_event_stream(load("progress"))


@pytest.mark.parametrize("name,validate", [
    ("guided", validate_curriculum), ("session", validate_session), ("progress", validate_progress),
])
def test_unknown_schema_versions_fail(name, validate):
    value = load(name)
    if name == "progress":
        value = value[1]
    value["schema_version"] = 999
    with pytest.raises(ContractError, match=r"\$\.schema_version"):
        validate(value)


@pytest.mark.parametrize("collection,key", [
    ("courses", "course_id"), ("items", "item_id"), ("lessons", "lesson_id"),
    ("guided_steps", "step_id"), ("recall_goals", "goal_id"),
])
def test_duplicate_ids_have_locations(collection, key):
    value = load("guided")
    rows = value["courses"] if collection == "courses" else value["courses"][0].get(collection)
    if rows is None:
        rows = value["courses"][0]["lessons"][0][collection]
    rows.append(deepcopy(rows[0]))
    with pytest.raises(ContractError, match="duplicate ID") as error:
        validate_curriculum(value)
    assert key in str(error.value) and "[1]" in str(error.value)


@pytest.mark.parametrize("field", ["repetition_item_ids", "guided_steps", "recall_goals"])
def test_unknown_item_references_fail_before_a_session(field):
    value = load("guided")
    lesson = value["courses"][0]["lessons"][0]
    if field == "repetition_item_ids":
        lesson[field] = ["missing"]
    else:
        lesson[field][0]["target_item_ids"] = ["missing"]
    with pytest.raises(ContractError, match=field + r".*unknown course item"):
        validate_curriculum(value)


@pytest.mark.parametrize("name,field", [
    ("repetition", "repetition_item_ids"), ("guided", "guided_steps"), ("topic", "topic"),
])
def test_mode_capabilities_require_actual_material(name, field):
    value = load(name)
    value["courses"][0]["lessons"][0][field] = None if field == "topic" else []
    with pytest.raises(ContractError, match="required for"):
        validate_curriculum(value)


@pytest.mark.parametrize("level", ["root", "course", "lesson", "item", "step"])
@pytest.mark.parametrize("private_field", ["learner_profile", "progress"])
def test_reusable_content_rejects_private_payloads_at_every_object(level, private_field):
    value = load("guided")
    course = value["courses"][0]
    objects = {"root": value, "course": course, "lesson": course["lessons"][0],
               "item": course["items"][0], "step": course["lessons"][0]["guided_steps"][0]}
    objects[level][private_field] = {"synthetic": True}
    with pytest.raises(ContractError, match=private_field):
        validate_curriculum(value)


def test_namespace_identity_and_duplicate_registered_sources():
    a, b = load("repetition"), load("repetition")
    b["source_id"] = "synthetic-beta"
    validate_catalogue([a, b])
    assert item_key(a["source_id"], "basics", "hello") != item_key(b["source_id"], "basics", "hello")
    with pytest.raises(ContractError, match="source_id.*duplicate"):
        validate_catalogue([a, deepcopy(a)])
    other_course = deepcopy(a["courses"][0])
    other_course["course_id"] = "another-course"
    a["courses"].append(other_course)
    validate_curriculum(a)  # Identical local IDs in independent courses are valid.


def test_unicode_and_private_snapshot_round_trip_are_lossless():
    value = load("session")
    validate_session(value)
    restored = json.loads(canonical_json(value))
    assert restored == value
    assert restored["curriculum_snapshot"]["courses"][0]["items"][0]["text"]["speech"] == "Приві́т"
    assert restored["learner_profile"] == {"level": "beginner"}
    assert restored["engine_state"]["data"]["pending_reply"] == "Try again"
    reordered = dict(reversed(list(value["curriculum_snapshot"].items())))
    assert content_hash(reordered) == value["source"]["revision"]["content_sha256"]


@pytest.mark.parametrize("mutation,location", [
    (lambda s: s["source"].update(source_id="other-source"), "source_id"),
    (lambda s: s["source"].update(lesson_id="missing"), "unknown course or lesson"),
    (lambda s: s.update(mode="repetition"), "not supported"),
    (lambda s: s.update(language="de"), "language"),
    (lambda s: s["source"]["revision"].update(content_sha256="d" * 64), "content_sha256"),
    (lambda s: s.update(curriculum_snapshot=None), "curriculum_snapshot"),
    (lambda s: s["engine_state"].update(format_version=999), "format_version"),
])
def test_snapshot_pins_are_checked(mutation, location):
    value = load("session")
    mutation(value)
    with pytest.raises(ContractError, match=location):
        validate_session(value)


def test_dirty_snapshot_is_explicit_and_cannot_claim_a_clean_missing_commit():
    value = load("session")
    value["source"]["revision"]["commit"] = None
    with pytest.raises(ContractError):
        validate_session(value)
    value["source"]["revision"]["dirty"] = True
    validate_session(value)


def test_free_conversation_can_be_source_free_with_explicit_topic_and_languages():
    value = load("session")
    value.update(source=None, curriculum_snapshot=None, mode="free_conversation", topic="Fictional picnic")
    value["engine_state"]["data"] = {"messages": []}
    validate_session(value)
    value["mode"] = "guided_conversation"
    with pytest.raises(ContractError, match="only free conversation"):
        validate_session(value)


def test_progress_round_trip_preserves_original_and_later_sources_and_help():
    events = load("progress")
    validate_event_stream(events)
    restored = json.loads(canonical_json(events))
    assert restored == events
    event = restored[-1]
    assert event["source"]["source_id"] == "synthetic-alpha"
    assert event["provenance"]["original_source"]["source_id"] == "synthetic-origin"
    assert event["provenance"]["original_source"]["revision"]["commit"] == "b" * 40
    assert event["turn"]["turn_id"] == "learner-turn-1"
    assert event["mode"] == "guided_conversation"
    assert event["assistance"]["kind"] == "cue"
    assert event["evidence"]["outcome"] == "cued"


@pytest.mark.parametrize("path", [
    ("turn",), ("source", "revision"), ("assistance",),
    ("provenance", "origin_turn_id"), ("provenance", "original_item", "item_id"),
])
def test_missing_progress_references_fail(path):
    value = load("progress")[-1]
    parent = value
    for key in path[:-1]:
        parent = parent[key]
    del parent[path[-1]]
    with pytest.raises(ContractError):
        validate_progress(value)


@pytest.mark.parametrize("mutation,location", [
    (lambda e: e.update(turn=None), "turn"),
    (lambda e: e["turn"].update(role="teacher"), "learner turn"),
    (lambda e: e["provenance"]["practice_source"].update(source_id="elsewhere"), "practice_source"),
    (lambda e: e["provenance"]["original_item"].update(source_id="elsewhere"), "original_item"),
    (lambda e: e["evidence"].update(outcome="mastered"), "outcome"),
    (lambda e: e.update(occurred_at="2026-10-16T12:00:00"), "date-time"),
    (lambda e: e["evidence"].update(outcome="independent"), "cannot be independent"),
])
def test_malformed_progress_is_rejected(mutation, location):
    value = load("progress")[-1]
    mutation(value)
    with pytest.raises(ContractError, match=location):
        validate_progress(value)


def test_stream_order_deduplication_and_turn_identity():
    events = load("progress")
    with pytest.raises(ContractError, match="duplicate event"):
        validate_event_stream(events + [deepcopy(events[-1])])
    events[-1]["sequence"] += 1
    with pytest.raises(ContractError, match="expected 3"):
        validate_event_stream(events)
    events = load("progress")
    events[-1]["turn"]["turn_id"] = "unknown-turn"
    with pytest.raises(ContractError, match="earlier accepted/planned"):
        validate_event_stream(events)
    events = load("progress")
    events[-1]["turn"]["text"] = "Different wording"
    with pytest.raises(ContractError, match="different contents"):
        validate_event_stream(events)


def test_partial_batches_require_explicit_mode_and_later_archive_reconciliation():
    events = load("progress")[2:]
    with pytest.raises(ContractError, match="expected 1"):
        validate_event_stream(events)
    validate_event_stream(events, partial=True)


def test_state_event_requires_matching_snapshot_sequence():
    value = load("progress")[0]
    value["snapshot"]["event_sequence"] = 99
    with pytest.raises(ContractError, match="event_sequence"):
        validate_progress(value)


def test_stream_rejects_duplicate_attempts_and_regressing_saved_state():
    events = load("progress")
    duplicate = deepcopy(events[1])
    duplicate.update(event_id="different-event", sequence=4)
    with pytest.raises(ContractError, match="duplicate accepted"):
        validate_event_stream(events + [duplicate])
    snapshot = deepcopy(events[0])
    snapshot.update(event_id="state-2", sequence=4)
    snapshot["snapshot"]["event_sequence"] = 4
    with pytest.raises(ContractError, match="revisions must increase"):
        validate_event_stream(events + [snapshot])


def test_stream_cannot_switch_source_or_mode():
    events = load("progress")
    # Each document is valid on its own; the shared session identity is not.
    events[-1]["source"]["revision"]["commit"] = "f" * 40
    events[-1]["provenance"]["practice_source"] = deepcopy(events[-1]["source"])
    with pytest.raises(ContractError, match="cannot change mode or pinned source"):
        validate_event_stream(events)


def test_snapshot_turn_reference_cannot_forge_an_accepted_attempt():
    events = load("progress")
    events[0]["turn"] = deepcopy(events[-1]["turn"])
    events = [events[0], events[-1]]
    events[-1]["sequence"] = 2
    with pytest.raises(ContractError, match="earlier accepted/planned"):
        validate_event_stream(events)


@pytest.mark.parametrize("invalid", [float("nan"), b"audio bytes", {1: "nonstring key"}])
def test_private_capsules_are_json_not_arbitrary_python(invalid):
    value = load("session")
    value["engine_state"]["data"]["invalid"] = invalid
    with pytest.raises(ContractError, match="not a JSON value"):
        validate_session(value)


def test_nullable_schema_errors_do_not_dump_private_payloads():
    value = load("session")
    value["curriculum_snapshot"]["learner_profile"] = {"private": "synthetic-secret-not-for-diagnostics"}
    with pytest.raises(ContractError) as error:
        validate_session(value)
    assert "synthetic-secret-not-for-diagnostics" not in str(error.value)
    assert "curriculum_snapshot" in str(error.value)


def test_planned_teacher_delivery_requires_consistent_existing_turn():
    events = load("progress")
    planned = deepcopy(events[1])
    planned.update(event_id="teacher-plan", sequence=4, event_type="teacher.reply_planned", assistance=None)
    planned["turn"] = {"turn_id": "teacher-turn-1", "index": 1, "role": "teacher", "text": "Hello again"}
    delivered = deepcopy(planned)
    delivered.update(event_id="teacher-delivery", sequence=5, event_type="teacher.reply_delivered")
    validate_event_stream(events + [planned, delivered])
    delivered["sequence"] = 4
    with pytest.raises(ContractError, match="earlier accepted/planned"):
        validate_event_stream(events + [delivered])


def test_source_free_observation_preserves_private_origin_without_inventing_curriculum():
    turn, observation = load("progress")[1:]
    for sequence, event in enumerate([turn, observation], 1):
        event.update(sequence=sequence, source=None, mode="free_conversation")
        event["provenance"].update(original_source=None, original_item=None, practice_source=None)
        event["assistance"].update(kind="none", help_level=0)
    observation["evidence"]["outcome"] = "observed"
    validate_event_stream([turn, observation])


def test_evidence_cannot_erase_assistance_recorded_at_acceptance():
    events = load("progress")
    events[-1]["assistance"].update(kind="none", help_level=0)
    events[-1]["evidence"]["outcome"] = "independent"
    with pytest.raises(ContractError, match="preserve the accepted attempt"):
        validate_event_stream(events)
