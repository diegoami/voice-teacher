"""Synthetic guided scenarios: no provider calls or personal curriculum."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from schemas.validate import canonical_json, validate_curriculum
from voice_teacher.api import create_app
from voice_teacher.content.registry import SourceSnapshot, SourceRegistry, SourceSpec
from voice_teacher.practice.coordinator import Coordinator
from voice_teacher.practice.guided import GuidedSession, GuidedPlan, plan_guided
from voice_teacher.practice.profiles import UKRAINIAN
from voice_teacher.practice.repetition import weak_queue
from voice_teacher.providers import Verdict, Judgement
from voice_teacher.progress.archive import Archive
from voice_teacher.storage import Store, StorageError
from voice_teacher.storage.work import RequestConflict

LEARNER = "synthetic-learner"
TICKET = "Оди́н квито́к, будь ла́ска."
PRICE = "Скі́льки це ко́штує?"
ALTERNATIVE = "Яка́ ціна́?"
THANKS = "Дя́кую."


class Judge:
    def __init__(self, *verdicts): self.queue = list(verdicts); self.calls = []
    def __call__(self, item, text):
        self.calls.append((deepcopy(item), text))
        v = self.queue.pop(0) if self.queue else ("accept",)
        kind, chunk, step = v[0], v[1] if len(v) > 1 else "", v[2] if len(v) > 2 else 0
        return Judgement(Verdict(kind, kind in {"accept", "error", "later_step"}, chunk, "Explain the task.", step, ""), 0, {})


def source(*, combined=True, count=3, recall=True, identical=False, language="uk"):
    value = json.loads((Path(__file__).parents[1] / "contracts/fixtures/guided.json").read_text())
    value["source_id"] = "alpha"
    c = value["courses"][0]; c["language"] = language
    c["items"] = [dict(item_id=i, item_revision=1, text=dict(display=t.replace("\u0301", ""), speech=t), meaning=m)
        for i, t, m in [("ticket", TICKET, "Ask for one ticket"), ("price", PRICE, "Ask the price"),
                        ("alternative", PRICE if identical else ALTERNATIVE, "Ask the price differently"), ("thanks", THANKS, "Thank the seller")]]
    l = c["lessons"][0]
    l.update(modes=["guided_conversation", "repetition"] if combined else ["guided_conversation"],
        repetition_item_ids=["ticket"] if combined else [],
        guided_steps=[dict(step_id=i, teacher=dict(display=t, speech=t), goal=g, target_item_ids=ids)
          for i, t, g, ids in [("request", "Добрий день!", "Ask for one ticket", ["ticket"]),
              ("price-goal", "Ось квиток.", "Ask the price", ["price", "alternative"]),
              ("thank", "Двадцять гривень.", "Thank the seller", ["thanks"])][:count]],
        recall_goals=[dict(goal_id="recall-price", prompt=dict(display="Ask its price again", speech="Ask its price again"),
            target_item_ids=["price", "alternative"])] if recall and count > 1 else [])
    validate_curriculum(value)
    return SourceSnapshot("synthetic", canonical_json({"curriculum": value, "provenance": {"commit": None, "dirty": True}}))


def template(s, sid="session"):
    c = s.curriculum["courses"][0]
    return dict(schema_version=1, kind="session_snapshot", learner_id=LEARNER, session_id=sid, revision=0,
        event_sequence=0, mode="guided_conversation", status="created", source=s.source_ref("basics", "lesson-1"),
        curriculum_snapshot=s.curriculum, topic=None, language=c["language"], instruction_language=c["instruction_language"],
        learner_profile={"level": "A2"}, engine_state={"format_version": 1, "data": {}})


def setup(tmp_path, *, s=None, judge=None, **options):
    s = s or source(); plan = plan_guided(s, "basics", "lesson-1", **options)
    store = Store(tmp_path / "data"); store.save_learner(LEARNER, {"level": "A2"})
    judge = judge or Judge(); c = Coordinator(store, judge)
    first = c.create_guided(template(s), plan)
    return store, c, judge, s, plan, first


def turn(c, store, text, request=None):
    rev = store.session(LEARNER, "session")["revision"]
    return c.submit(LEARNER, "session", request or f"turn-{rev}", expected_revision=rev, text=text)


def control(c, store, operation):
    rev = store.session(LEARNER, "session")["revision"]
    return c.control(LEARNER, "session", f"{operation}-{rev}", expected_revision=rev, operation=operation)


def outcomes(store): return [e for e in store.events(LEARNER, "session") if e["event_type"] == "evidence.recorded"]


def advance(c, store):
    snap = store.session(LEARNER, "session")
    engine = c._engine(snap, c.judge)
    if engine.boundary: return control(c, store, "resume")
    if engine.phase == "opening": text = engine.current.lesson.opening[engine.current.index]
    elif engine.phase == "guided" and engine.round == 0: text = engine.current.model_items[engine.current.index][0]
    else: text = engine.current._item().targets[0]
    return turn(c, store, text)


@pytest.mark.parametrize("routine", ["guided", "combined"])
def test_short_planned_activities_cover_both_sittings_and_recall_once(tmp_path, routine):
    store, c, judge, _, plan, first = setup(tmp_path, routine=routine, max_goals=1)
    total = 8 if routine == "combined" else 7
    assert len(plan.activities) == total
    assert [a["part"] for a in plan.activities] == ["1"] * (total - 4) + ["2"] * 4
    assert [r["goal_id"] for a in plan.activities for r in a["lesson"]["recall"]] == ["recall-price"]
    if routine == "guided":
        assert all(t not in canonical_json(first) for t in [TICKET, PRICE, ALTERNATIVE, THANKS])
    else: assert first["teacher"][-1]["text"] == TICKET
    boundaries = []
    for _ in range(30):
        result = advance(c, store)
        if result["status"] == "paused":
            boundaries.append(result["activity"]["position"])
            assert not result["done"] and result["activity"]["complete"]
            assert result["teacher"][-1]["text"] == plan.activity_end
        if result["done"]: break
    assert result["done"] and boundaries == list(range(total - 1))
    events = outcomes(store)
    assert sum(e["evidence"]["outcome"] == "independent" for e in events) == 7
    assert sum(e["evidence"]["outcome"] == "repeated" for e in events) == (4 if routine == "combined" else 0)
    assert len(judge.calls) == 7
    assert len(store.projection(LEARNER, "session")["activities"]) == total


@pytest.mark.parametrize("cards,spoken", [(True, True), (True, False), (False, True), (False, False)])
def test_cards_and_spoken_tasks_never_supply_hidden_answers_before_attempt(tmp_path, cards, spoken):
    store, c, judge, _, _, first = setup(tmp_path, cards=cards, spoken_tasks=spoken)
    assert bool(first["card"]) == cards
    assert any(s["kind"] == "task" for s in first["teacher"]) == spoken
    assert not any(t in canonical_json(first) for t in [TICKET, PRICE, ALTERNATIVE, THANKS])
    assert judge.calls == []
    turn(c, store, TICKET)
    assert judge.calls[0][0].targets == [TICKET]  # targets are legitimate after the attempt
    e = outcomes(store)[0]
    assert e["evidence"]["outcome"] == "independent" and not e["assistance"]["target_exposed"]
    assert e["assistance"]["kind"] == ("task_card" if cards else "none")


@pytest.mark.parametrize("heard,identical,item", [(ALTERNATIVE, False, "alternative"), (PRICE, True, None), ("Яка загальна сума?", False, None)])
def test_accepted_variant_and_ambiguous_goal_survive_archive_without_invented_item(tmp_path, heard, identical, item):
    store, c, _, _, _, _ = setup(tmp_path, s=source(identical=identical))
    turn(c, store, TICKET); turn(c, store, heard)
    e = outcomes(store)[-1]
    assert e["evidence"]["outcome"] == "independent"
    original = e["provenance"]["original_item"]
    assert (original["item_id"] if original else None) == item
    assert (e["evidence"]["preferred"] is None) == (item is None)
    if item is None:
        assert e["provenance"]["original_source"] is None and "ambiguous" in e["evidence"]["reason"]
        assert e["provenance"]["practice_source"]["source_id"] == "alpha"
    assert weak_queue(store, LEARNER) == []
    root = tmp_path / "archive"; root.mkdir(); a = Archive(root); a.export(store)
    restored = Store(tmp_path / "restore"); a.restore(restored)
    assert restored.events(LEARNER, "session") == store.events(LEARNER, "session")
    engine = Coordinator(restored, Judge())._engine(restored.session(LEARNER, "session"), Judge())
    assert engine.current.evidence[-1].item_id == (item or "")
    assert engine.current.lesson.steps[engine.current.evidence[-1].number - 1].step_id == "price-goal"


def test_social_later_step_and_skipped_goals_preserve_labels(tmp_path):
    judge = Judge(("social",), ("later_step", "", 2), ("accept",))
    store, c, _, _, _, _ = setup(tmp_path, judge=judge)
    turn(c, store, "Добрий день")
    assert outcomes(store) == []
    assert c._engine(store.session(LEARNER, "session"), judge).state.attempts == 0
    turn(c, store, ALTERNATIVE)
    es = outcomes(store)
    assert [(e["evidence"]["outcome"], e["provenance"]["original_item"]["item_id"]) for e in es] == [("skipped", "ticket"), ("independent", "alternative")]
    assert judge.calls[1][0].later == [(2, "Ask the price"), (3, "Thank the seller")]
    assert turn(c, store, THANKS)["status"] == "paused"


@pytest.mark.parametrize("mode,expected", [("cue", "cued"), ("correction", "corrected_repeated"), ("model", "modelled_repeated")])
def test_staged_help_is_recorded_and_preserved_across_real_process_restart(tmp_path, mode, expected):
    first_error = ("error", "квито́к") if mode == "correction" else ("error",)
    judge = Judge(first_error, ("error",) if mode == "model" else ("accept",))
    store, c, _, _, _, _ = setup(tmp_path, judge=judge, cards=False, spoken_tasks=False)
    result = turn(c, store, "wrong answer")
    if mode == "model": result = turn(c, store, "another wrong answer")
    assert result["teacher"][0]["kind"] == mode
    if mode == "model": assert result["teacher"][0]["text"] == TICKET
    saved = store.session(LEARNER, "session")["engine_state"]["data"]["engine"]
    control(c, store, "pause")
    rev = store.session(LEARNER, "session")["revision"]
    script = '''import json,sys
from voice_teacher.storage import Store
from voice_teacher.practice.coordinator import Coordinator
c=Coordinator(Store(sys.argv[1]),lambda *a: (_ for _ in ()).throw(RuntimeError('resume must not judge')))
print(json.dumps(c.control('synthetic-learner','session','fresh-resume',expected_revision=int(sys.argv[2]),operation='resume')))
'''
    resumed = json.loads(subprocess.check_output([sys.executable, "-c", script, str(store.path.parent), str(rev)], text=True))
    assert resumed["teacher"] == result["teacher"] and resumed["card"] is None
    current = store.session(LEARNER, "session")["engine_state"]["data"]["engine"]
    assert current == saved  # resume replays, it does not append help or reset attempts
    c = Coordinator(Store(store.path.parent), Judge())
    turn(c, store, TICKET)
    e = outcomes(store)[-1]
    assert e["evidence"]["outcome"] == expected and e["assistance"]["target_exposed"]


def test_boundary_resume_in_fresh_process_starts_exact_next_goal_and_retry_is_idempotent(tmp_path):
    store, c, _, _, plan, _ = setup(tmp_path, max_goals=1)
    boundary = turn(c, store, TICKET, request="one")
    assert boundary["status"] == "paused" and not boundary["done"]
    before = store.events(LEARNER, "session")
    assert c.submit(LEARNER, "session", "one", expected_revision=0, text=TICKET) == boundary
    assert store.events(LEARNER, "session") == before
    with pytest.raises(RequestConflict): turn(c, store, PRICE)
    script = '''import json,sys
from voice_teacher.storage import Store
from voice_teacher.practice.coordinator import Coordinator
c=Coordinator(Store(sys.argv[1]),lambda *a: (_ for _ in ()).throw(RuntimeError('must not judge')))
print(json.dumps(c.control('synthetic-learner','session','resume',expected_revision=1,operation='resume')))
'''
    resumed = json.loads(subprocess.check_output([sys.executable, "-c", script, str(store.path.parent)], text=True))
    assert resumed["activity"]["position"] == 1 and resumed["card"] == "Your turn: Ask the price."
    assert resumed["teacher"][-2]["text"] == "Ось квиток." and PRICE not in canonical_json(resumed)
    assert len(outcomes(store)) == 1
    c = Coordinator(Store(store.path.parent), Judge())
    assert control(c, store, "stop")["done"]
    assert len(outcomes(store)) == 1


@pytest.mark.parametrize("at_boundary", [False, True])
def test_stop_is_global_with_no_fabricated_attempt(tmp_path, at_boundary):
    store, c, _, _, _, _ = setup(tmp_path, max_goals=1)
    if at_boundary: turn(c, store, TICKET)
    result = control(c, store, "stop") if at_boundary else turn(c, store, "Стоп")
    assert result["done"] and result["teacher"][-1]["text"] == UKRAINIAN.closing
    assert len(outcomes(store)) == int(at_boundary)
    assert c._engine(store.session(LEARNER, "session"), Judge()).done


def test_guided_without_opening_or_recall_and_explicit_sitting_filters(tmp_path):
    s = source(combined=False, count=1, recall=False)
    store, c, _, _, _, _ = setup(tmp_path, s=s, sitting="first_sitting")
    assert turn(c, store, TICKET)["done"]
    for sitting, part in [("first_sitting", "1"), ("second_sitting", "2")]:
        plan = plan_guided(s, "basics", "lesson-1", sitting=sitting)
        assert [a["part"] for a in plan.activities] == [part]
        e = GuidedSession(plan, Judge()); e.start(); e.hear(TICKET)
        assert e.done and [v.round for v in e.evidence] == [int(part)]
    with pytest.raises(ValueError): plan_guided(s, "basics", "lesson-1", routine="combined")


def test_invalid_plans_hidden_prompt_and_snapshot_changes_are_rejected_before_write(tmp_path):
    store, c, _, s, plan, _ = setup(tmp_path)
    bad = deepcopy(plan); bad.activities[0]["lesson"]["steps"][0]["targets"][0] = "forged answer"
    with pytest.raises(StorageError): c.create_guided(template(s, "forged"), bad)
    with pytest.raises(KeyError): store.session(LEARNER, "forged")
    bad = deepcopy(plan); bad.activity_end = "untrusted instruction"
    with pytest.raises(StorageError): c.create_guided(template(s, "forged"), bad)
    for field, value in [("index", True), ("index", 99), ("plan_hash", "wrong"), ("completed", [{}])]:
        engine = GuidedSession(plan, Judge()); engine.start(); saved = engine.snapshot(); saved["data"][field] = value
        with pytest.raises(ValueError): GuidedSession.from_snapshot(plan, Judge(), saved)
    raw = s.curriculum; raw["courses"][0]["lessons"][0]["guided_steps"][0]["goal"] = "Say " + TICKET
    leaking = SourceSnapshot("leaking", canonical_json({"curriculum": raw, "provenance": s.provenance}))
    with pytest.raises(ValueError, match="hidden answer"): plan_guided(leaking, "basics", "lesson-1", cards=False)


def test_cross_chunk_recall_is_not_lost_and_custom_profile_is_pinned(tmp_path):
    s = source(language="pl"); raw = s.curriculum
    raw["courses"][0]["lessons"][0]["recall_goals"][0]["target_item_ids"] = ["ticket", "price"]
    s = SourceSnapshot("cross", canonical_json({"curriculum": raw, "provenance": s.provenance}))
    plan = plan_guided(s, "basics", "lesson-1", max_goals=1)
    assert plan.activities[-1]["lesson"]["recall"][0]["target_item_ids"] == ["ticket", "price"]
    profile = replace(UKRAINIAN, language="pl", stop_words=("koniec",), closing="Koniec.")
    store = Store(tmp_path / "data"); store.save_learner(LEARNER, {})
    c = Coordinator(store, Judge(), profiles={("pl", "en"): profile}); c.create_guided(template(s), plan)
    assert control(Coordinator(Store(store.path.parent), Judge()), store, "stop")["teacher"][-1]["text"] == "Koniec."


def test_api_advertises_and_starts_partial_guided_only_and_validates_mode_options(tmp_path):
    s = source(combined=False, recall=False)
    store = Store(tmp_path / "data"); store.save_learner(LEARNER, {})
    root = tmp_path / "content"; root.mkdir(); (root / "voice-teacher.json").write_text(canonical_json(s.curriculum))
    reg = SourceRegistry(store); reg.register(SourceSpec("alpha", "Alpha", str(root), allow_dirty=True)); reg.refresh("alpha")
    c = Coordinator(store, Judge()); app = create_app(store, c, operator_token="x" * 40, origin="http://teacher.test")
    client = TestClient(app, base_url="http://teacher.test")
    code = app.state.auth.issue_code(LEARNER, "synthetic")["code"]
    token = client.post("/api/v1/pair", json={"code": code}).json()["token"]; headers = {"Authorization": "Bearer " + token}
    listed = client.get("/api/v1/sources/alpha/courses/basics/lessons", headers=headers)
    assert listed.json()[0]["available_modes"] == ["guided_conversation"]
    assert all(t not in listed.text for t in [TICKET, PRICE])
    body = dict(session_id="session", source_id="alpha", course_id="basics", lesson_id="lesson-1", mode="guided_conversation", max_goals=1, cards=False, spoken_tasks=False)
    result = client.post("/api/v1/sessions", json=body, headers=headers)
    assert result.status_code == 201 and result.json()["card"] is None and result.json()["activity"]["total"] == 6
    assert "targets" not in result.text and TICKET not in result.text
    assert client.post("/api/v1/sessions", json={**body, "session_id": "bad", "routine": "combined"}, headers=headers).status_code == 409
    for options in [{"item_ids": ["ticket"]}, {"max_goals": 7}, {"cards": "false"}]:
        assert client.post("/api/v1/sessions", json={**body, "session_id": "bad", **options}, headers=headers).status_code == 422
    boundary = client.post("/api/v1/sessions/session/turns", headers=headers, json=dict(request_id="one", expected_revision=0, text=TICKET))
    assert boundary.status_code == 200 and boundary.json()["status"] == "paused"
    resumed = client.post("/api/v1/sessions/session/controls", headers=headers, json=dict(request_id="next", expected_revision=1, operation="resume"))
    assert resumed.status_code == 200 and resumed.json()["activity"]["position"] == 1


def test_large_review_and_recall_sets_are_bounded_without_losing_authored_items():
    s = source(); raw = s.curriculum; course = raw["courses"][0]; lesson = course["lessons"][0]
    for n in range(13):
        course["items"].append(dict(item_id=f"review-{n}", item_revision=1,
            text=dict(display=f"Synthetic review {n}", speech=f"Synthetic review {n}"), meaning=f"Review meaning {n}"))
    lesson["repetition_item_ids"] = [f"review-{n}" for n in range(13)]
    lesson["recall_goals"] = [dict(goal_id=f"recall-{n}", prompt=dict(display=f"Ask again {n}", speech=f"Ask again {n}"), target_item_ids=["ticket"]) for n in range(9)]
    validate_curriculum(raw)
    s = SourceSnapshot("many", canonical_json({"curriculum": raw, "provenance": s.provenance}))
    plan = plan_guided(s, "basics", "lesson-1", routine="combined", max_goals=2)
    assert [i for a in plan.activities for i in a["lesson"]["opening_item_ids"]] == lesson["repetition_item_ids"]
    assert [r["goal_id"] for a in plan.activities for r in a["lesson"]["recall"]] == [f"recall-{n}" for n in range(9)]
    assert all(len(a["lesson"]["opening"]) <= 6 and len(a["lesson"]["steps"]) <= 2 and len(a["lesson"]["recall"]) <= 2 for a in plan.activities)
    engine = GuidedSession(plan, Judge()); engine.start()
    assert engine.current.lesson.opening_item_ids == [f"review-{n}" for n in range(6)]
    for _ in range(6): engine.hear(engine.current.lesson.opening[engine.current.index])
    assert engine.boundary and not engine.done
    saved = engine.snapshot(); restored = GuidedSession.from_snapshot(plan, Judge(), saved)
    assert restored.resume()[-1].text == "Synthetic review 6"


def test_delivery_failure_and_recognition_report_preserve_guided_capsule_and_boundary(tmp_path):
    store, c, judge, _, _, _ = setup(tmp_path, max_goals=1)
    c.delivery = lambda _: (_ for _ in ()).throw(RuntimeError("synthetic delivery failure"))
    with pytest.raises(RuntimeError): turn(c, store, TICKET, request="one")
    before = store.events(LEARNER, "session")
    c = Coordinator(Store(store.path.parent), Judge())
    recovered = c.submit(LEARNER, "session", "one", expected_revision=0, text=TICKET)
    assert recovered["status"] == "paused" and recovered["activity"]["complete"]
    assert store.events(LEARNER, "session") == before and len(judge.calls) == 1 and c.judge.calls == []
    engine = store.session(LEARNER, "session")["engine_state"]["data"]["engine"]
    c.report_recognition(LEARNER, "session", "one", status="recognized", text="synthetic suspected ASR error")
    snap = store.session(LEARNER, "session")["engine_state"]["data"]
    assert snap["coordinator_version"] == 4 and snap["engine"] == engine
    control(c, store, "resume")
    snap = store.session(LEARNER, "session")["engine_state"]["data"]
    assert snap["coordinator_version"] == 4 and "one" in snap["recognition_reports"]


def test_authored_stop_phrase_is_practice_material_in_guided_and_combined():
    s = source(); raw = s.curriculum
    raw["courses"][0]["items"][0]["text"] = dict(display="Досить, дякую.", speech="Досить, дякую.")
    s = SourceSnapshot("stop-phrase", canonical_json({"curriculum": raw, "provenance": s.provenance}))
    for routine in ["guided", "combined"]:
        plan = plan_guided(s, "basics", "lesson-1", routine=routine)
        e = GuidedSession(plan, Judge()); e.start(); e.hear("Досить, дякую.")
        assert not e.done and not e.stopped and len(e.evidence) == 1


def test_answer_in_question_reply_and_single_word_cue_are_explicit_models():
    class AnsweringJudge:
        def __call__(self, item, text):
            return Judgement(Verdict("question", False, "", "You could say " + TICKET, 0, ""), 0, {})
    plan = plan_guided(source(), "basics", "lesson-1")
    e = GuidedSession(plan, AnsweringJudge()); e.start()
    assert e.hear("How can I ask?")[0].kind == "model"
    assert e.assistance["target_exposed"] and e.state.awaiting_repeat
    e.hear(TICKET)
    assert e.evidence[0].label == "modelled_repeated"
    e = GuidedSession(plan, Judge(("accept",), ("accept",), ("error",)))
    e.start(); e.hear(TICKET); e.hear(PRICE)
    assert e.hear("wrong")[0].kind == "model"  # one-word 'cue' is the full answer
    e.hear(THANKS)
    assert e.evidence[-1].label == "modelled_repeated"


def test_later_step_after_help_does_not_upgrade_the_assisted_turn(tmp_path):
    store, c, _, _, _, _ = setup(tmp_path, judge=Judge(("error",), ("later_step", "", 2)))
    turn(c, store, "wrong")
    turn(c, store, ALTERNATIVE)
    assert [(e["evidence"]["outcome"], e["assistance"]["kind"]) for e in outcomes(store)] == [("skipped", "cue"), ("cued", "cue")]
    assert outcomes(store)[-1]["provenance"]["original_item"]["item_id"] == "alternative"


def test_off_task_acceptance_cannot_be_independent_goal_credit(tmp_path):
    class InconsistentJudge:
        def __call__(self, *args): return Judgement(Verdict("accept", False, "", "", 0, ""), 0, {})
    store, c, _, _, _, _ = setup(tmp_path, judge=InconsistentJudge())
    turn(c, store, "off topic")
    assert outcomes(store) == []
    engine = c._engine(store.session(LEARNER, "session"), Judge())
    assert engine.current.index == 0 and engine.state.help == "cue"
