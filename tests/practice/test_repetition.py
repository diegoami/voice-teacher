from copy import deepcopy
from dataclasses import replace
import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from schemas.validate import canonical_json, validate_curriculum
from voice_teacher.api import create_app
from voice_teacher.content.registry import SourceSnapshot, SourceRegistry, SourceSpec
from voice_teacher.practice.coordinator import Coordinator
from voice_teacher.practice.profiles import UKRAINIAN
from voice_teacher.practice.repetition import RepetitionSession, plan_lesson, plan_queue, weak_queue
from voice_teacher.providers import Judgement, Verdict, Recognition
from voice_teacher.providers.pipeline import VoicePipeline
from voice_teacher.providers.speech import SpeechConfig, SpeechError
from voice_teacher.progress.archive import Archive
from voice_teacher.storage import Store
from voice_teacher.storage.work import RequestConflict

LEARNER = "synthetic-learner"
TICKET = "Оди́н квито́к, будь ла́ска."
PRICE = "Скі́льки це ко́штує?"


class Judge:
    def __init__(self, verdict="accept"): self.verdict = verdict; self.calls = []
    def __call__(self, item, text):
        self.calls.append((deepcopy(item), text))
        return Judgement(Verdict(self.verdict, self.verdict == "accept", "", "", 0, ""), 0, {})


def source(name="alpha", *, language="uk"):
    value = json.loads((Path(__file__).parents[1] / "contracts/fixtures/guided.json").read_text())
    value["source_id"] = name
    c = value["courses"][0]; c["language"] = language
    c["items"] = [dict(item_id=identity, item_revision=1, text=dict(display=text.replace("\u0301", ""), speech=text), meaning=meaning)
        for identity, text, meaning in [("ticket", TICKET, "Ask for one ticket"), ("price", PRICE, "Ask the price")]]
    l = c["lessons"][0]; l.update(modes=["repetition"], repetition_item_ids=["ticket", "price"], guided_steps=[], recall_goals=[])
    validate_curriculum(value)
    return SourceSnapshot(name, canonical_json({"curriculum": value, "provenance": {"commit": None, "dirty": True}}))


def template(s, sid="session", learner=LEARNER):
    c = s.curriculum["courses"][0]
    return dict(schema_version=1, kind="session_snapshot", learner_id=learner, session_id=sid,
        revision=0, event_sequence=0, mode="repetition", status="created", source=s.source_ref("basics", "lesson-1"),
        curriculum_snapshot=s.curriculum, topic=None, language=c["language"], instruction_language=c["instruction_language"],
        learner_profile={"level": "A2"}, engine_state={"format_version": 1, "data": {}})


def setup(tmp_path, *, ids=None, recall=False, judge=None, delivery=None):
    store = Store(tmp_path / "data"); store.save_learner(LEARNER, {"level": "A2"})
    s = source(); plan = plan_lesson(s, "basics", "lesson-1", item_ids=ids, recall_before_model=recall)
    judge = judge or Judge(); c = Coordinator(store, judge, delivery=delivery)
    presentation = c.create_repetition(template(s), plan)
    return store, c, judge, s, plan, presentation


def turn(c, store, text=TICKET, *, sid="session", request=None):
    revision = store.session(LEARNER, sid)["revision"]
    return c.submit(LEARNER, sid, request or "turn-" + str(revision), expected_revision=revision, text=text)


def outcomes(store, sid="session"):
    return [e for e in store.events(LEARNER, sid) if e["event_type"] == "evidence.recorded"]


def test_phrase_only_selected_set_retries_and_replays_without_guided_dependencies(tmp_path):
    store, c, judge, s, plan, first = setup(tmp_path, ids=["price"])
    assert s.lesson("basics", "lesson-1")["guided_steps"] == []
    assert first["teacher"][-1]["text"] == PRICE and TICKET not in canonical_json(first)
    assert "\u0301" not in first["teacher"][-1]["display"]
    result = turn(c, store, PRICE, request="one")
    before = store.events(LEARNER, "session")
    assert c.submit(LEARNER, "session", "one", expected_revision=0, text=PRICE) == result
    assert c.presentation(LEARNER, "session")["done"]
    assert store.events(LEARNER, "session") == before
    assert judge.calls == [] and result["done"]
    assert outcomes(store)[0]["evidence"]["outcome"] == "repeated"


