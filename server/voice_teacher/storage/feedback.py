"""Durable post-attempt decisions, separate from the cached dialogue reply."""
import json
from schemas.validate import canonical_json
from .sqlite import _id
from .work import RequestConflict


class FeedbackStore:
    def __init__(self,store):self.store=store

    def get(self,learner,session,request,context,identity):
        key=tuple(_id(v) for v in (learner,session,request))
        with self.store._connection() as c:
            row=c.execute("SELECT context_json,decision_json FROM feedback_decisions WHERE learner_id=? AND session_id=? AND request_id=?",key).fetchone()
        if row is None:return None
        if row["context_json"]!=canonical_json({"provider":identity,"context":context}):raise RequestConflict("feedback context changed")
        return json.loads(row["decision_json"])

    def save(self,learner,session,request,context,identity,value):
        key=tuple(_id(v) for v in (learner,session,request))
        body=canonical_json(value);input_body=canonical_json({"provider":identity,"context":context})
        with self.store._transaction() as c:
            pending=c.execute("SELECT input_json,stage FROM requests WHERE learner_id=? AND session_id=? AND request_id=?",key).fetchone()
            if pending is None or pending["stage"] not in {"accepted","judged"} or json.loads(pending["input_json"]).get("text")!=context["turn"]["text"]:
                raise RequestConflict("feedback has no matching pending learner request")
            c.execute("INSERT OR IGNORE INTO feedback_decisions VALUES (?,?,?,?,?)",(*key,input_body,body))
            row=c.execute("SELECT context_json,decision_json FROM feedback_decisions WHERE learner_id=? AND session_id=? AND request_id=?",key).fetchone()
            if row["context_json"]!=input_body or row["decision_json"]!=body:raise RequestConflict("feedback decision changed")
        return json.loads(body)
