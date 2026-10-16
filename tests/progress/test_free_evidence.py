"""Synthetic free feedback with accepted-turn attribution, never provider calls."""
from copy import deepcopy

from voice_teacher.practice.coordinator import Coordinator
from voice_teacher.practice.free import FreePolicy, plan_free
from voice_teacher.providers.dialogue import DialogueReply
from voice_teacher.providers.feedback import FeedbackReply
from voice_teacher.storage import Store

LEARNER="synthetic-learner"


class Dialogue:
    identity={"provider":"synthetic","model":"dialogue-v1","policy_version":1,"max_reply_tokens":256}
    def __init__(self):self.calls=0
    def __call__(self,context):
        self.calls+=1
        return DialogueReply("Цікаво. Розкажіть більше.",0,{})


class Feedback:
    identity={"provider":"synthetic","model":"feedback-v1","policy_version":1,"max_reply_tokens":512}
    def __init__(self):self.calls=[]
    def __call__(self,context):
        self.calls.append(deepcopy(context))
        turn=context["turn"]
        return FeedbackReply([{"turn_id":turn["turn_id"],"original":turn["text"],"preferred":turn["text"].replace("потяг.","потягом."),"reason":"Use the instrumental form for the means of transport.","item_id":None}],0,{})


def setup(tmp_path,style="light_immediate"):
    store=Store(tmp_path/"data");store.save_learner(LEARNER,{"level":"A2","private_note":"SYNTHETIC_PRIVATE"})
    dialogue,feedback=Dialogue(),Feedback()
    c=Coordinator(store,lambda *a: (_ for _ in ()).throw(AssertionError("no fixed-target judge")),dialogue=dialogue)
    c.feedback=feedback
    plan=plan_free(None,None,None,topic="Travel",learner_level="A2",provider=dialogue.identity,policy=FreePolicy(),correction_style=style)
    template=dict(schema_version=1,kind="session_snapshot",learner_id=LEARNER,session_id="free",revision=0,event_sequence=0,mode="free_conversation",status="created",source=None,curriculum_snapshot=None,topic="Travel",language="uk",instruction_language="en",learner_profile=store.learner(LEARNER),engine_state={"format_version":1,"data":{}})
    c.create_free(template,plan)
    return store,c,dialogue,feedback


def test_supported_observation_references_the_actual_accepted_learner_wording(tmp_path):
    store,c,dialogue,feedback=setup(tmp_path)
    c.submit(LEARNER,"free","one",expected_revision=0,text="Я їду потяг.")
    rows=store.projection(LEARNER,"free")["evidence"]
    assert len(rows)==1
    observed=rows[0]
    assert observed["evidence"]["outcome"]=="observed"
    assert observed["turn"]["text"]==observed["evidence"]["attempt"]=="Я їду потяг."
    assert observed["evidence"]["preferred"]=="Я їду потягом."
    assert observed["provenance"]["original_item"] is None
    assert feedback.calls[0]["turn"]["turn_id"]==observed["turn"]["turn_id"]
    assert "SYNTHETIC_PRIVATE" not in str(feedback.calls)

import json
from pathlib import Path
import subprocess
import sys
import pytest
from voice_teacher.progress.archive import Archive
from voice_teacher.storage import StorageError


def test_end_preference_holds_feedback_until_finish_and_preserves_original_turns(tmp_path):
    store,c,dialogue,feedback=setup(tmp_path,"end_of_session")
    first=c.submit(LEARNER,"free","one",expected_revision=0,text="Я їду потяг.")
    second=c.submit(LEARNER,"free","two",expected_revision=1,text="Він їде потяг.")
    assert not store.projection(LEARNER,"free")["evidence"]
    assert all(t["kind"]!="feedback" for t in first["teacher"]+second["teacher"])
    finished=c.control(LEARNER,"free","finish",expected_revision=2,operation="stop")
    rows=store.projection(LEARNER,"free")["evidence"]
    assert len(rows)==2 and {r["turn"]["text"] for r in rows}=={"Я їду потяг.","Він їде потяг."}
    assert [t["kind"] for t in finished["teacher"]]==["feedback","feedback","close"]
    assert len(feedback.calls)==2 and dialogue.calls==2
    assert c.control(LEARNER,"free","finish",expected_revision=2,operation="stop")==finished
    assert len(store.projection(LEARNER,"free")["evidence"])==2
    root=tmp_path/"archive";root.mkdir();a=Archive(root);a.export(store)
    restored=Store(tmp_path/"restored");a.restore(restored)
    assert restored.session(LEARNER,"free")==store.session(LEARNER,"free")
    assert restored.events(LEARNER,"free")==store.events(LEARNER,"free")


