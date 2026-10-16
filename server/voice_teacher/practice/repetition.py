"""Short, independently planned repetition and optional recall before modelling."""
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
import json

from jsonschema import Draft202012Validator
from schemas.validate import REGISTRY, SCHEMAS, canonical_json
from ..providers import Item
from ..storage.sqlite import _id
from .profiles import UKRAINIAN
from .session import Say, Evidence, repeats, wants_to_stop
from .state import _copy, _hash
from .text import plain, normalise


@dataclass
class RepetitionPlan:
    source_id: str
    course_id: str
    lesson_id: str
    title: str
    language: str
    instruction_language: str
    targets: list[dict]
    recall_before_model: bool = False

    def to_dict(self): return deepcopy(asdict(self))

    @classmethod
    def from_dict(cls, value):
        plan = cls(**deepcopy(value)); plan.validate(); return plan

    def validate(self):
        for value in (self.source_id, self.course_id, self.lesson_id): _id(value)
        if type(self.recall_before_model) is not bool or not isinstance(self.targets, list) or not 1 <= len(self.targets) <= 6:
            raise ValueError("select one to six repetition items")
        seen = set()
        for target in self.targets:
            if not isinstance(target, dict) or set(target) != {"source", "item", "speech", "display", "meaning", "origin_session_id", "origin_turn_id", "queue_event_id"}:
                raise ValueError("invalid repetition target")
            for name, definition in [("source", "source_ref"), ("item", "item_ref")]:
                validator = Draft202012Validator({"$ref": SCHEMAS["common"]["$id"] + "#/$defs/" + definition}, registry=REGISTRY)
                if not validator.is_valid(target[name]): raise ValueError("invalid original item reference")
            if any(target["source"][k] != target["item"][k] for k in ("source_id", "course_id")):
                raise ValueError("original source/item mismatch")
            identity = canonical_json(target["item"])
            if identity in seen: raise ValueError("duplicate repetition item")
            seen.add(identity)
            if not all(isinstance(target[k], str) and target[k].strip() for k in ("speech", "display", "meaning")):
                raise ValueError("nonempty authored renderings required")
            if (target["origin_session_id"] is None) != (target["origin_turn_id"] is None):
                raise ValueError("incomplete original turn reference")
            for k in ("origin_session_id", "origin_turn_id", "queue_event_id"):
                if target[k] is not None: _id(target[k])


def _target(source, item, *, origin_session_id=None, origin_turn_id=None, queue_event_id=None):
    return {"source": deepcopy(source), "item": {"source_id": source["source_id"], "course_id": source["course_id"],
            "item_id": item["item_id"], "item_revision": item["item_revision"]},
            "speech": item["text"]["speech"], "display": item["text"]["display"], "meaning": item["meaning"],
            "origin_session_id": origin_session_id, "origin_turn_id": origin_turn_id, "queue_event_id": queue_event_id}


def plan_lesson(source, course_id, lesson_id, *, item_ids=None, limit=6, recall_before_model=False):
    """Read only the canonical repetition capability; no invented guided phases."""
    lesson = source.lesson(course_id, lesson_id)
    if "repetition" not in lesson["modes"]: raise ValueError("lesson does not offer repetition")
    if type(limit) is not int or not 1 <= limit <= 6: raise ValueError("invalid short-set limit")
    allowed = lesson["repetition_item_ids"]
    selected = list(allowed[:limit]) if item_ids is None else list(item_ids)
    if not selected or len(selected) > limit or len(set(selected)) != len(selected) or any(i not in allowed for i in selected):
        raise ValueError("select only authored repetition items")
    course = next(c for c in source.curriculum["courses"] if c["course_id"] == course_id)
    items = {i["item_id"]: i for i in course["items"]}
    plan = RepetitionPlan(source.curriculum["source_id"], course_id, lesson_id, lesson["title"], course["language"],
        course["instruction_language"], [_target(source.source_ref(course_id, lesson_id), items[i]) for i in selected], recall_before_model)
    plan.validate(); return plan


