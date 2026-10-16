from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from schemas.validate import canonical_json, validate_curriculum
from voice_teacher.content.adapters import LegacyAdapter, LegacyError
from voice_teacher.practice import Session

TICKET = "Оди́н квито́к, будь ла́ска."
PRICE = "Скі́льки це ко́штує?"
ALTERNATIVE = "Яка́ ціна́?"
PACKAGE = f"""# Synthetic preparation

SESSION_BRIEF
Lesson part: 4B — SYNTHETIC_PRIVATE_TITLE
Learner: SYNTHETIC_PRIVATE_LEARNER
Main goal: revisit transport

Teacher introduction:
Приві́т, SYNTHETIC_PRIVATE_LEARNER.

Opening review (2 lines):
1. {TICKET}
2. {PRICE}

Active phrase set:
- {TICKET}
- {PRICE}

Guided sequence:
SYNTHETIC_PRIVATE_SCENARIO
1. New cycle: Say «До́брий день!» Wait for the learner to ask for one ticket.
2. Say «Ось, будь ла́ска.» Wait for the learner to ask the price.

Delayed recall:
- Запита́йте ціну́.

Earlier weak expressions included:
- SYNTHETIC_PRIVATE_WEAK_HINT

Source:
Synthetic only.
"""


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def write_prepared(root, value, mapping):
    (root / "prepared/4B.json").write_text(json.dumps(value, ensure_ascii=False))
    mapping["courses"][0]["lessons"][0]["prepared_sha256"] = digest((root / "prepared/4B.json").read_bytes())


def refresh_package_hash(root, mapping):
    mapping["courses"][0]["lessons"][0]["package_sha256"] = digest((root / "voice-sessions/example-4B/package.md").read_bytes())


def fixture(tmp_path):
    root = tmp_path / "source"
    (root / "voice-sessions/example-4B").mkdir(parents=True)
    (root / "prepared").mkdir()
    (root / "voice-sessions/example-4B/package.md").write_text(PACKAGE)
    prepared = {"lesson": {"source": "example-4B", "part": "4B", "title": "SYNTHETIC_PRIVATE_TITLE",
        "learner": "SYNTHETIC_PRIVATE_LEARNER", "main_goal": "revisit transport",
        "introduction": "Приві́т, SYNTHETIC_PRIVATE_LEARNER.", "opening": [TICKET, PRICE],
        "active_phrases": [TICKET, PRICE], "weak_expressions": ["SYNTHETIC_PRIVATE_WEAK_HINT"],
        "scenario": "SYNTHETIC_PRIVATE_SCENARIO",
        "steps": [dict(number=1, teacher_line="До́брий день!", expected="ask for one ticket", setting="New cycle", targets=[TICKET], phrase="SYNTHETIC_PRIVATE_WEAK_HINT", open_answer=False),
                  dict(number=2, teacher_line="Ось, будь ла́ска.", expected="ask the price", setting="", targets=[PRICE, ALTERNATIVE], phrase="", open_answer=False)],
        "recall": [dict(number=1, prompt="Запита́йте ціну́.", targets=[PRICE], phrase="")],
        "closing": "Заня́ття закі́нчено.", "unrelated_private_field": "SYNTHETIC_PRIVATE_EXTRA"},
        "usage": {"ignored": "SYNTHETIC_PRIVATE_USAGE"}}
    mapping = {"format_version": 1, "source_id": "synthetic-source", "title": "Synthetic catalogue", "courses": [{
        "course_id": "basics", "title": "Basics", "language": "uk", "instruction_language": "en",
        "items": [dict(item_id=identity, item_revision=1, meaning=meaning, speech_sha256=digest(text)) for identity, text, meaning in
                  [("ticket", TICKET, "One ticket"), ("price", PRICE, "Ask the price"), ("price-alternative", ALTERNATIVE, "Alternative price question")]],
        "lessons": [{"lesson_id": "4B", "legacy_part": "4B", "title": "Transport", "package": "voice-sessions/example-4B",
                     "prepared": "prepared/4B.json", "package_sha256": "", "prepared_sha256": "",
                     "opening_item_ids": ["ticket", "price"],
                     "steps": [dict(number=1, step_id="request-ticket", target_item_ids=["ticket"]),
                               dict(number=2, step_id="ask-price", target_item_ids=["price", "price-alternative"])],
                     "recall": [dict(number=1, goal_id="recall-price", target_item_ids=["price"])], "topic": None}]}]}
    refresh_package_hash(root, mapping)
    write_prepared(root, prepared, mapping)
    return root, mapping, prepared


