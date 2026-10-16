"""Portable engine-state capsule. Durable transactions are owned by T05/T06."""
from dataclasses import asdict
import hashlib
import json


def _copy(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def snapshot(session):
    return _copy({"format_version": 1, "data": {
        "lesson_hash": _hash(session.lesson.to_dict()), "profile_hash": _hash(asdict(session.profile)),
        "part": session.part, "phase": session.phase, "round": session.round, "index": session.index,
        "resaid": session.resaid, "state": asdict(session.state), "card": session.card,
        "evidence": [asdict(e) for e in session.evidence], "log": session.log,
    }})


def restore(cls, lesson, judge, saved, *, profile, clock):
    from .session import ItemState, Evidence
    saved = _copy(saved)
    if set(saved) != {"format_version", "data"} or type(saved["format_version"]) is not int or saved["format_version"] != 1:
        raise ValueError("unsupported engine snapshot version")
    d = saved["data"]
    fields = {"lesson_hash", "profile_hash", "part", "phase", "round", "index", "resaid", "state", "card", "evidence", "log"}
    if not isinstance(d, dict) or set(d) != fields:
        raise ValueError("invalid engine snapshot fields")
    if d["lesson_hash"] != _hash(lesson.to_dict()) or d["profile_hash"] != _hash(asdict(profile)):
        raise ValueError("snapshot does not match pinned lesson/profile")
    if d["phase"] not in {"new", "opening", "guided", "recall", "closed"}:
        raise ValueError("invalid snapshot phase")
    if type(d["round"]) is not int or d["round"] not in [0, 1, 2] or type(d["index"]) is not int or d["index"] < 0:
        raise ValueError("invalid snapshot position")
    if type(d["resaid"]) is not bool or (d["card"] is not None and not isinstance(d["card"], str)):
        raise ValueError("invalid snapshot presentation")
    session = cls(lesson, judge, clock=clock, part=d["part"], profile=profile)
    active = {"opening": len(lesson.opening), "guided": len(session.model_items) if d["round"] == 0 else len(lesson.steps),
              "recall": len(lesson.recall)}
    if d["phase"] in active and d["index"] >= active[d["phase"]]:
        raise ValueError("snapshot position outside lesson")
    state = ItemState(**d["state"])
    for value in [state.attempts, state.unclear, state.repeat_tries]:
        if type(value) is not int or value < 0:
            raise ValueError("invalid help counters")
    if state.help not in ["", "cue", "correction", "model"] or type(state.awaiting_repeat) is not bool:
        raise ValueError("invalid help state")
    if not isinstance(state.history, list) or any(not isinstance(row, list) or len(row) != 2 or
            not all(isinstance(t, str) for t in row) for row in state.history):
        raise ValueError("invalid attempt history")
    state.history = [tuple(row) for row in state.history]
    if not isinstance(d["evidence"], list) or not isinstance(d["log"], list):
        raise ValueError("invalid snapshot history")
    session.phase, session.round, session.index = d["phase"], d["round"], d["index"]
    session.resaid, session.card, session.state = d["resaid"], d["card"], state
    session.evidence = [Evidence(**e) for e in d["evidence"]]
    session.log = d["log"]
    return session