def test_feedback_failure_retries_cached_dialogue_instead_of_regenerating_it(tmp_path):
    store,c,dialogue,feedback=setup(tmp_path)
    class Broken:
        identity=Feedback.identity
        def __call__(self,context):raise RuntimeError("synthetic feedback failure")
    c.feedback=Broken()
    before=store.session(LEARNER,"free");events=store.events(LEARNER,"free")
    with pytest.raises(RuntimeError):c.submit(LEARNER,"free","one",expected_revision=0,text="Я їду потяг.")
    assert store.session(LEARNER,"free")==before and store.events(LEARNER,"free")==events
    assert dialogue.calls==1
    c.feedback=feedback
    c.submit(LEARNER,"free","one",expected_revision=0,text="Я їду потяг.")
    assert dialogue.calls==1 and len(feedback.calls)==1 and len(store.projection(LEARNER,"free")["evidence"])==1


def test_saved_feedback_and_dialogue_recover_in_a_real_fresh_process_without_providers(tmp_path,monkeypatch):
    store,c,dialogue,feedback=setup(tmp_path)
    commit=store.commit
    def crash(*a,**kw):raise RuntimeError("synthetic crash after durable feedback before atomic events")
    monkeypatch.setattr(store,"commit",crash)
    with pytest.raises(RuntimeError):c.submit(LEARNER,"free","one",expected_revision=0,text="Я їду потяг.")
    assert not store.projection(LEARNER,"free")["evidence"]
    assert dialogue.calls==1 and len(feedback.calls)==1
    script='''import json,sys
from voice_teacher.storage import Store
from voice_teacher.practice.coordinator import Coordinator
s=Store(sys.argv[1]);c=Coordinator(s,lambda *a:(_ for _ in ()).throw(AssertionError('must not judge')))
r=c.submit('synthetic-learner','free','one',expected_revision=0,text='Я їду потяг.')
print(json.dumps({'result':r,'evidence':s.projection('synthetic-learner','free')['evidence']}))
'''
    fresh=json.loads(subprocess.check_output([sys.executable,"-c",script,str(store.path.parent)],text=True))
    assert len(fresh["evidence"])==1 and fresh["result"]["revision"]==1
    monkeypatch.setattr(store,"commit",commit)
    assert c.submit(LEARNER,"free","one",expected_revision=0,text="Я їду потяг.")==fresh["result"]
    assert len(store.projection(LEARNER,"free")["evidence"])==1 and dialogue.calls==1 and len(feedback.calls)==1


def test_fabricated_reference_and_changed_feedback_provider_cannot_advance_a_session(tmp_path):
    store,c,dialogue,feedback=setup(tmp_path)
    class Fabricated(Feedback):
        def __call__(self,context):
            reply=super().__call__(context);reply.observations[0]["turn_id"]="someone-else"
            return reply
    c.feedback=Fabricated();before=store.events(LEARNER,"free")
    with pytest.raises(ValueError):c.submit(LEARNER,"free","one",expected_revision=0,text="Я їду потяг.")
    assert store.events(LEARNER,"free")==before
    wrong=Feedback();wrong.identity={**wrong.identity,"model":"different-model"};c.feedback=wrong
    with pytest.raises(StorageError):c.submit(LEARNER,"free","one",expected_revision=0,text="Я їду потяг.")
    assert not wrong.calls and store.events(LEARNER,"free")==before
    c.feedback=feedback;c.submit(LEARNER,"free","one",expected_revision=0,text="Я їду потяг.")
    assert dialogue.calls==1