def load(root, mapping):
    return LegacyAdapter(mapping).load(root, source_id=mapping["source_id"])


def test_expected_catalogue_and_private_runtime_inputs_preserve_stress(tmp_path):
    root, mapping, _ = fixture(tmp_path)
    result = load(root, mapping)
    validate_curriculum(result.curriculum)
    course = result.curriculum["courses"][0]
    lesson = result.prepared_lesson("basics", "4B")
    assert lesson.opening == [TICKET, PRICE]
    assert lesson.steps[1].targets == [PRICE, ALTERNATIVE]
    assert [s.expected for s in lesson.steps] == ["ask for one ticket", "ask the price"]
    assert lesson.recall[0].prompt == "Запита́йте ціну́."
    assert lesson.steps[0].setting == "New cycle"
    assert course["items"][0]["text"] == {"speech": TICKET, "display": "Один квиток, будь ласка."}
    assert course["lessons"][0]["modes"] == ["repetition", "guided_conversation"]
    assert course["lessons"][0]["repetition_item_ids"] == ["ticket", "price", "price-alternative"]
    assert "SYNTHETIC_PRIVATE" not in canonical_json(result.curriculum)
    assert "SYNTHETIC_PRIVATE_LEARNER" in lesson.introduction
    assert result.session_inputs[("basics", "4B")]["legacy_context"]["learner"] == "SYNTHETIC_PRIVATE_LEARNER"
    assert "SYNTHETIC_PRIVATE_EXTRA" not in str(result.session_inputs)
    assert "SYNTHETIC_PRIVATE_USAGE" not in str(result.session_inputs)
    Session(lesson, lambda *args: None).start()  # runtime package, no POC import/path hacks


def test_explicit_topic_enables_free_mode_without_private_scenario_leak(tmp_path):
    root, mapping, _ = fixture(tmp_path)
    mapping["courses"][0]["lessons"][0]["topic"] = "Public transport"
    lesson = load(root, mapping).curriculum["courses"][0]["lessons"][0]
    assert lesson["modes"] == ["repetition", "guided_conversation", "free_conversation"]
    assert lesson["topic"] == "Public transport"


@pytest.mark.parametrize("change", ["count", "numbering", "missing-marker", "missing-teacher", "missing-action"])
def test_malformed_packages_fail_before_a_session_starts(tmp_path, change):
    root, mapping, _ = fixture(tmp_path)
    replacements = {"count": ("(2 lines)", "(3 lines)"), "numbering": ("2. " + PRICE, "3. " + PRICE),
                    "missing-marker": ("SESSION_BRIEF", "NOT_A_BRIEF"), "missing-teacher": ("Say «До́брий день!»", "Continue normally"),
                    "missing-action": ("Wait for the learner to ask for one ticket", "Pause briefly")}
    old, new = replacements[change]
    (root / "voice-sessions/example-4B/package.md").write_text(PACKAGE.replace(old, new))
    refresh_package_hash(root, mapping)
    with pytest.raises(LegacyError): load(root, mapping)


