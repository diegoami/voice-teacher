"""Learner decisions are separate from observed practice evidence."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

from schemas.validate import _shape, canonical_json, content_hash, validate_curriculum
from ..storage import StorageError, RevisionConflict, EventConflict
from ..storage.sqlite import _id


def stream_key(value):
    source = value["source"]
    return source["source_id"], source["course_id"], source["revision"]["content_sha256"]


def _request(value):
    if not isinstance(value, dict) or set(value) != {"request_id", "source_id", "course_id", "lesson_id", "version_id", "expected_revision", "completed"}:
        raise StorageError("invalid lesson decision request")
    for key in ("request_id", "source_id", "course_id", "lesson_id", "version_id"):
        _id(value[key])
    if type(value["expected_revision"]) is not int or value["expected_revision"] < 0 or type(value["completed"]) is not bool:
        raise StorageError("invalid lesson decision revision or state")
    return canonical_json(value)


def _identity(learner, request):
    return "decision-" + hashlib.sha256(canonical_json([learner, request]).encode()).hexdigest()


def validate_decision(value):
    _shape("lesson-decision", value)
    request, source = value["request"], value["source"]
    _request(request)
    validate_curriculum(value["curriculum_snapshot"])
    if value["decision_id"] != _identity(value["learner_id"], request["request_id"]) or value["sequence"] != request["expected_revision"] + 1:
        raise StorageError("lesson decision identity/sequence mismatch")
    curriculum = value["curriculum_snapshot"]
    if any(source[k] != request[k] for k in ("source_id", "course_id", "lesson_id")) or curriculum["source_id"] != source["source_id"] or content_hash(curriculum) != source["revision"]["content_sha256"]:
        raise StorageError("lesson decision source mismatch")
    course = next((c for c in curriculum["courses"] if c["course_id"] == source["course_id"]), None)
    if course is None or not any(l["lesson_id"] == source["lesson_id"] for l in course["lessons"]):
        raise StorageError("lesson decision references unknown course/lesson")


def validate_stream(decisions):
    by_id, requests, streams = {}, {}, {}
    for value in decisions:
        validate_decision(value)
        identity = value["decision_id"]
        if by_id.setdefault(identity, value) != value:
            raise EventConflict("lesson decision ID has conflicting contents")
        req = value["learner_id"], value["request"]["request_id"]
        if requests.setdefault(req, value) != value:
            raise EventConflict("lesson decision request has conflicting contents")
        key = (value["learner_id"], *stream_key(value))
        existing = streams.setdefault(key, {})
        if existing.setdefault(value["sequence"], value) != value:
            raise EventConflict("lesson decision sequence has conflicting contents")
    for rows in streams.values():
        if sorted(rows) != list(range(1, len(rows) + 1)):
            raise EventConflict("lesson decision stream has missing history")
    return sorted(by_id.values(), key=lambda v: (v["learner_id"], *stream_key(v), v["sequence"]))


def public_result(value):
    return dict(request_id=value["request"]["request_id"], decision_id=value["decision_id"], revision=value["sequence"], completed=value["request"]["completed"])


def _find(c, learner, request, body):
    row = c.execute("SELECT input_json,body_json FROM lesson_decisions WHERE learner_id=? AND request_id=?", (learner, request["request_id"])).fetchone()
    if row is None:
        return None
    if row["input_json"] != body:
        raise EventConflict("lesson decision request reused with another intent")
    return public_result(json.loads(row["body_json"]))


def find_request(store, learner, request):
    body = _request(request)
    with store._connection() as c:
        return _find(c, _id(learner), request, body)


def record(store, learner, request, source):
    body, learner = _request(request), _id(learner)
    with store._transaction() as c:
        old = _find(c, learner, request, body)
        if old is not None:
            return old
        if source.version_id != request["version_id"]:
            raise RevisionConflict("source version changed; choose again")
        reference = source.source_ref(request["course_id"], request["lesson_id"])
        if reference["source_id"] != request["source_id"]:
            raise RevisionConflict("source identity changed")
        key = reference["source_id"], reference["course_id"], reference["revision"]["content_sha256"]
        count = c.execute("SELECT coalesce(max(sequence),0) FROM lesson_decisions WHERE learner_id=? AND source_id=? AND course_id=? AND content_sha256=?", (learner, *key)).fetchone()[0]
        if count != request["expected_revision"]:
            raise RevisionConflict("lesson choices changed; reload progress")
        if c.execute("SELECT 1 FROM learners WHERE learner_id=?", (learner,)).fetchone() is None:
            raise StorageError("unknown learner")
        value = dict(schema_version=1, kind="lesson_completion_decision", actor="learner",
                     decision_id=_identity(learner, request["request_id"]), learner_id=learner, sequence=count + 1,
                     occurred_at=datetime.now(timezone.utc).isoformat(), request=deepcopy(request),
                     source=reference, curriculum_snapshot=source.curriculum)
        validate_decision(value)
        c.execute("INSERT INTO lesson_decisions VALUES (?,?,?,?,?,?,?,?,?,0)",
                  (value["decision_id"], learner, request["request_id"], *key, value["sequence"], body, canonical_json(value)))
        return public_result(value)


def all_decisions(store, learner=None):
    with store._connection() as c:
        sql = "SELECT body_json FROM lesson_decisions"
        rows = c.execute(sql + (" WHERE learner_id=?" if learner is not None else ""), (_id(learner),) if learner is not None else ())
        return validate_stream([json.loads(r[0]) for r in rows])


def restore_decisions(c, incoming, profiles):
    existing = [json.loads(r[0]) for r in c.execute("SELECT body_json FROM lesson_decisions")]
    validate_stream([*existing, *incoming])
    added = 0
    for value in incoming:
        learner, request = value["learner_id"], value["request"]
        body = _request(request)
        if _find(c, learner, request, body) is not None:
            continue
        if c.execute("SELECT 1 FROM learners WHERE learner_id=?", (learner,)).fetchone() is None:
            c.execute("INSERT INTO learners VALUES (?,?)", (learner, canonical_json(profiles[learner])))
        c.execute("INSERT INTO lesson_decisions VALUES (?,?,?,?,?,?,?,?,?,1)",
                  (value["decision_id"], learner, request["request_id"], *stream_key(value), value["sequence"], body, canonical_json(value)))
        added += 1
    c.executemany("UPDATE lesson_decisions SET exported=1 WHERE decision_id=?", [(v["decision_id"],) for v in incoming])
    return added