def test_explicit_personal_review_survives_archive_and_can_be_practised_without_lesson_writes(tmp_path):
    from voice_teacher.practice.personal_review import queue
    store,c,dialogue,feedback=setup(tmp_path)
    assert queue(store,LEARNER)==[]
    c.submit(LEARNER,"free","one",expected_revision=0,text="Я їду потяг.")
    assert queue(store,LEARNER)==[]
    observation=store.projection(LEARNER,"free")["evidence"][0]
    before=store.projection(LEARNER,"free")["turns"]
    promoted=c.promote_personal(LEARNER,"free","promote",expected_revision=1,observation_id=observation["event_id"],form="preferred",meaning="I travel by train")
    target=promoted["target"]
    assert c.promote_personal(LEARNER,"free","promote",expected_revision=1,observation_id=observation["event_id"],form="preferred",meaning="I travel by train")==promoted
    assert store.projection(LEARNER,"free")["turns"]==before
    assert len(queue(store,LEARNER))==1 and target["origin_turn_id"]==observation["turn"]["turn_id"]
    first=c.create_personal_review(LEARNER,"review",[target["target_id"]])
    assert first["status"]=="active" and first["teacher"]
    c.submit(LEARNER,"review","repeat",expected_revision=0,text=target["text"])
    repeated=store.projection(LEARNER,"review")["evidence"][0]
    assert repeated["evidence"]["outcome"]=="repeated"
    assert repeated["provenance"]["origin_session_id"]=="free" and repeated["provenance"]["origin_turn_id"]==target["origin_turn_id"]
    assert repeated["provenance"]["original_source"]["source_id"].startswith("private-review-")
    assert len(feedback.calls)==1 and dialogue.calls==1
    root=tmp_path/"archive";root.mkdir();a=Archive(root);a.export(store)
    restored=Store(tmp_path/"restored");a.restore(restored)
    assert queue(restored,LEARNER)==queue(store,LEARNER)
    resumed=Coordinator(restored,lambda *a:(_ for _ in ()).throw(AssertionError("no repetition judge")))
    resumed.create_personal_review(LEARNER,"another-review",[target["target_id"]])
    assert restored.session(LEARNER,"another-review")["source"]["source_id"].startswith("private-review-")


def test_recognition_dispute_suppresses_held_correction_and_blocks_personal_promotion(tmp_path):
    from voice_teacher.practice.personal_review import queue
    store,c,dialogue,feedback=setup(tmp_path,"end_of_session")
    c.submit(LEARNER,"free","one",expected_revision=0,text="Я їду потяг.")
    c.report_recognition(LEARNER,"free","one",status="recognized",text="Я їду потяг.")
    finished=c.control(LEARNER,"free","finish",expected_revision=2,operation="stop")
    rows=store.projection(LEARNER,"free")["evidence"]
    assert len(rows)==1 and rows[0]["evidence"]["recognition_uncertain"]
    assert [t["kind"] for t in finished["teacher"]]==["close"]
    with pytest.raises(StorageError):c.promote_personal(LEARNER,"free","promote",expected_revision=3,observation_id=rows[0]["event_id"],form="preferred",meaning="I travel by train")
    assert queue(store,LEARNER)==[]


def test_promotion_is_deliberate_immutable_and_excludes_later_disputed_targets(tmp_path):
    from voice_teacher.practice.personal_review import queue
    store,c,_,_=setup(tmp_path)
    c.submit(LEARNER,"free","one",expected_revision=0,text="Я їду потяг.")
    observed=store.projection(LEARNER,"free")["evidence"][0]
    promoted=c.promote_personal(LEARNER,"free","promote",expected_revision=1,observation_id=observed["event_id"],form="preferred",meaning="I travel by train")
    with pytest.raises(StorageError):c.promote_personal(LEARNER,"free","different-meaning",expected_revision=2,observation_id=observed["event_id"],form="preferred",meaning="A different meaning")
    c.report_recognition(LEARNER,"free","one",status="recognized",text="Я їду потяг.")
    assert queue(store,LEARNER)==[]
    with pytest.raises(ValueError):c.create_personal_review(LEARNER,"review",[promoted["target"]["target_id"]])
    assert store.session(LEARNER,"free")["engine_state"]["data"]["feedback"]["review_targets"]==[promoted["target"]]


def test_changed_feedback_configuration_refuses_new_generation_before_any_provider_call(tmp_path):
    store,c,dialogue,feedback=setup(tmp_path)
    c.feedback=None
    with pytest.raises(StorageError):c.submit(LEARNER,"free","one",expected_revision=0,text="Я їду потяг.")
    assert dialogue.calls==0 and not feedback.calls and store.session(LEARNER,"free")["revision"]==0
    c.feedback=feedback
    c.submit(LEARNER,"free","one",expected_revision=0,text="Я їду потяг.")
    assert dialogue.calls==1 and len(feedback.calls)==1