@pytest.mark.parametrize("change", ["empty-targets", "missing-targets", "row-count", "wrong-number", "boolean-number", "stale-teacher", "missing-open-answer"])
def test_preparation_must_be_complete_and_match_the_package(tmp_path, change):
    root, mapping, prepared = fixture(tmp_path)
    lesson = prepared["lesson"]
    if change == "empty-targets": lesson["steps"][0]["targets"] = []
    if change == "missing-targets": del lesson["recall"][0]["targets"]
    if change == "row-count": lesson["steps"].pop()
    if change == "wrong-number": lesson["steps"][0]["number"] = 2
    if change == "boolean-number": lesson["steps"][0]["number"] = True
    if change == "stale-teacher": lesson["steps"][0]["teacher_line"] = "Changed"
    if change == "missing-open-answer": del lesson["steps"][0]["open_answer"]
    write_prepared(root, prepared, mapping)
    with pytest.raises(LegacyError): load(root, mapping)


def test_missing_preparation_and_changed_inputs_require_explicit_review(tmp_path):
    root, mapping, _ = fixture(tmp_path)
    (root / "prepared/4B.json").unlink()
    with pytest.raises(LegacyError, match="missing source"): load(root, mapping)
    (root / "prepared/4B.json").write_text("{}")
    with pytest.raises(LegacyError, match="explicitly prepare/review"): load(root, mapping)


@pytest.mark.parametrize("change", ["unknown-item", "count", "item-hash", "unknown-version"])
def test_identity_mapping_is_explicit_and_complete(tmp_path, change):
    root, mapping, _ = fixture(tmp_path)
    course = mapping["courses"][0]
    if change == "unknown-item": course["lessons"][0]["opening_item_ids"][0] = "unknown"
    if change == "count": course["lessons"][0]["steps"][0]["target_item_ids"].append("price")
    if change == "item-hash": course["items"][0]["speech_sha256"] = "0" * 64
    if change == "unknown-version": mapping["format_version"] = 2
    with pytest.raises(LegacyError): load(root, mapping)


def test_unknown_source_and_lesson_mappings_are_actionable(tmp_path):
    root, mapping, _ = fixture(tmp_path)
    with pytest.raises(LegacyError, match="unknown source mapping"):
        LegacyAdapter(mapping).load(root, source_id="unregistered")
    with pytest.raises(LegacyError, match="unknown course/lesson"):
        load(root, mapping).prepared_lesson("other", "4B")


def test_identical_renderings_keep_separate_explicit_item_identities(tmp_path):
    root, mapping, prepared = fixture(tmp_path)
    prepared["lesson"]["steps"][1]["targets"][1] = PRICE
    mapping["courses"][0]["items"][2]["speech_sha256"] = digest(PRICE)
    write_prepared(root, prepared, mapping)
    items = load(root, mapping).curriculum["courses"][0]["items"]
    assert len(items) == 3 and items[1]["text"] == items[2]["text"]
    assert items[1]["item_id"] != items[2]["item_id"]


def test_multiple_courses_keep_their_own_4b_and_item_scope(tmp_path):
    root, mapping, _ = fixture(tmp_path)
    other = deepcopy(mapping["courses"][0]); other["course_id"] = "second-track"
    mapping["courses"].append(other)
    result = load(root, mapping)
    assert len(result.curriculum["courses"]) == 2
    assert result.prepared_lesson("basics", "4B").course_id == "basics"
    assert result.prepared_lesson("second-track", "4B").course_id == "second-track"


def test_read_only_compilation_never_executes_scripts_or_changes_source_hashes(tmp_path):
    root, mapping, _ = fixture(tmp_path)
    marker = tmp_path / "should-not-exist"
    script = root / "setup.py"
    script.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')")
    files = [p for p in root.rglob("*") if p.is_file()]
    before = {p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in files}
    dirs = sorted([root, *(p for p in root.rglob("*") if p.is_dir())], key=lambda p: len(p.parts))
    try:
        for p in files: p.chmod(0o444)
        for p in reversed(dirs): p.chmod(0o555)
        result = load(root, mapping)
        assert result.input_hashes == {key: before[key] for key in result.input_hashes}
        assert {p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in files} == before
        assert not marker.exists()
    finally:
        for p in dirs: p.chmod(0o755)
        for p in files: p.chmod(0o644)


