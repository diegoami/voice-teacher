"""Bounded guided activities built from pinned curriculum, with no dialogue model.

Curriculum remains data. Before an attempt only the authored teacher line and
communicative goal are presented. Hidden renderings enter only the post-attempt
judge, explicit cue/correction, or the optional combined modelling routine.
"""
from copy import deepcopy
from dataclasses import dataclass, asdict
import time

from .models import Lesson, Step, RecallPrompt
from .profiles import UKRAINIAN
from .session import Session, Say, ItemState
from .state import _hash, _copy
from .text import contains_answer


ACTIVITY_END_EN = "Activity complete. Take a break, or continue when you are ready."


@dataclass
class GuidedLesson(Lesson):
    routine: str = "guided"
    cards: bool = True
    spoken_tasks: bool = True

    def validate(self):
        super().validate(require_combined=False)
        if (not self.steps and not self.recall and not (self.routine == "combined" and self.opening)) or self.routine not in {"guided", "combined"}:
            raise ValueError("guided activities require content and a supported routine")
        if type(self.cards) is not bool or type(self.spoken_tasks) is not bool:
            raise ValueError("guided presentation settings must be booleans")


class ActivitySession(Session):
    def start(self):
        if self.phase != "new": raise RuntimeError("activity already started")
        if self.part == "2" and not self.lesson.steps:
            self.phase, self.round, self.index = "recall", 0, 0
            return self._teacher([Say(self.profile.recall, "intro")] + self._begin_item())
        if self.part == "2": return super().start()
        if self.lesson.routine == "combined" and self.lesson.opening: return super().start()
        self.phase, self.index = "guided", 0
        self.round = 0 if self.lesson.routine == "combined" else 1
        return self._teacher(([Say(self.profile.new_sentences, "transition")] + self._repeat_line(0))
            if self.round == 0 else [Say(self.profile.start_talk, "intro")] + self._begin_item())

    def _begin_item(self):
        if self.phase != "guided": return super()._begin_item()
        self.state, self.card = ItemState(), None
        step = self.lesson.steps[self.index]
        says = [Say(step.teacher_line, "line")]
        if self.round == 1:
            task = step.expected[0].upper() + step.expected[1:] + "."
            if self.lesson.cards:
                self.card = self.profile.turn_card.format(task=task) + (self.profile.open_answer_card if step.open_answer else "")
            if self.lesson.spoken_tasks: says.append(Say(task, "task"))
        return says

    def present(self):
        # Replay exactly the last planned speech, including a cue or a model;
        # do not reset help or regenerate a goal after a manual pause.
        latest = next((e for e in reversed(self.log) if e["event"] == "teacher"), None)
        return [Say(**s) for s in latest["says"]] if latest else []


@dataclass
class GuidedPlan:
    source: dict
    course_id: str
    lesson_id: str
    title: str
    language: str
    instruction_language: str
    routine: str
    cards: bool
    spoken_tasks: bool
    max_goals: int
    sitting: str
    activity_end: str
    activities: list[dict]

    def to_dict(self): return asdict(self)

    @classmethod
    def from_dict(cls, value):
        plan = cls(**deepcopy(value)); plan.validate(); return plan

    def validate(self):
        if self.routine not in {"guided", "combined"} or self.sitting not in {"combined", "first_sitting", "second_sitting"}:
            raise ValueError("unsupported guided plan")
        if type(self.max_goals) is not int or not 1 <= self.max_goals <= 6 or not self.activities:
            raise ValueError("invalid guided activity size")
        if not isinstance(self.activity_end, str) or not self.activity_end.strip(): raise ValueError("activity closing required")
        identities = set()
        for a in self.activities:
            if set(a) != {"activity_id", "part", "lesson"} or a["part"] not in {"1", "2"} or a["activity_id"] in identities:
                raise ValueError("invalid activity descriptor")
            identities.add(a["activity_id"])
            lesson = GuidedLesson.from_dict(a["lesson"])
            if (lesson.source_id, lesson.course_id, lesson.lesson_id, lesson.language, lesson.instruction_language,
                lesson.routine, lesson.cards, lesson.spoken_tasks) != (self.source["source_id"], self.course_id, self.lesson_id,
                self.language, self.instruction_language, self.routine, self.cards, self.spoken_tasks):
                raise ValueError("activity does not match guided plan")
            if len(lesson.steps) > self.max_goals or len(lesson.recall) > self.max_goals or len(lesson.opening) > 6: raise ValueError("activity exceeds planned goals")