def test_pause_process_restart_resume_replays_identical_selected_next_item_and_stop(tmp_path):
    store, c, _, _, _, _ = setup(tmp_path)
    next_item = turn(c, store)
    assert next_item["teacher"][0]["text"] == PRICE
    c.control(LEARNER, "session", "pause", expected_revision=1, operation="pause")
    script = """import json,sys
from voice_teacher.storage import Store
from voice_teacher.practice.coordinator import Coordinator
c=Coordinator(Store(sys.argv[1]),lambda *args: (_ for _ in ()).throw(RuntimeError('must not judge')))
print(json.dumps(c.control('synthetic-learner','session','resume',expected_revision=2,operation='resume')))
"""
    resumed = json.loads(subprocess.check_output([sys.executable, "-c", script, str(store.path.parent)], text=True))
    c = Coordinator(Store(store.path.parent), Judge())
    assert resumed["teacher"] == next_item["teacher"]
    assert len(outcomes(store)) == 1
    stopped = c.control(LEARNER, "session", "stop", expected_revision=3, operation="stop")
    assert stopped["done"] and len(outcomes(store)) == 1
    with pytest.raises(RequestConflict): c.control(LEARNER, "session", "bad", expected_revision=4, operation="resume")


def test_saved_judgement_delivery_failure_recovers_without_extra_recall_or_evidence(tmp_path):
    def fail(_): raise RuntimeError("synthetic delivery failure")
    store, c, judge, _, _, first = setup(tmp_path, ids=["ticket"], recall=True, delivery=fail)
    assert TICKET not in canonical_json(first)
    with pytest.raises(RuntimeError): turn(c, store, request="one")
    before = store.events(LEARNER, "session")
    c = Coordinator(Store(store.path.parent), Judge(), delivery=lambda _: {"recovered": True})
    result = c.submit(LEARNER, "session", "one", expected_revision=0, text=TICKET)
    assert result["done"] and result["delivery"] == {"recovered": True}
    assert len(judge.calls) == 1 and c.judge.calls == []
    assert store.events(LEARNER, "session") == before


def test_only_accepted_unexposed_recall_is_independent(tmp_path):
    store, c, judge, _, _, first = setup(tmp_path, ids=["ticket"], recall=True)
    assert first["card"] == "Your turn: Ask for one ticket" and TICKET not in canonical_json(first)
    turn(c, store)
    e = outcomes(store)[0]
    assert e["evidence"]["outcome"] == "independent" and not e["assistance"]["target_exposed"]
    assert judge.calls[0][0].targets == [TICKET]


@pytest.mark.parametrize("verdict", ["error", "unclear", "question", "social", "later_step"])
def test_failed_recall_supplies_model_and_later_match_is_repeated(tmp_path, verdict):
    store, c, judge, _, _, _ = setup(tmp_path, ids=["ticket"], recall=True, judge=Judge(verdict))
    model = turn(c, store, "synthetic failed answer")
    assert model["teacher"][0]["text"] == TICKET and outcomes(store) == []
    turn(c, store)
    e = outcomes(store)[0]
    assert e["evidence"]["outcome"] == "repeated" and e["assistance"]["target_exposed"]
    assert len(judge.calls) == 1


def test_two_unmatched_repetitions_need_another_turn_and_feed_private_queue(tmp_path):
    store, c, judge, _, _, _ = setup(tmp_path, ids=["ticket"])
    bad = "banana orange pear apple plum"
    assert turn(c, store, bad)["teacher"][0]["text"] == TICKET
    assert outcomes(store) == []
    assert turn(c, store, bad)["done"]
    event = outcomes(store)[0]
    assert event["evidence"]["outcome"] == "needs_turn" and weak_queue(store, LEARNER) == [event["event_id"]]
    assert judge.calls == []


