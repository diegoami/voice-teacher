"""Read-only learner views. Item practice coverage is deliberately not mastery."""
from collections import Counter
import json

from datetime import datetime
from ..storage.sqlite import _id

COVERED = frozenset({"independent", "repeated", "cued", "modelled_repeated", "corrected_repeated"})
CRITERION = "An item is covered by a supported repetition or guided attempt, including cued or modelled practice. This is material covered, not independent recall or mastery. Free conversation does not advance lesson coverage."


def _read(store, learner):
    learner = _id(learner)
    with store._connection() as c:
        c.execute("BEGIN")
        sessions = [json.loads(r[0]) for r in c.execute("SELECT snapshot_json FROM sessions WHERE learner_id=?", (learner,))]
        events = [json.loads(r[0]) for r in c.execute("SELECT body_json FROM events WHERE learner_id=? ORDER BY session_id,sequence", (learner,))]
        exported = {r[0] for r in c.execute("SELECT e.event_id FROM events e JOIN outbox o ON o.job_id=e.event_id WHERE e.learner_id=? AND o.status='done'", (learner,))}
    return sessions, events, exported


def _disputed(snapshots):
    return {(s["session_id"],r["origin_turn_id"]) for s in snapshots
            for r in s["engine_state"]["data"].get("recognition_reports",{}).values() if r.get("origin_turn_id")}


def _source_key(source):
    return (source["source_id"], source["course_id"], source["revision"]["content_sha256"])


def _active(events):
    superseded = {e["supersedes_event_id"] for e in events if e["supersedes_event_id"]}
    return [e for e in events if e["event_type"] == "evidence.recorded" and e["event_id"] not in superseded]


def summary(store, learner, *, progress_sync=None, limit=50):
    if type(limit) is not int or not 1 <= limit <= 100: raise ValueError("invalid history limit")
    if progress_sync is not None and progress_sync.store.path != store.path: raise ValueError("sync must use the same runtime store")
    sync_state, sync_error = None, None
    if progress_sync is not None:
        try: sync_state = progress_sync.status()
        except Exception: sync_error = "Sync status unavailable; local progress is retained."
    sessions, events, exported = _read(store, learner)
    pushed = {e["event_id"] for e in (sync_state or {}).get("events", []) if e["state"] == "pushed"}
    backup = {e["event_id"]: "pushed" if e["event_id"] in pushed else "exported" if e["event_id"] in exported else "locally_saved" for e in events}
    counts = Counter(backup.values())
    active = _active(events)
    disputed = _disputed(sessions)
    covered = set()
    for event in active:
        evidence, p = event["evidence"], event["provenance"]
        if event["mode"] == "free_conversation" or evidence["recognition_uncertain"] or (event["session_id"],event["turn"]["turn_id"]) in disputed or evidence["outcome"] not in COVERED: continue
        if p["original_source"] is None or p["original_item"] is None: continue
        item = p["original_item"]
        covered.add((*_source_key(p["original_source"]), item["item_id"], item["item_revision"]))
    from ..practice.personal_review import source_id as personal_source_id
    private_source = personal_source_id(learner)
    courses = {}
    for snapshot in sessions:
        source = snapshot["source"]
        if source is None or (source["source_id"] == private_source and source["course_id"] == "personal-review"): continue
        key = _source_key(source)
        if key in courses: continue
        course = next(c for c in snapshot["curriculum_snapshot"]["courses"] if c["course_id"] == source["course_id"])
        revisions = {i["item_id"]: i["item_revision"] for i in course["items"]}
        lessons, all_items, covered_items = [], set(), set()
        for lesson in course["lessons"]:
            required = set(lesson["repetition_item_ids"])
            for step in lesson["guided_steps"]: required.update(step["target_item_ids"])
            practiced = {i for i in required if (*key, i, revisions[i]) in covered}
            all_items.update(required); covered_items.update(practiced)
            lessons.append({"lesson_id": lesson["lesson_id"], "title": lesson["title"], "required_items": len(required),
                            "covered_items": len(practiced), "covered": bool(required) and practiced == required})
        next_lesson = next((l["lesson_id"] for l in lessons if not l["covered"]), None)
        courses[key] = {"source_id": source["source_id"], "course_id": source["course_id"], "content_sha256": key[2],
                        "title": course["title"], "required_items": len(all_items), "covered_items": len(covered_items),
                        "next_lesson_id": next_lesson, "lessons": lessons}
    by_session = {}
    for event in events: by_session.setdefault(event["session_id"], []).append(event)
    recent = []
    for snapshot in sessions:
        rows = by_session.get(snapshot["session_id"], [])
        source = snapshot["source"]
        title = snapshot["topic"] or "Free conversation"
        if source is not None:
            course = next(c for c in snapshot["curriculum_snapshot"]["courses"] if c["course_id"] == source["course_id"])
            title = next(l["title"] for l in course["lessons"] if l["lesson_id"] == source["lesson_id"])
        states = Counter(backup[e["event_id"]] for e in rows)
        recent.append({"session_id": snapshot["session_id"], "title": title, "mode": snapshot["mode"], "source": source,
                       "status": snapshot["status"], "updated_at": max((e["occurred_at"] for e in rows), default=""),
                       "accepted_turns": sum(e["event_type"] == "turn.accepted" for e in rows),
                       "locally_saved": states["locally_saved"], "exported": states["exported"], "pushed": states["pushed"]})
    recent.sort(key=lambda s: (datetime.fromisoformat(s["updated_at"]),s["session_id"]), reverse=True)
    return {"criterion": CRITERION, "courses": [courses[k] for k in sorted(courses)], "sessions": recent[:limit],
            "more_sessions": len(recent) > limit, "sync": {"configured": progress_sync is not None,
                "locally_saved": counts["locally_saved"], "exported": counts["exported"], "pushed": counts["pushed"],
                "last_push_at": (sync_state or {}).get("last_push_at") if counts["pushed"] else None,
                "error": sync_error or ("Sync failed; local progress is retained." if (sync_state or {}).get("error") else None)}}