def plan_guided(source, course_id, lesson_id, *, routine="guided", cards=True, spoken_tasks=True,
                max_goals=3, sitting="combined", activity_end=None):
    if routine not in {"guided", "combined"} or sitting not in {"combined", "first_sitting", "second_sitting"}:
        raise ValueError("unsupported guided routine")
    if type(max_goals) is not int or not 1 <= max_goals <= 6 or type(cards) is not bool or type(spoken_tasks) is not bool:
        raise ValueError("invalid guided settings")
    lesson = source.lesson(course_id, lesson_id)
    course = next(c for c in source.curriculum["courses"] if c["course_id"] == course_id)
    if "guided_conversation" not in lesson["modes"] or not lesson["guided_steps"]:
        raise ValueError("lesson has no authored guided scenario")
    if routine == "combined" and ("repetition" not in lesson["modes"] or not lesson["repetition_item_ids"]):
        raise ValueError("combined routine needs authored repetition")
    if activity_end is None:
        if course["instruction_language"] != "en": raise ValueError("configured activity closing needed for instruction language")
        activity_end = ACTIVITY_END_EN
    items = {i["item_id"]: i for i in course["items"]}
    steps = [Step(n, s["step_id"], s["teacher"]["speech"], s["goal"],
                  [items[i]["text"]["speech"] for i in s["target_item_ids"]], s["target_item_ids"], open_answer=s.get("open_answer", False))
             for n, s in enumerate(lesson["guided_steps"], 1)]
    recalls = [RecallPrompt(n, r["goal_id"], r["prompt"]["speech"],
                    [items[i]["text"]["speech"] for i in r["target_item_ids"]], r["target_item_ids"])
               for n, r in enumerate(lesson["recall_goals"], 1)]
    # Source text cannot turn a hidden answer into an uncredited task/model.
    for row in [*steps, *recalls]:
        prompt = (row.teacher_line + " " + row.expected) if isinstance(row, Step) else row.prompt
        for target in row.targets:
            if contains_answer(prompt, target):
                raise ValueError("guided prompt includes a hidden answer")
    chunks = [steps[i:i + max_goals] for i in range(0, len(steps), max_goals)]
    # Recall stays delayed until both sittings have practised all scenario goals.
    activities = []
    if routine == "combined" and sitting != "second_sitting":
        review = lesson["repetition_item_ids"]
        for n in range(0, len(review), 6):
            ids = review[n:n + 6]
            opening = GuidedLesson(source.curriculum["source_id"], course_id, lesson_id, lesson["title"], "",
                [items[i]["text"]["speech"] for i in ids], ids, [], [], course["language"], course["instruction_language"],
                activity_end, routine, cards, spoken_tasks)
            opening.validate()
            activities.append({"activity_id": f"opening-block-{n // 6 + 1}", "part": "1", "lesson": opening.to_dict()})
    for part in ["1", "2"]:
        if sitting == "first_sitting" and part != "1" or sitting == "second_sitting" and part != "2": continue
        for n, chunk in enumerate(chunks):
            native = GuidedLesson(source.curriculum["source_id"], course_id, lesson_id, lesson["title"], "", [], [],
                [Step(**{**asdict(s), "number": k}) for k, s in enumerate(chunk, 1)],
                [],
                course["language"], course["instruction_language"], activity_end,
                routine, cards, spoken_tasks)
            native.validate()
            activities.append({"activity_id": f"sitting-{part}-block-{n + 1}", "part": part, "lesson": native.to_dict()})
    if sitting != "first_sitting":
        for n in range(0, len(recalls), max_goals):
            native = GuidedLesson(source.curriculum["source_id"], course_id, lesson_id, lesson["title"], "", [], [], [],
                [RecallPrompt(**{**asdict(r), "number": k}) for k, r in enumerate(recalls[n:n + max_goals], 1)],
                course["language"], course["instruction_language"], activity_end, routine, cards, spoken_tasks)
            native.validate()
            activities.append({"activity_id": f"recall-block-{n // max_goals + 1}", "part": "2", "lesson": native.to_dict()})
    activities[-1]["lesson"]["closing"] = None
    plan = GuidedPlan(source.source_ref(course_id, lesson_id), course_id, lesson_id, lesson["title"],
        course["language"], course["instruction_language"], routine, cards, spoken_tasks, max_goals, sitting, activity_end, activities)
    plan.validate(); return plan