class RepetitionSession:
    def __init__(self, lesson, judge, *, profile=UKRAINIAN, clock=None):
        lesson.validate()
        if (lesson.language, lesson.instruction_language) != (profile.language, profile.instruction_language):
            raise ValueError("repetition language/profile mismatch")
        if lesson.recall_before_model:
            for target in lesson.targets:
                answer = " " + normalise(target["speech"], profile) + " "
                prompt = " " + normalise(profile.turn_card.format(task=target["meaning"]), profile) + " "
                if answer.strip() and answer in prompt: raise ValueError("recall prompt includes the authored answer; use repetition or revise the prompt")
        self.lesson, self.profile, self.judge = deepcopy(lesson), profile, judge
        self.phase, self.index, self.retries, self.evidence = "new", 0, 0, []

    @property
    def done(self): return self.phase == "closed"

    @property
    def card(self):
        if self.phase == "repeat": return self.profile.opening_card
        if self.phase == "recall": return plain(self.profile.turn_card.format(task=self.lesson.targets[self.index]["meaning"]), self.profile)
        return None

    @property
    def assistance(self):
        model = self.phase == "repeat"
        return {"kind": "model" if model else "task_card", "help_level": 2 if model else 0, "target_exposed": model}

    def _render(self, says):
        for say in says: say.display = plain(say.text, self.profile)
        return says

    def _begin(self):
        self.retries = 0
        self.phase = "recall" if self.lesson.recall_before_model else "repeat"
        return self.present()

    def present(self):
        if self.phase not in {"recall", "repeat"}: return []
        return self._render([Say(self.card, "prompt")] if self.phase == "recall" else [Say(self.lesson.targets[self.index]["speech"], "model")])

    def start(self):
        if self.phase != "new": raise ValueError("repetition already started")
        says = self._begin()
        return self._render([Say(self.profile.listen, "intro")]) + says if self.phase == "repeat" else says

    def stop(self):
        if self.done: return []
        self.phase, self.retries = "closed", 0
        return self._render([Say(self.profile.closing, "close")])

    def hear(self, text):
        if self.phase not in {"recall", "repeat"}: raise ValueError("repetition is not active")
        if not isinstance(text, str) or not text.strip(): raise ValueError("nonempty attempt required")
        target = self.lesson.targets[self.index]
        heard = normalise(text, self.profile)
        if wants_to_stop(text, self.profile) and len(heard.split()) == 1 and heard != normalise(target["speech"], self.profile):
            return self.stop()
        if self.phase == "recall":
            result = self.judge(Item("recall", self.card, target["meaning"], [target["speech"]]), text)
            if result.verdict.verdict == "accept" and result.verdict.on_task:
                return self._finish(text, "independent")
            # Once the model is supplied, a subsequent match can only be repeated.
            self.phase = "repeat"
            return self._render([Say(target["speech"], "model")])
        if repeats(target["speech"], text, self.profile): return self._finish(text, "repeated")
        if self.retries == 0:
            self.retries = 1
            return self._render([Say(target["speech"], "repeat")])
        return self._finish(text, "needs_turn")

    def _finish(self, text, label):
        target = self.lesson.targets[self.index]
        self.evidence.append(Evidence(self.phase, 0, self.index + 1, label, self.retries, text, target["speech"],
            target["item"]["source_id"], target["item"]["course_id"], target["source"]["lesson_id"], target["item"]["item_id"]))
        self.index += 1
        return self.stop() if self.index == len(self.lesson.targets) else self._begin()

    def snapshot(self):
        return _copy({"format_version": 1, "data": {"plan_hash": _hash(self.lesson.to_dict()), "profile_hash": _hash(asdict(self.profile)),
            "phase": self.phase, "index": self.index, "retries": self.retries, "evidence": [asdict(e) for e in self.evidence]}})

    @classmethod
    def from_snapshot(cls, lesson, judge, saved, *, profile=UKRAINIAN, clock=None):
        saved = _copy(saved)
        if not isinstance(saved, dict) or set(saved) != {"format_version", "data"} or type(saved["format_version"]) is not int or saved["format_version"] != 1:
            raise ValueError("unsupported repetition snapshot")
        d = saved["data"]
        if not isinstance(d, dict) or set(d) != {"plan_hash", "profile_hash", "phase", "index", "retries", "evidence"}:
            raise ValueError("invalid repetition snapshot fields")
        if d["plan_hash"] != _hash(lesson.to_dict()) or d["profile_hash"] != _hash(asdict(profile)):
            raise ValueError("repetition snapshot does not match pinned inputs")
        if d["phase"] not in {"new", "recall", "repeat", "closed"} or type(d["index"]) is not int or not 0 <= d["index"] <= len(lesson.targets):
            raise ValueError("invalid repetition position")
        if d["phase"] == "recall" and not lesson.recall_before_model: raise ValueError("recall was not selected")
        if type(d["retries"]) is not int or d["retries"] not in {0, 1} or (d["phase"] in {"new", "recall", "closed"} and d["retries"] != 0):
            raise ValueError("invalid repetition retries")
        if (d["phase"] in {"recall", "repeat"} and d["index"] == len(lesson.targets)) or (d["phase"] == "new" and d["index"] != 0):
            raise ValueError("repetition phase/position mismatch")
        engine = cls(lesson, judge, profile=profile, clock=clock)
        engine.phase, engine.index, engine.retries = d["phase"], d["index"], d["retries"]
        if not isinstance(d["evidence"], list) or len(d["evidence"]) != engine.index: raise ValueError("invalid repetition history")
        for number, value in enumerate(d["evidence"], 1):
            e = Evidence(**value); t = lesson.targets[number - 1]
            if type(e.number) is not int or type(e.round) is not int or e.number != number or e.round != 0 or e.label not in {"independent", "repeated", "needs_turn"} or e.phase not in {"recall", "repeat"}:
                raise ValueError("invalid repetition evidence")
            if (e.label == "independent") != (e.phase == "recall") or (e.phase == "recall" and not lesson.recall_before_model):
                raise ValueError("invalid recall evidence")
            if type(e.attempts) is not int or e.attempts not in {0, 1} or (e.phase == "recall" and e.attempts != 0) or (e.label == "needs_turn" and e.attempts != 1) or not isinstance(e.learner, str) or not e.learner.strip():
                raise ValueError("invalid repetition attempt")
            if (e.source_id, e.course_id, e.lesson_id, e.item_id, e.target) != (t["item"]["source_id"], t["item"]["course_id"], t["source"]["lesson_id"], t["item"]["item_id"], t["speech"]):
                raise ValueError("repetition evidence does not match pinned item")
            engine.evidence.append(e)
        return engine


