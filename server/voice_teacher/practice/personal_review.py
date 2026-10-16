"""Explicit private review choices; no lesson checkout or vocabulary writes."""
from copy import deepcopy
import hashlib
import json
from uuid import uuid5, NAMESPACE_URL

from schemas.validate import canonical_json
from ..content.registry import SourceSnapshot
from ..storage.sqlite import _id


def target_id(learner,session,observation,form):
    return str(uuid5(NAMESPACE_URL,canonical_json(["personal-review",learner,session,observation,form])))


def validate_targets(state,snapshot):
    observations={r["event_id"]:r for r in state["observations"]}
    seen=set()
    for row in state["review_targets"]:
        fields={"target_id","observation_id","form","text","meaning","origin_session_id","origin_turn_id","language","instruction_language","original_source","original_item"}
        if not isinstance(row,dict) or set(row)!=fields:raise ValueError("invalid private review target")
        observation=observations.get(row["observation_id"])
        if observation is None or row["observation_id"] not in state["published"] or observation["uncertain"]:raise ValueError("review target has no supported published observation")
        if row["form"] not in {"original","preferred"}:raise ValueError("invalid review form")
        claim=observation["claim"]
        chosen=claim["original"] if row["form"]=="original" else claim["preferred"]
        if chosen is None or row["text"]!=chosen or not isinstance(row["meaning"],str) or not row["meaning"].strip() or len(row["meaning"])>500:raise ValueError("review target wording changed")
        identity=target_id(snapshot["learner_id"],snapshot["session_id"],row["observation_id"],row["form"])
        if row["target_id"]!=identity or identity in seen:raise ValueError("invalid review target identity")
        seen.add(identity)
        for key in ("language","instruction_language"):
            if row[key]!=snapshot[key]:raise ValueError("review target language changed")
        if row["origin_session_id"]!=snapshot["session_id"] or row["origin_turn_id"]!=observation["turn"]["turn_id"]:raise ValueError("review origin changed")
        source,item=None,None
        if claim["item_id"] is not None:
            source=snapshot["source"]
            course=next(c for c in snapshot["curriculum_snapshot"]["courses"] if c["course_id"]==source["course_id"])
            authored=next(i for i in course["items"] if i["item_id"]==claim["item_id"])
            item={"source_id":source["source_id"],"course_id":source["course_id"],"item_id":authored["item_id"],"item_revision":authored["item_revision"]}
        if row["original_source"]!=source or row["original_item"]!=item:raise ValueError("review curriculum provenance changed")


def history(store,learner):
    with store._connection() as c:
        c.execute("BEGIN")
        snapshots=[json.loads(r[0]) for r in c.execute("SELECT snapshot_json FROM sessions WHERE learner_id=?",(_id(learner),))]
        events=[json.loads(r[0]) for r in c.execute("SELECT body_json FROM events WHERE learner_id=? ORDER BY session_id,sequence",(learner,))]
    return snapshots,events


def queue(store,learner):
    from .free_feedback import checked_state
    snapshots,events=history(store,learner)
    superseded={e["supersedes_event_id"] for e in events if e["supersedes_event_id"]}
    disputed={(s["session_id"],r["origin_turn_id"]) for s in snapshots for r in s["engine_state"]["data"].get("recognition_reports",{}).values() if r.get("origin_turn_id")}
    result=[]
    for snapshot in snapshots:
        data=snapshot["engine_state"]["data"]
        if data.get("coordinator_version")!=6:continue
        turns=[e["turn"] for e in events if e["session_id"]==snapshot["session_id"] and e["event_type"]=="turn.accepted"]
        state=checked_state(data["feedback"],snapshot,turns)
        for row in state["review_targets"]:
            if row["observation_id"] in superseded or (row["origin_session_id"],row["origin_turn_id"]) in disputed:continue
            result.append(deepcopy(row))
    return sorted(result,key=lambda t:t["target_id"])


def source_id(learner):
    return "private-review-"+hashlib.sha256(_id(learner).encode()).hexdigest()[:24]


def compile_plan(store,learner,target_ids,*,recall_before_model=False):
    from .repetition import plan_lesson
    if not isinstance(target_ids,list) or not 1<=len(target_ids)<=2 or len(set(target_ids))!=len(target_ids):raise ValueError("select one or two personal review targets")
    owned={r["target_id"]:r for r in queue(store,learner)}
    if any(_id(i) not in owned for i in target_ids):raise ValueError("personal target is not in this learner's active queue")
    targets=[owned[i] for i in target_ids]
    pairs={(r["language"],r["instruction_language"]) for r in targets}
    if len(pairs)!=1:raise ValueError("personal review languages must match")
    language,instruction=pairs.pop()
    raw={"schema_version":1,"kind":"curriculum","source_id":source_id(learner),"title":"Personal review",
         "courses":[{"course_id":"personal-review","title":"Personal review","language":language,"instruction_language":instruction,
           "items":[{"item_id":r["target_id"],"item_revision":1,"text":{"display":r["text"],"speech":r["text"]},"meaning":r["meaning"]} for r in targets],
           "lessons":[{"lesson_id":"personal-set","title":"Personal review","modes":["repetition"],"repetition_item_ids":target_ids,"guided_steps":[],"recall_goals":[],"topic":None}]}]}
    source=SourceSnapshot("personal",canonical_json({"curriculum":raw,"provenance":{"commit":None,"dirty":True}}))
    plan=plan_lesson(source,"personal-review","personal-set",item_ids=target_ids,recall_before_model=recall_before_model)
    snapshots,_=history(store,learner)
    by_session={s["session_id"]:s for s in snapshots}
    for target,row in zip(plan.targets,targets):
        target.update(origin_session_id=row["origin_session_id"],origin_turn_id=row["origin_turn_id"],queue_event_id=row["target_id"])
        # Preserve an authored identity only when the explicit review choice is
        # precisely its pinned rendering AND meaning. Otherwise it is private.
        if row["original_item"] is not None:
            original=by_session[row["origin_session_id"]]
            course=next(c for c in original["curriculum_snapshot"]["courses"] if c["course_id"]==row["original_item"]["course_id"])
            item=next(i for i in course["items"] if i["item_id"]==row["original_item"]["item_id"])
            if row["text"] in item["text"].values() and row["meaning"]==item["meaning"]:
                target.update(source=deepcopy(row["original_source"]),item=deepcopy(row["original_item"]))
    plan.validate();return source,plan
