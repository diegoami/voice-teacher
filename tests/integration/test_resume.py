"""Synthetic persisted activities and owner-bound request recovery."""
from pathlib import Path
import json

from fastapi.testclient import TestClient
import pytest

from schemas.validate import canonical_json
from voice_teacher.api import create_app
from voice_teacher.content.registry import SourceSnapshot
from voice_teacher.practice.coordinator import Coordinator
from voice_teacher.practice.guided import plan_guided
from voice_teacher.providers import Judgement, Verdict
from voice_teacher.storage import Store

LEARNER = "synthetic-learner"
ORIGIN = "http://teacher.test"
OPERATOR = "synthetic-operator-" + "x" * 32
TICKET = "Оди́н квито́к, будь ла́ска."


class Judge:
    def __init__(self): self.calls = 0
    def __call__(self, item, text):
        self.calls += 1
        return Judgement(Verdict("error" if text == "bad" else "accept", text != "bad", "", "", 0, ""), 0, {})


def setup(tmp_path):
    store = Store(tmp_path / "data"); store.save_learner(LEARNER, {"level": "A2"})
    raw = json.loads((Path(__file__).parents[1] / "contracts/fixtures/guided.json").read_text())
    raw["source_id"] = "alpha"; course = raw["courses"][0]; lesson = course["lessons"][0]
    course["items"][0]["text"] = {"display": TICKET.replace("\u0301", ""), "speech": TICKET}
    lesson["modes"] = ["guided_conversation", "repetition"]; lesson["repetition_item_ids"] = ["hello"]
    lesson["guided_steps"][0].update(teacher={"display": "Добрий день!", "speech": "До́брий день!"}, goal="Ask for one ticket")
    source = SourceSnapshot("synthetic", canonical_json({"curriculum": raw, "provenance": {"commit": None, "dirty": True}}))
    template = dict(schema_version=1, kind="session_snapshot", learner_id=LEARNER, session_id="session", revision=0,
        event_sequence=0, mode="guided_conversation", status="created", source=source.source_ref("basics", "lesson-1"),
        curriculum_snapshot=raw, topic=None, language="uk", instruction_language="en", learner_profile={"level": "A2"},
        engine_state={"format_version": 1, "data": {}})
    judge = Judge(); c = Coordinator(store, judge); c.create_guided(template, plan_guided(source, "basics", "lesson-1", max_goals=1))
    app = create_app(store, c, operator_token=OPERATOR, origin=ORIGIN)
    client = TestClient(app, base_url=ORIGIN)
    code = app.state.auth.issue_code(LEARNER, "synthetic")["code"]
    token = client.post("/api/v1/pair", json={"code": code}).json()["token"]
    return store, c, judge, app, client, {"Authorization": "Bearer " + token}


def test_owner_can_query_committed_request_without_preparing_speech(tmp_path):
    store, c, judge, app, client, headers = setup(tmp_path)
    assert client.post("/api/v1/sessions/session/turns", headers=headers,
        json=dict(request_id="one", expected_revision=0, text="bad")).status_code == 200
    response = client.get("/api/v1/sessions/session/requests/one", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"request_id": "one", "status": "ready", "revision": 1}
    assert judge.calls == 1


def test_pending_cancelled_and_ready_receipts_are_private_and_survive_restart(tmp_path):
    store, c, judge, app, client, headers = setup(tmp_path)
    c.work.accept(LEARNER, "session", "pending", 0, {"text": "SYNTHETIC_PRIVATE_INPUT"}, statuses={"active"})
    assert client.get("/api/v1/sessions/session/requests/pending", headers=headers).json() == {"request_id": "pending", "status": "pending", "revision": None}
    c.control(LEARNER, "session", "pause", expected_revision=0, operation="pause")
    fresh = Coordinator(Store(store.path.parent), Judge())
    fresh_app = create_app(fresh.store, fresh, operator_token=OPERATOR, origin=ORIGIN)
    fresh_client = TestClient(fresh_app, base_url=ORIGIN)
    cancelled = fresh_client.get("/api/v1/sessions/session/requests/pending", headers=headers)
    assert cancelled.json() == {"request_id": "pending", "status": "cancelled", "revision": None}
    assert "SYNTHETIC_PRIVATE" not in cancelled.text
    assert fresh_client.get("/api/v1/sessions/session/requests/pause", headers=headers).json() == {"request_id": "pause", "status": "ready", "revision": 1}
    assert fresh_client.get("/api/v1/sessions/session/requests/unknown", headers=headers).status_code == 404
    store.save_learner("another", {})
    code = fresh_app.state.auth.issue_code("another", "synthetic")["code"]
    token = fresh_client.post("/api/v1/pair", json={"code": code}).json()["token"]
    assert fresh_client.get("/api/v1/sessions/session/requests/pause", headers={"Authorization": "Bearer " + token}).status_code == 404
    assert fresh_client.get("/api/v1/sessions/session/requests/pause").status_code == 401


def test_mid_cue_pause_restart_resume_preserves_goal_assistance_and_pinned_source(tmp_path):
    store, c, judge, app, client, headers = setup(tmp_path)
    turn = client.post("/api/v1/sessions/session/turns", headers=headers, json=dict(request_id="one", expected_revision=0, text="bad"))
    cue = turn.json()["teacher"]
    before = store.session(LEARNER, "session")
    assert before["engine_state"]["data"]["engine"]["data"]["current"]["data"]["state"]["help"] == "cue"
    assert client.post("/api/v1/sessions/session/controls", headers=headers,
        json=dict(request_id="pause", expected_revision=1, operation="pause")).json()["status"] == "paused"
    store.save_learner(LEARNER, {"level": "C1"})
    fresh_store = Store(store.path.parent); fresh = Coordinator(fresh_store, Judge())
    fresh_client = TestClient(create_app(fresh_store, fresh, operator_token=OPERATOR, origin=ORIGIN), base_url=ORIGIN)
    resumed = fresh_client.post("/api/v1/sessions/session/controls", headers=headers,
        json=dict(request_id="resume", expected_revision=2, operation="resume"))
    assert resumed.status_code == 200 and resumed.json()["teacher"] == cue
    assert fresh_store.session(LEARNER, "session")["source"] == before["source"]
    assert fresh_store.session(LEARNER, "session")["learner_profile"] == {"level": "A2"}
    after = fresh_client.post("/api/v1/sessions/session/turns", headers=headers,
        json=dict(request_id="two", expected_revision=3, text=TICKET))
    assert after.status_code == 200 and after.json()["status"] == "paused" and after.json()["activity"]["complete"]
    evidence = [e for e in fresh_store.events(LEARNER, "session") if e["event_type"] == "evidence.recorded"]
    assert len(evidence) == 1 and evidence[0]["evidence"]["outcome"] == "cued"
    assert evidence[0]["assistance"]["kind"] == "cue"
    assert evidence[0]["provenance"]["original_source"] == before["source"]
