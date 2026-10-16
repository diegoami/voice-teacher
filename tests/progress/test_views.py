"""Synthetic owner-bound history and explicit item-practice coverage."""
from fastapi.testclient import TestClient

from voice_teacher.api import create_app
from voice_teacher.storage import Store
from test_roundtrip import LEARNER, session, turn


def client_for(store, coordinator, *, learner=LEARNER, sync=None):
    app = create_app(store, coordinator, operator_token="synthetic-operator-" + "x" * 40,
                     origin="http://teacher.test", **({"progress_sync": sync} if sync else {}))
    client = TestClient(app, base_url="http://teacher.test")
    code = app.state.auth.issue_code(learner, "synthetic")["code"]
    token = client.post("/api/v1/pair", json={"code": code}).json()["token"]
    return client, {"Authorization": "Bearer " + token}


def test_partial_session_is_visible_without_inventing_coverage(tmp_path):
    store = Store(tmp_path / "data")
    c = session(store)
    client, headers = client_for(store, c)
    response = client.get("/api/v1/progress", headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["sessions"][0]["session_id"] == "alpha"
    assert result["sessions"][0]["status"] == "active"
    assert result["courses"][0]["covered_items"] == 0
    assert result["courses"][0]["next_lesson_id"] == "lesson-1"
    assert result["sync"]["configured"] is False
    assert result["sync"]["locally_saved"] == len(store.events(LEARNER,"alpha"))

from copy import deepcopy
import json
from pathlib import Path
import pytest
from schemas.validate import canonical_json
from voice_teacher.content.registry import SourceSnapshot
from voice_teacher.practice.coordinator import Coordinator
from voice_teacher.practice.repetition import plan_lesson
from voice_teacher.progress.views import summary, evidence
from test_roundtrip import Judge


def repetition(store, name, source_id, *, recall=False, revision=1, extra_course=False, selected_course="basics"):
    raw = json.loads((Path(__file__).parents[1] / "contracts/fixtures/repetition.json").read_text())
    raw["source_id"] = source_id
    if extra_course:
        second = deepcopy(raw["courses"][0]);second["course_id"]="advanced";second["title"]="Advanced"
        raw["courses"].append(second)
    course = next(c for c in raw["courses"] if c["course_id"]==selected_course)
    course["items"][0]["item_revision"] = revision
    source = SourceSnapshot("synthetic", canonical_json({"curriculum":raw,"provenance":{"commit":None,"dirty":True}}))
    lesson = course["lessons"][0]
    plan = plan_lesson(source,course["course_id"],lesson["lesson_id"],recall_before_model=recall)
    template = dict(schema_version=1,kind="session_snapshot",learner_id=LEARNER,session_id=name,revision=0,event_sequence=0,
                    mode="repetition",status="created",source=source.source_ref(course["course_id"],lesson["lesson_id"]),curriculum_snapshot=raw,
                    topic=None,language="uk",instruction_language="en",learner_profile={"level":"A2","private_note":"SYNTHETIC_PRIVATE"},engine_state={"format_version":1,"data":{}})
    store.save_learner(LEARNER,template["learner_profile"])
    c=Coordinator(store,Judge());c.create_repetition(template,plan)
    return c,plan


def test_separate_sources_and_revisions_keep_repetition_distinct_from_independent_use(tmp_path):
    store=Store(tmp_path/"data")
    repeated, rp = repetition(store,"repeat-alpha","alpha")
    turn(repeated,"repeat-alpha",rp.targets[0]["display"])
    independent, ip = repetition(store,"recall-beta","beta",recall=True)
    turn(independent,"recall-beta",ip.targets[0]["display"])
    repetition(store,"new-alpha","alpha",revision=2)
    view=summary(store,LEARNER)
    old_alpha=next(c for c in view["courses"] if c["source_id"]=="alpha" and c["covered_items"])
    assert old_alpha["covered_items"] == old_alpha["required_items"] == 1
    assert old_alpha["next_lesson_id"] is None
    assert next(c for c in view["courses"] if c["source_id"]=="alpha" and not c["covered_items"])["next_lesson_id"] is not None
    assert next(c for c in view["courses"] if c["source_id"]=="beta")["covered_items"]==1
    assert evidence(store,LEARNER,"repeat-alpha")["rows"][0]["outcome"]=="repeated"
    assert evidence(store,LEARNER,"recall-beta")["rows"][0]["outcome"]=="independent"
    assert not evidence(store,LEARNER,"recall-beta")["rows"][0]["correction"]
    assert "mastery" in view["criterion"]
    assert "SYNTHETIC_PRIVATE" not in json.dumps(view)


def test_corrected_and_partial_history_links_to_its_actual_turn_and_retains_provenance(tmp_path):
    store=Store(tmp_path/"data")
    from voice_teacher.providers import Judgement, Verdict
    class CorrectionJudge:
        calls=0
        def __call__(self,item,text):
            self.calls+=1
            return Judgement(Verdict("error" if self.calls==1 else "accept",True,"Вітаю","",0,""),0,{})
    c=session(store,judge=CorrectionJudge())
    turn(c,text="Wrong synthetic greeting")
    turn(c,text="Привіт")
    rev=store.session(LEARNER,"alpha")["revision"]
    c.control(LEARNER,"alpha","finish",expected_revision=rev,operation="stop")
    client,headers=client_for(store,c)
    result=client.get("/api/v1/sessions/alpha/evidence",headers=headers)
    assert result.status_code==200,result.text
    row=result.json()["rows"][0]
    assert row["correction"] and row["outcome"]=="corrected_repeated"
    assert row["assistance"]["kind"]=="correction"
    assert row["turn"]["text"]=="Привіт" and row["attempt"]=="Привіт"
    turns=client.get("/api/v1/sessions/alpha/transcript",headers=headers).json()
    assert any(t["turn_id"]==row["turn"]["turn_id"] for t in turns)
    assert row["provenance"]["original_source"]==store.session(LEARNER,"alpha")["source"]
    view=client.get("/api/v1/progress",headers=headers).json()
    assert view["sessions"][0]["status"]=="finished"
    assert view["courses"][0]["covered_items"]==1
    assert view["sessions"][0]["accepted_turns"]==2
    assert "engine_state" not in result.text and "curriculum_snapshot" not in result.text


def test_progress_and_evidence_are_owner_bound_and_page_limits_are_validated(tmp_path):
    store=Store(tmp_path/"data");c=session(store);turn(c);turn(c)
    client,headers=client_for(store,c)
    page=client.get("/api/v1/sessions/alpha/evidence?limit=1",headers=headers)
    assert page.status_code==200 and len(page.json()["rows"])==1 and page.json()["next_offset"]==1
    assert len(client.get("/api/v1/sessions/alpha/evidence?offset=1&limit=1",headers=headers).json()["rows"])==1
    assert client.get("/api/v1/progress").status_code==401
    assert client.get("/api/v1/progress?limit=101",headers=headers).status_code==422
    assert client.get("/api/v1/sessions/alpha/evidence?offset=-1",headers=headers).status_code==422
    store.save_learner("another",{})
    other,other_headers=client_for(store,c,learner="another")
    assert other.get("/api/v1/progress",headers=other_headers).json()["sessions"]==[]
    assert other.get("/api/v1/sessions/alpha/evidence",headers=other_headers).status_code==404
    assert other.get("/api/v1/sessions/missing/evidence",headers=other_headers).status_code==404


def test_cross_source_practice_and_supersession_do_not_merge_the_courses(tmp_path):
    store=Store(tmp_path/"data");a=session(store);turn(a)
    b=session(store,"beta");turn(b,"beta")
    original=store.projection(LEARNER,"alpha")["evidence"][0]
    old=store.projection(LEARNER,"beta")["evidence"][0]
    saved=store.session(LEARNER,"beta")
    cross=deepcopy(old);cross.update(event_id="cross",sequence=saved["event_sequence"]+2)
    cross["provenance"].update(original_source=original["source"],original_item=original["provenance"]["original_item"],origin_session_id="alpha",origin_turn_id=original["turn"]["turn_id"])
    superseded=deepcopy(old);superseded.update(event_id="superseded",sequence=saved["event_sequence"]+1,event_type="observation.superseded",evidence=None,assistance=None,supersedes_event_id=old["event_id"])
    checkpoint=deepcopy(store.events(LEARNER,"beta")[-1]);checkpoint.update(event_id="cross-state",sequence=cross["sequence"]+1)
    saved.update(revision=saved["revision"]+1,event_sequence=checkpoint["sequence"]);checkpoint["snapshot"]=saved
    store.commit(LEARNER,"beta",[superseded,cross,checkpoint],expected_revision=1)
    rows=evidence(store,LEARNER,"beta")["rows"]
    assert rows[0]["superseded"] and not rows[1]["superseded"]
    assert rows[1]["provenance"]["original_source"]["source_id"]=="alpha"
    assert rows[1]["provenance"]["practice_source"]["source_id"]=="beta"
    courses=summary(store,LEARNER)["courses"]
    assert next(c for c in courses if c["source_id"]=="alpha")["covered_items"]==1
    assert next(c for c in courses if c["source_id"]=="beta")["covered_items"]==0


def test_real_sync_failure_and_retry_keep_saved_exported_and_pushed_distinct(tmp_path,monkeypatch):
    from test_git_sync import remote, worker
    from voice_teacher.progress.git_sync import SyncError
    w=worker(tmp_path,remote(tmp_path));c=session(w.store)
    client,headers=client_for(w.store,c,sync=w)
    read=lambda:client.get("/api/v1/progress",headers=headers).json()["sync"]
    local=read();assert local["configured"] and local["locally_saved"]>0 and local["pushed"]==0
    original=w._git
    def fail_push(*args,**kw):
        if args[0]=="push":raise SyncError("SYNTHETIC_PRIVATE_FAILURE")
        return original(*args,**kw)
    monkeypatch.setattr(w,"_git",fail_push)
    with pytest.raises(SyncError):w.run_once()
    exported=read();assert exported["locally_saved"]==0 and exported["exported"]==local["locally_saved"] and exported["pushed"]==0
    assert exported["error"] and "SYNTHETIC_PRIVATE" not in json.dumps(exported)
    monkeypatch.setattr(w,"_git",original);w.run_once()
    pushed=read();assert pushed["exported"]==0 and pushed["pushed"]==local["locally_saved"] and pushed["last_push_at"]
    turn(c)
    mixed=read();assert mixed["pushed"]==pushed["pushed"] and mixed["locally_saved"]>0
    monkeypatch.setattr(w,"status",lambda:(_ for _ in ()).throw(RuntimeError("SYNTHETIC_PRIVATE")))
    unavailable=read();assert unavailable["pushed"]==0 and unavailable["exported"]==pushed["pushed"] and unavailable["error"]


@pytest.mark.parametrize("uncertain",[False,True])
def test_free_observations_and_unanswered_models_do_not_claim_course_coverage(tmp_path,uncertain):
    from voice_teacher.practice.free import plan_free, FreePolicy
    from voice_teacher.providers.dialogue import DialogueReply
    store=Store(tmp_path/"data");r,plan=repetition(store,"model-only","alpha")
    raw=store.session(LEARNER,"model-only")["curriculum_snapshot"]
    raw["courses"][0]["lessons"][0]["modes"].append("free_conversation")
    raw["courses"][0]["lessons"][0]["topic"]="Travel"
    source=SourceSnapshot("synthetic",canonical_json({"curriculum":raw,"provenance":{"commit":None,"dirty":True}}))
    class Dialogue:
        identity={"provider":"synthetic","model":"fixture","policy_version":1,"max_reply_tokens":128}
        def __call__(self,context):return DialogueReply("Розкажіть більше.",0,{})
    c=Coordinator(store,Judge(),dialogue=Dialogue())
    free=plan_free(source,plan.course_id,plan.lesson_id,topic="Travel",learner_level="A2",provider=Dialogue.identity,policy=FreePolicy())
    snapshot=deepcopy(store.session(LEARNER,"model-only"));snapshot.update(session_id="free",revision=0,event_sequence=0,mode="free_conversation",status="created",source=free.source,curriculum_snapshot=raw,topic="Travel",engine_state={"format_version":1,"data":{}})
    c.create_free(snapshot,free);turn(c,"free","Привіт")
    accepted=next(e for e in store.events(LEARNER,"free") if e["event_type"]=="turn.accepted")
    saved=store.session(LEARNER,"free")
    observation=deepcopy(accepted);observation.update(event_id="observed",sequence=saved["event_sequence"]+1,event_type="evidence.recorded",evidence={"outcome":"observed","attempt":"Привіт","preferred":"Вітаю","reason":"Supported alternate wording","recognition_uncertain":uncertain})
    observation["provenance"].update(original_source=plan.targets[0]["source"],original_item=plan.targets[0]["item"])
    state=deepcopy(store.events(LEARNER,"free")[-1]);state.update(event_id="observation-state",sequence=observation["sequence"]+1)
    saved.update(revision=saved["revision"]+1,event_sequence=state["sequence"]);state["snapshot"]=saved
    store.commit(LEARNER,"free",[observation,state],expected_revision=1)
    view=summary(store,LEARNER)
    assert all(course["covered_items"]==0 and course["next_lesson_id"] for course in view["courses"])
    row=evidence(store,LEARNER,"free")["rows"][0]
    assert row["outcome"]=="observed" and row["correction"] is (not uncertain)
    assert row["recognition_uncertain"] is uncertain and row["turn"]["text"]=="Привіт"


def test_two_courses_in_the_same_source_revision_keep_independent_positions(tmp_path):
    store=Store(tmp_path/"data")
    first,plan=repetition(store,"basics","alpha",extra_course=True)
    second,_=repetition(store,"advanced","alpha",extra_course=True,selected_course="advanced")
    turn(first,"basics",plan.targets[0]["display"])
    courses=summary(store,LEARNER)["courses"]
    assert len(courses)==2 and len({c["content_sha256"] for c in courses})==1
    assert next(c for c in courses if c["course_id"]=="basics")["next_lesson_id"] is None
    assert next(c for c in courses if c["course_id"]=="advanced")["covered_items"]==0
    assert next(c for c in courses if c["course_id"]=="advanced")["next_lesson_id"]=="lesson-1"