class GuidedSession:
    def __init__(self, plan, judge, *, profile=UKRAINIAN, clock=None):
        plan.validate()
        if (plan.language, plan.instruction_language) != (profile.language, profile.instruction_language):
            raise ValueError("guided plan does not match configured profile")
        self.lesson, self.profile, self.judge = deepcopy(plan), profile, judge
        self.clock = clock or time.monotonic
        self.index, self.completed, self.stopped = 0, [], False
        self.current = self._new()

    def _new(self):
        a = self.lesson.activities[self.index]
        return ActivitySession(GuidedLesson.from_dict(a["lesson"]), self.judge, part=a["part"], profile=self.profile, clock=self.clock)

    @property
    def done(self): return self.stopped or self.current.done and self.index == len(self.lesson.activities) - 1
    @property
    def boundary(self): return self.current.done and not self.done
    @property
    def card(self): return self.current.card
    @property
    def phase(self): return self.current.phase
    @property
    def round(self): return self.current.round
    @property
    def state(self): return self.current.state
    @property
    def evidence(self):
        return [e for native in self.completed for e in native.evidence] + self.current.evidence
    @property
    def activity(self):
        return {"activity_id": self.lesson.activities[self.index]["activity_id"], "position": self.index,
                "total": len(self.lesson.activities), "complete": self.current.done}
    @property
    def assistance(self):
        model = self.phase == "opening" or self.phase == "guided" and self.round == 0
        kind = "model" if model else self.state.help or ("task_card" if self.card else "none")
        return {"kind": kind, "help_level": 2 if kind == "model" else int(kind in {"cue", "correction"}),
                "target_exposed": model or kind in {"cue", "correction", "model"}}

    def start(self): return self.current.start()
    def hear(self, text):
        if self.done or self.boundary: raise RuntimeError("resume the next activity before accepting a turn")
        says = self.current.hear(text)
        if any(e["event"] == "stopped" for e in self.current.log):
            self.stopped = True
            return self.current._teacher([Say(self.profile.closing, "close")])
        return says
    def stop(self):
        if self.done: return []
        self.current.stop(); self.stopped = True
        return self.current._teacher([Say(self.profile.closing, "close")])
    def resume(self):
        if self.done: raise RuntimeError("guided session finished")
        if self.boundary:
            self.completed.append(self.current); self.index += 1; self.current = self._new()
            return self.current.start()
        return self.current.present()

    def snapshot(self):
        return _copy({"format_version": 1, "data": {"plan_hash": _hash(self.lesson.to_dict()),
            "profile_hash": _hash(asdict(self.profile)), "index": self.index, "stopped": self.stopped,
            "completed": [s.snapshot() for s in self.completed], "current": self.current.snapshot()}})

    @classmethod
    def from_snapshot(cls, plan, judge, saved, *, profile=UKRAINIAN, clock=None):
        saved = _copy(saved)
        if set(saved) != {"format_version", "data"} or type(saved["format_version"]) is not int or saved["format_version"] != 1:
            raise ValueError("unsupported guided snapshot")
        d = saved["data"]
        if set(d) != {"plan_hash", "profile_hash", "index", "stopped", "completed", "current"} or d["plan_hash"] != _hash(plan.to_dict()) or d["profile_hash"] != _hash(asdict(profile)):
            raise ValueError("guided snapshot does not match pinned inputs")
        if type(d["index"]) is not int or not 0 <= d["index"] < len(plan.activities) or type(d["stopped"]) is not bool or not isinstance(d["completed"], list) or len(d["completed"]) != d["index"]:
            raise ValueError("invalid guided position")
        engine = cls(plan, judge, profile=profile, clock=clock)
        def restore(n, state):
            a = plan.activities[n]
            s = ActivitySession.from_snapshot(GuidedLesson.from_dict(a["lesson"]), judge, state, profile=profile, clock=engine.clock)
            if s.part != a["part"]: raise ValueError("activity sitting mismatch")
            return s
        engine.completed = [restore(n, s) for n, s in enumerate(d["completed"])]
        if any(not s.done or any(e["event"] == "stopped" for e in s.log) for s in engine.completed):
            raise ValueError("incomplete previous guided activity")
        engine.index, engine.stopped = d["index"], d["stopped"]
        engine.current = restore(engine.index, d["current"])
        if engine.stopped and not engine.current.done: raise ValueError("stopped activity is active")
        return engine