def test_returned_values_cannot_mutate_the_mapping_or_later_loads(tmp_path):
    root, mapping, _ = fixture(tmp_path)
    adapter = LegacyAdapter(mapping)
    one = adapter.load(root, source_id="synthetic-source")
    one.curriculum["courses"][0]["lessons"][0]["guided_steps"][0]["target_item_ids"].clear()
    one.prepared_lesson("basics", "4B").opening.clear()
    two = adapter.load(root, source_id="synthetic-source")
    assert two.curriculum["courses"][0]["lessons"][0]["guided_steps"][0]["target_item_ids"] == ["ticket"]
    assert two.prepared_lesson("basics", "4B").opening == [TICKET, PRICE]


def test_source_escape_and_oversize_input_are_refused(tmp_path):
    root, mapping, _ = fixture(tmp_path)
    mapping["courses"][0]["lessons"][0]["prepared"] = "../outside.json"
    with pytest.raises(LegacyError, match="relative path"): load(root, mapping)
    root, mapping, _ = fixture(tmp_path / "other")
    with pytest.raises(LegacyError, match="byte limit"):
        LegacyAdapter(mapping, max_bytes=16).load(root, source_id="synthetic-source")


def test_known_private_learner_description_cannot_leak_through_public_goals(tmp_path):
    root, mapping, prepared = fixture(tmp_path)
    path = root / "voice-sessions/example-4B/package.md"
    path.write_text(PACKAGE.replace("ask for one ticket", "greet SYNTHETIC_PRIVATE_LEARNER"))
    prepared["lesson"]["steps"][0]["expected"] = "greet SYNTHETIC_PRIVATE_LEARNER"
    refresh_package_hash(root, mapping)
    write_prepared(root, prepared, mapping)
    with pytest.raises(LegacyError, match="privacy"):
        load(root, mapping)


def test_valid_changed_preparation_requires_explicit_hash_review(tmp_path):
    root, mapping, prepared = fixture(tmp_path)
    prepared["usage"]["ignored"] = "different synthetic preparation metadata"
    (root / "prepared/4B.json").write_text(json.dumps(prepared, ensure_ascii=False))
    with pytest.raises(LegacyError, match="explicitly prepare/review"):
        load(root, mapping)


def test_package_at_registered_root_and_crlf_input_are_supported(tmp_path):
    root, mapping, _ = fixture(tmp_path)
    package_root = root / "voice-sessions/example-4B"
    (package_root / "prepared.json").write_bytes((root / "prepared/4B.json").read_bytes())
    package = package_root / "package.md"
    package.write_bytes(PACKAGE.replace("\n", "\r\n").encode())
    lesson = mapping["courses"][0]["lessons"][0]
    lesson.update(package=".", prepared="prepared.json", package_sha256=digest(package.read_bytes()))
    result = load(package_root, mapping)
    assert result.prepared_lesson("basics", "4B").opening == [TICKET, PRICE]


def test_reviewed_open_answer_policy_survives_compilation_into_guided_plan(tmp_path):
    from voice_teacher.content.registry import SourceSnapshot
    from voice_teacher.practice.guided import GuidedSession, plan_guided
    root, mapping, prepared = fixture(tmp_path)
    prepared["lesson"]["steps"][1]["open_answer"] = True
    write_prepared(root, prepared, mapping)
    result = load(root, mapping)
    assert result.curriculum["courses"][0]["lessons"][0]["guided_steps"][1]["open_answer"] is True
    source = SourceSnapshot("legacy", canonical_json({"curriculum": result.curriculum, "provenance": {"commit": None, "dirty": True}}))
    plan = plan_guided(source, "basics", "4B")
    from voice_teacher.providers import Judgement, Verdict
    from voice_teacher.practice.profiles import UKRAINIAN
    engine = GuidedSession(plan, lambda *a: Judgement(Verdict("accept", True, "", "", 0, ""), 0, {}))
    engine.start(); engine.hear(TICKET)
    assert engine.current._item().open_answer is True
    assert UKRAINIAN.open_answer_card in engine.card