WEAK = {"needs_turn", "skipped", "cued", "corrected_repeated", "modelled_repeated"}


def _history(store, learner):
    with store._connection() as c:
        events = [json.loads(r[0]) for r in c.execute("SELECT body_json FROM events WHERE learner_id=?", (_id(learner),))]
        snapshots = [json.loads(r[0]) for r in c.execute("SELECT snapshot_json FROM sessions WHERE learner_id=?", (learner,))]
    return events, snapshots


def weak_queue(store, learner):
    """Private candidate IDs from latest supported outcomes, excluding disputes."""
    events, snapshots = _history(store, learner)
    superseded = {e["supersedes_event_id"] for e in events if e["supersedes_event_id"]}
    disputed = {(s["session_id"], r["origin_turn_id"]) for s in snapshots
        for r in s["engine_state"]["data"].get("recognition_reports", {}).values() if r.get("origin_turn_id")}
    latest = {}
    for e in sorted(events, key=lambda e: (datetime.fromisoformat(e["occurred_at"]).timestamp(), e["session_id"], e["sequence"])):
        if e["event_type"] != "evidence.recorded" or e["provenance"]["original_item"] is None: continue
        if e["event_id"] in superseded or (e["session_id"], e["turn"]["turn_id"]) in disputed or e["evidence"]["recognition_uncertain"]: continue
        key = canonical_json(e["provenance"]["original_item"])
        outcome = e["evidence"]["outcome"]
        if outcome in WEAK: latest[key] = e
        elif outcome == "independent": latest.pop(key, None)
        # Hearing and repeating alone does not retire an existing weak target.
    return [e["event_id"] for e in latest.values()]


