"""Durable turn intents and provider stages; no external calls in transactions."""
import json

from schemas.validate import canonical_json
from .sqlite import StorageError, RevisionConflict, _id


class RequestConflict(StorageError):
    pass


class WorkBusy(StorageError):
    pass


class WorkStore:
    def __init__(self, store):
        self.store = store

    def get(self, learner, session, request):
        key = tuple(_id(v) for v in (learner, session, request))
        with self.store._connection() as c:
            row = c.execute("SELECT * FROM requests WHERE learner_id=? AND session_id=? AND request_id=?", key).fetchone()
            if row is None:
                raise KeyError("request not found for this learner/session")
            return dict(row)

    def accept(self, learner, session, request, expected_revision, value, *, statuses, cancel_pending=False):
        key = tuple(_id(v) for v in (learner, session, request))
        body = canonical_json(value)
        if type(expected_revision) is not int or expected_revision < 0:
            raise RevisionConflict("invalid expected revision")
        with self.store._transaction() as c:
            old = c.execute("SELECT * FROM requests WHERE learner_id=? AND session_id=? AND request_id=?", key).fetchone()
            if old is not None:
                if old["input_json"] != body or old["expected_revision"] != expected_revision:
                    raise RequestConflict("request ID was already used with different input or revision")
                if old["stage"] == "cancelled":
                    raise RequestConflict("request was cancelled by a session control")
                return dict(old)
            current = c.execute("SELECT revision, snapshot_json FROM sessions WHERE learner_id=? AND session_id=?", key[:2]).fetchone()
            if current is None or current["revision"] != expected_revision:
                raise RevisionConflict("session ownership/revision does not match")
            if json.loads(current["snapshot_json"])["status"] not in statuses:
                raise RequestConflict("operation is not allowed in this session state")
            if cancel_pending:
                c.execute("UPDATE requests SET stage='cancelled' WHERE learner_id=? AND session_id=? AND stage IN ('accepted','judged')", key[:2])
            elif c.execute("SELECT 1 FROM requests WHERE learner_id=? AND session_id=? AND stage IN ('accepted','judged')", key[:2]).fetchone():
                raise WorkBusy("resume the pending request before accepting another turn")
            c.execute("INSERT INTO requests(learner_id,session_id,request_id,expected_revision,input_json,stage) VALUES (?,?,?,?,?,'accepted')",
                      (*key, expected_revision, body))
        return self.get(*key)

    def judgment(self, learner, session, request, value):
        body = canonical_json(value)
        with self.store._transaction() as c:
            key = (learner, session, request)
            c.execute("UPDATE requests SET stage='judged', judgment_json=? WHERE learner_id=? AND session_id=? AND request_id=? AND stage='accepted'", (body, *key))
            row = c.execute("SELECT stage, judgment_json FROM requests WHERE learner_id=? AND session_id=? AND request_id=?", key).fetchone()
            if row is None or row["stage"] == "cancelled" or row["judgment_json"] is None:
                raise RequestConflict("request no longer owns a judge result")
            return json.loads(row["judgment_json"])

    def delivered(self, learner, session, request, value):
        body = canonical_json(value)
        with self.store._transaction() as c:
            key = (learner, session, request)
            c.execute("UPDATE requests SET stage='delivered', delivery_json=? WHERE learner_id=? AND session_id=? AND request_id=? AND stage='committed'", (body, *key))
            row = c.execute("SELECT stage FROM requests WHERE learner_id=? AND session_id=? AND request_id=?", key).fetchone()
            if row is None or row["stage"] != "delivered":
                raise RequestConflict("request has no committed response to deliver")
        return self.get(*key)