def test_cross_source_queue_retains_original_and_practice_and_roundtrips_without_reset(tmp_path):
    store, c, _, a, _, _ = setup(tmp_path, ids=["ticket"])
    for _ in range(2): turn(c, store, "banana orange pear apple plum")
    original = outcomes(store)[0]; before = store.events(LEARNER, "session"); position = store.projection(LEARNER, "session")["activities"]
    b = source("beta"); ids = weak_queue(store, LEARNER)
    plan = plan_queue(store, LEARNER, b, "basics", "lesson-1", ids)
    c.create_repetition(template(b, "review"), plan)
    turn(c, store, sid="review")
    event = outcomes(store, "review")[0]
    assert event["provenance"]["original_source"] == a.source_ref("basics", "lesson-1")
    assert event["provenance"]["practice_source"] == b.source_ref("basics", "lesson-1")
    assert event["provenance"]["origin_session_id"] == "session"
    assert event["provenance"]["origin_turn_id"] == original["turn"]["turn_id"]
    assert weak_queue(store, LEARNER) == ids  # repeated alone never retires the weak target
    assert store.events(LEARNER, "session") == before and store.projection(LEARNER, "session")["activities"] == position
    root = tmp_path / "archive"; root.mkdir(); archive = Archive(root); archive.export(store)
    restored = Store(tmp_path / "restored"); archive.restore(restored)
    assert restored.events(LEARNER, "review") == store.events(LEARNER, "review")
    assert Coordinator(restored, Judge()).presentation(LEARNER, "review")["done"]
    recall = plan_queue(restored, LEARNER, b, "basics", "lesson-1", ids, recall_before_model=True)
    rc = Coordinator(restored, Judge()); rc.create_repetition(template(b, "recall"), recall)
    turn(rc, restored, sid="recall")
    assert weak_queue(restored, LEARNER) == []


def test_queue_ownership_disputed_attempts_and_tampered_targets_are_refused(tmp_path):
    store, c, _, s, plan, _ = setup(tmp_path, ids=["ticket"])
    for _ in range(2): turn(c, store, "banana orange pear apple plum")
    ids = weak_queue(store, LEARNER)
    store.save_learner("another", {})
    with pytest.raises(ValueError): plan_queue(store, "another", s, "basics", "lesson-1", ids)
    altered = deepcopy(plan); altered.targets[0]["speech"] = "tampered target"
    with pytest.raises(ValueError): c.create_repetition(template(s, "tampered"), altered)
    with pytest.raises(KeyError): store.session(LEARNER, "tampered")
    c.report_recognition(LEARNER, "session", "turn-1", status="recognized", text="suspected recognition problem")
    assert weak_queue(store, LEARNER) == []
    with pytest.raises(ValueError): plan_queue(store, LEARNER, s, "basics", "lesson-1", ids)


def test_speech_failure_report_keeps_repetition_capsule_and_original_phase(tmp_path):
    store, c, _, _, _, _ = setup(tmp_path, ids=["ticket"])
    class Speech:
        config = SpeechConfig()
        def transcribe(self, *args, **kwargs): return Recognition("")
        def synthesize(self, text, **kwargs): return b"synthetic speech"
    p = VoicePipeline(store, c, Speech(), Speech())
    before = store.events(LEARNER, "session")
    with pytest.raises(SpeechError): p.submit(LEARNER, "session", "empty", expected_revision=0, data=b"synthetic recording", media_type="audio/webm")
    assert store.events(LEARNER, "session") == before
    assert p.report_problem(LEARNER, "session", "empty")
    assert store.session(LEARNER, "session")["engine_state"]["data"]["coordinator_version"] == 3
    turn(Coordinator(Store(store.path.parent), Judge()), store)
    assert outcomes(store)[0]["evidence"]["outcome"] == "repeated"
    assert "empty" in store.session(LEARNER, "session")["engine_state"]["data"]["recognition_reports"]


def test_custom_language_profile_and_source_capabilities(tmp_path):
    s = source(language="pl"); plan = plan_lesson(s, "basics", "lesson-1", item_ids=["price"])
    custom = replace(UKRAINIAN, language="pl", stop_words=("koniec",), closing="Koniec.")
    store = Store(tmp_path / "data"); store.save_learner(LEARNER, {})
    c = Coordinator(store, Judge(), profiles={("pl", "en"): custom})
    c.create_repetition(template(s), plan)
    assert turn(c, store, "koniec")["teacher"][0]["text"] == "Koniec."
    with pytest.raises(ValueError): RepetitionSession(plan, Judge())
    with pytest.raises(ValueError): plan_lesson(s, "basics", "lesson-1", item_ids=["unrelated"])
    with pytest.raises(ValueError): plan_lesson(s, "basics", "lesson-1", item_ids=["price", "price"])
    raw = s.curriculum; raw["courses"][0]["lessons"][0]["modes"] = ["free_conversation"]
    other = SourceSnapshot("other", canonical_json({"curriculum": raw, "provenance": s.provenance}))
    with pytest.raises(ValueError): plan_lesson(other, "basics", "lesson-1")