def plan_queue(store, learner, source, course_id, lesson_id, event_ids, *, recall_before_model=False):
    # The selected source/lesson supplies current practice provenance, not a new
    # identity for an older target. Only learner-owned active queue IDs are accepted.
    base = plan_lesson(source, course_id, lesson_id, limit=1, recall_before_model=recall_before_model)
    if not isinstance(event_ids, list) or not 1 <= len(event_ids) <= 2 or len(set(event_ids)) != len(event_ids):
        raise ValueError("select one or two private queue items")
    allowed = set(weak_queue(store, learner))
    if any(identity not in allowed for identity in event_ids): raise ValueError("item is not in this learner's active weak queue")
    events, _ = _history(store, learner)
    by_id = {e["event_id"]: e for e in events}
    targets = []
    for identity in event_ids:
        event = by_id[identity]; original = event["provenance"]; ref = original["original_item"]
        candidates = [e["snapshot"] for e in events if e["event_type"] == "state.saved" and e["source"] == original["original_source"]]
        if not candidates: raise ValueError("original source snapshot is unavailable")
        curriculum = candidates[-1]["curriculum_snapshot"]
        course = next(c for c in curriculum["courses"] if c["course_id"] == ref["course_id"])
        if (course["language"], course["instruction_language"]) != (base.language, base.instruction_language):
            raise ValueError("queued item language does not match current practice")
        item = next((i for i in course["items"] if (i["item_id"], i["item_revision"]) == (ref["item_id"], ref["item_revision"])), None)
        if item is None: raise ValueError("original item revision is unavailable")
        targets.append(_target(original["original_source"], item, origin_session_id=original["origin_session_id"], origin_turn_id=original["origin_turn_id"], queue_event_id=identity))
    base.targets = targets; base.validate(); return base



def validate_plan(store, template, plan):
    """Recompile selected targets from owned history/pinned content before save."""
    from ..content.registry import SourceSnapshot
    source = template["source"]
    if template["mode"] != "repetition" or source is None: raise ValueError("repetition needs a pinned source")
    frozen = SourceSnapshot("pinned", canonical_json({"curriculum": template["curriculum_snapshot"], "provenance": source["revision"]}))
    queued = [t["queue_event_id"] for t in plan.targets]
    from .personal_review import source_id, compile_plan
    if any(queued) and source["source_id"] == source_id(template["learner_id"]):
        private_source, expected = compile_plan(store, template["learner_id"], queued, recall_before_model=plan.recall_before_model)
        if private_source.source_ref("personal-review","personal-set") != source or private_source.curriculum != template["curriculum_snapshot"]:
            raise ValueError("personal review snapshot changed")
    elif any(queued):
        if not all(queued): raise ValueError("select a lesson set or a queued set")
        expected = plan_queue(store, template["learner_id"], frozen, source["course_id"], source["lesson_id"], queued, recall_before_model=plan.recall_before_model)
    else:
        expected = plan_lesson(frozen, source["course_id"], source["lesson_id"], item_ids=[t["item"]["item_id"] for t in plan.targets], recall_before_model=plan.recall_before_model)
    if plan.to_dict() != expected.to_dict(): raise ValueError("repetition plan does not match pinned content/owned queue")