def evidence(store, learner, session, *, offset=0, limit=50):
    learner, session = _id(learner), _id(session)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100: raise ValueError("invalid evidence page")
    with store._connection() as c:
        c.execute("BEGIN")
        if c.execute("SELECT 1 FROM sessions WHERE learner_id=? AND session_id=?", (learner, session)).fetchone() is None: raise KeyError("session not found")
        events = [json.loads(r[0]) for r in c.execute("SELECT body_json FROM events WHERE learner_id=? ORDER BY session_id,sequence", (learner,))]
        snapshots = [json.loads(r[0]) for r in c.execute("SELECT snapshot_json FROM sessions WHERE learner_id=?", (learner,))]
    disputed = _disputed(snapshots)
    turns = {(e["session_id"],e["turn"]["turn_id"]): e["turn"] for e in events if e["event_type"] == "turn.accepted"}
    superseded = {e["supersedes_event_id"] for e in events if e["supersedes_event_id"]}
    rows = [e for e in events if e["session_id"] == session and e["event_type"] == "evidence.recorded"]
    result = []
    for e in rows[offset:offset+limit]:
        value, p = e["evidence"], e["provenance"]
        turn = turns.get((session,e["turn"]["turn_id"]))
        if turn is None: raise ValueError("evidence has no accepted turn")
        uncertain = value["recognition_uncertain"] or (session,turn["turn_id"]) in disputed
        correction = bool(value["preferred"]) and (e["assistance"]["kind"] == "correction" or value["outcome"] == "corrected_repeated" or (value["outcome"] == "observed" and bool(value["reason"])))
        result.append({"event_id":e["event_id"], "session_id":session, "turn":turn, "outcome":value["outcome"],
                       "attempt":value["attempt"], "preferred":value["preferred"], "reason":value["reason"],
                       "recognition_uncertain":uncertain, "correction":correction and not uncertain,
                       "assistance":e["assistance"], "provenance":p, "superseded":e["event_id"] in superseded})
    return {"session_id":session,"rows":result,"next_offset":offset+limit if len(rows)>offset+limit else None}