@pytest.mark.parametrize("field,value", [("index", 10), ("retries", True), ("plan_hash", "wrong"), ("phase", "guided"), ("phase", "recall")])
def test_repetition_snapshot_refuses_invalid_position_or_changed_inputs(field, value):
    plan = plan_lesson(source(), "basics", "lesson-1")
    engine = RepetitionSession(plan, Judge()); engine.start(); saved = engine.snapshot()
    saved["data"][field] = value
    with pytest.raises(ValueError): RepetitionSession.from_snapshot(plan, Judge(), saved)


def test_api_lists_and_starts_phrase_only_mode_and_keeps_queue_private(tmp_path):
    store = Store(tmp_path / "data"); store.save_learner(LEARNER, {})
    root = tmp_path / "content"; root.mkdir(); s = source()
    (root / "voice-teacher.json").write_text(canonical_json(s.curriculum))
    reg = SourceRegistry(store); reg.register(SourceSpec("alpha", "Alpha", str(root), allow_dirty=True)); reg.refresh("alpha")
    c = Coordinator(store, Judge()); app = create_app(store, c, operator_token="x" * 40, origin="http://teacher.test")
    client = TestClient(app, base_url="http://teacher.test")
    code = app.state.auth.issue_code(LEARNER, "synthetic")["code"]
    token = client.post("/api/v1/pair", json={"code": code}).json()["token"]; headers = {"Authorization": "Bearer " + token}
    listed = client.get("/api/v1/sources/alpha/courses/basics/lessons", headers=headers).json()
    assert listed[0]["available_modes"] == ["repetition"] and "targets" not in canonical_json(listed)
    body = dict(session_id="api", source_id="alpha", course_id="basics", lesson_id="lesson-1", mode="repetition", item_ids=["price"])
    response = client.post("/api/v1/sessions", json=body, headers=headers)
    assert response.status_code == 201 and response.json()["teacher"][-1]["text"] == PRICE.replace("\u0301", "")
    assert client.get("/api/v1/review-items", headers=headers).json() == []
    assert client.get("/api/v1/review-items").status_code == 401
    assert client.post("/api/v1/sessions", json={**body, "session_id": "bad", "queue_event_ids": ["fake"]}, headers=headers).status_code == 422
    pinned = store.session(LEARNER, "api")
    raw = s.curriculum
    raw["courses"][0]["items"][1].update(item_revision=2, meaning=PRICE)
    (root / "voice-teacher.json").write_text(canonical_json(raw)); reg.refresh("alpha")
    assert client.post("/api/v1/sessions", json={**body, "session_id": "leaked", "recall_before_model": True}, headers=headers).status_code == 409
    with pytest.raises(KeyError): store.session(LEARNER, "leaked")
    assert store.session(LEARNER, "api") == pinned


@pytest.mark.parametrize("phrase", ["Досить, дякую.", "Стоп."])
def test_authored_stop_words_can_be_repeated_as_lesson_material(phrase):
    original = source(); raw = original.curriculum
    raw["courses"][0]["items"][0]["text"] = {"display": phrase, "speech": phrase}
    s = SourceSnapshot("stop-word", canonical_json({"curriculum": raw, "provenance": original.provenance}))
    engine = RepetitionSession(plan_lesson(s, "basics", "lesson-1", item_ids=["ticket"]), Judge())
    engine.start(); engine.hear(phrase)
    assert engine.done and [e.label for e in engine.evidence] == ["repeated"]


def test_recall_refuses_a_prompt_that_already_contains_the_authored_answer():
    plan = plan_lesson(source(), "basics", "lesson-1", item_ids=["ticket"], recall_before_model=True)
    plan.targets[0]["meaning"] = "Say " + TICKET
    with pytest.raises(ValueError, match="recall prompt includes"): RepetitionSession(plan, Judge())
