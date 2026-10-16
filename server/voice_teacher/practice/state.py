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
    if not isinstance(saved, dict) or set(saved) != {"format_version", "data"} or type(saved["format_version"]) is not int or saved["format_version"] != 1:
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
    if (d["phase"] == "new" and d["index"] != 0) or (d["phase"] in {"new", "opening", "recall"} and d["round"] != 0):
        raise ValueError("snapshot phase and position disagree")
    state = ItemState(**d["state"])
    for value in [state.attempts, state.unclear, state.repeat_tries]:
        if type(value) is not int or value < 0:
            raise ValueError("invalid help counters")
    if state.help not in ["", "cue", "correction", "model"] or type(state.awaiting_repeat) is not bool:
        raise ValueError("invalid help state")
    if state.awaiting_repeat != (state.help == "model") or state.unclear > 1 or state.repeat_tries > 1:
        raise ValueError("inconsistent help state")
    if not isinstance(state.history, list) or any(not isinstance(row, list) or len(row) != 2 or
            not all(isinstance(t, str) for t in row) for row in state.history):
        raise ValueError("invalid attempt history")
    state.history = [tuple(row) for row in state.history]
    if not isinstance(d["evidence"], list) or not isinstance(d["log"], list):
        raise ValueError("invalid snapshot history")
    session.phase, session.round, session.index = d["phase"], d["round"], d["index"]
    session.resaid, session.card, session.state = d["resaid"], d["card"], state
    session.evidence = [Evidence(**e) for e in d["evidence"]]
    labels = {"repeated", "independent", "cued", "corrected_repeated", "modelled_repeated", "needs_turn", "skipped"}
    for e in session.evidence:
        if e.phase not in {"opening", "guided", "recall"} or e.label not in labels:
            raise ValueError("invalid evidence phase/label")
        if type(e.round) is not int or e.round not in {0, 1, 2} or (e.phase != "guided" and e.round != 0):
            raise ValueError("invalid evidence round")
        rows = {"opening": lesson.opening, "guided": session.model_items if e.round == 0 else lesson.steps, "recall": lesson.recall}
        if type(e.number) is not int or not 1 <= e.number <= len(rows[e.phase]):
            raise ValueError("invalid evidence position")
        if type(e.attempts) is not int or e.attempts < 0 or not isinstance(e.learner, str) or not isinstance(e.target, str):
            raise ValueError("invalid evidence result")
        if (e.source_id, e.course_id, e.lesson_id) != (lesson.source_id, lesson.course_id, lesson.lesson_id):
            raise ValueError("evidence does not match pinned lesson")
        n = e.number - 1
        expected = lesson.opening_item_ids[n] if e.phase == "opening" else (
            list(dict.fromkeys(s.target_item_ids[0] for s in lesson.steps))[n] if e.phase == "guided" and e.round == 0
            else (lesson.steps if e.phase == "guided" else lesson.recall)[n].target_item_ids[0])
        if e.item_id != expected:
            raise ValueError("evidence does not match pinned item")
    session.log = d["log"]
    return session
