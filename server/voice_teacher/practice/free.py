"""Engine-owned, bounded free dialogue; generated text has no control authority."""
from copy import deepcopy
from dataclasses import dataclass, asdict

from schemas.validate import canonical_json
from ..providers.dialogue import DialogueReply, provider_identity, validate_context
from .profiles import UKRAINIAN
from .session import Say
from .state import _hash, _copy
from .text import normalise, plain


@dataclass(frozen=True)
class FreePolicy:
    language: str = "uk"
    instruction_language: str = "en"
    opening: str = "Поговорімо. Що вас цікавить у цій темі?"
    paused: str = "Conversation paused. Continue when you are ready."
    limit_message: str = "This short conversation is saved. Finish now, or start another conversation later."
    stop_phrases: tuple[str, ...] = ("стоп", "досить", "закінчимо", "закінчімо", "stop", "finish", "стоп будь ласка", "досить дякую", "закінчимо будь ласка", "stop please", "please stop", "finish please")
    pause_phrases: tuple[str, ...] = ("пауза", "pause", "пауза будь ласка", "pause please", "please pause")
    max_turns: int = 12

    def validate(self):
        if type(self.max_turns) is not int or not 1 <= self.max_turns <= 30:
            raise ValueError("invalid conversation turn limit")
        for value in [self.opening, self.paused, self.limit_message]:
            if not isinstance(value, str) or not value.strip() or len(value) > 1200: raise ValueError("invalid conversation policy text")
        for phrases in [self.stop_phrases, self.pause_phrases]:
            if not isinstance(phrases, tuple) or not 1 <= len(phrases) <= 16 or any(not isinstance(t, str) or not t.strip() or len(t) > 80 for t in phrases):
                raise ValueError("invalid conversation controls")
        if set(self.stop_phrases) & set(self.pause_phrases): raise ValueError("ambiguous conversation controls")

    @classmethod
    def from_dict(cls, value):
        data = deepcopy(value)
        for key in ["stop_phrases", "pause_phrases"]:
            if not isinstance(data[key], (list, tuple)): raise ValueError("conversation controls must be a list")
            data[key] = tuple(data[key])
        policy = cls(**data); policy.validate(); return policy


@dataclass
class FreePlan:
    source: dict | None
    course_id: str | None
    lesson_id: str | None
    language: str
    instruction_language: str
    topic: str
    learner_level: str
    grounding: dict
    correction_style: str
    provider: dict
    policy: dict

    def to_dict(self): return _copy(asdict(self))

    @classmethod
    def from_dict(cls, value):
        plan = cls(**deepcopy(value)); plan.validate(); return plan

    def validate(self):
        provider_identity(self.provider)
        policy = FreePolicy.from_dict(self.policy)
        if (self.language, self.instruction_language) != (policy.language, policy.instruction_language):
            raise ValueError("conversation policy language mismatch")
        if self.source is None and (self.course_id is not None or self.lesson_id is not None):
            raise ValueError("source-free conversation cannot identify a course")
        if self.source is not None and (self.source["course_id"], self.source["lesson_id"]) != (self.course_id, self.lesson_id):
            raise ValueError("conversation source mismatch")
        if self.topic != self.grounding.get("topic"): raise ValueError("conversation topic mismatch")
        validate_context({"language": self.language, "instruction_language": self.instruction_language,
            "correction_style": self.correction_style, "learner_profile": {"level": self.learner_level},
            "curriculum": self.grounding, "history": [], "learner_turn": "validate"})


def plan_free(source, course_id, lesson_id, *, topic, learner_level, provider, policy=None, correction_style="light_immediate"):
    policy = policy or FreePolicy(); policy.validate()
    reference = None
    grounding = {"topic": topic, "lesson_title": "", "goals": []}
    if source is not None:
        lesson = source.lesson(course_id, lesson_id)
        course = next(c for c in source.curriculum["courses"] if c["course_id"] == course_id)
        if "free_conversation" not in lesson["modes"] or (course["language"], course["instruction_language"]) != (policy.language, policy.instruction_language):
            raise ValueError("lesson has no available free conversation grounding")
        reference = source.source_ref(course_id, lesson_id)
        grounding = {"topic": topic or lesson["topic"], "lesson_title": lesson["title"][:200],
            "goals": [s["goal"][:300] for s in lesson["guided_steps"][:6]]}
    plan = FreePlan(reference, course_id, lesson_id, policy.language, policy.instruction_language, grounding["topic"],
        learner_level, grounding, correction_style, provider_identity(provider), _copy(asdict(policy)))
    plan.validate(); return plan


class FreeSession:
    def __init__(self, plan, dialogue, *, profile=UKRAINIAN, clock=None):
        plan.validate()
        if (plan.language, plan.instruction_language) != (profile.language, profile.instruction_language):
            raise ValueError("conversation language/profile mismatch")
        self.lesson, self.profile, self.dialogue = deepcopy(plan), profile, dialogue
        self.policy = FreePolicy.from_dict(plan.policy)
        if {normalise(t, profile) for t in self.policy.stop_phrases} & {normalise(t, profile) for t in self.policy.pause_phrases}:
            raise ValueError("ambiguous normalized conversation controls")
        self.phase, self.turns, self.history, self.decisions, self.last_teacher = "new", 0, [], [], []

    @property
    def done(self): return self.phase == "closed"
    @property
    def paused(self): return self.phase == "paused"
    @property
    def card(self): return None
    @property
    def evidence(self): return []  # T21 adds supported observations, never course completion.
    @property
    def assistance(self): return {"kind": "none", "help_level": 0, "target_exposed": False}

    def _say(self, *texts, kind="reply"):
        says = [Say(t, kind, plain(t, self.profile)) for t in texts]
        self.last_teacher = [asdict(s) for s in says]
        return says

    def start(self):
        if self.phase != "new": raise RuntimeError("conversation already started")
        self.phase = "active"
        self.history = [{"role": "teacher", "text": self.policy.opening}]
        return self._say(self.policy.opening, kind="intro")

    def context(self, text):
        recent, size = [], 0
        for row in reversed(self.history):
            if len(recent) == 8 or size + len(row["text"]) > 12000: break
            recent.append(deepcopy(row)); size += len(row["text"])
        context = {"language": self.lesson.language, "instruction_language": self.lesson.instruction_language,
            "correction_style": self.lesson.correction_style, "learner_profile": {"level": self.lesson.learner_level},
            "curriculum": deepcopy(self.lesson.grounding), "history": list(reversed(recent)), "learner_turn": text}
        validate_context(context); return context

    def hear(self, text):
        if self.phase != "active": raise RuntimeError("conversation is not active")
        if not isinstance(text, str) or not text.strip() or len(text) > 8000: raise ValueError("invalid conversation turn")
        heard = normalise(text, self.profile)
        if heard in {normalise(t, self.profile) for t in self.policy.stop_phrases}: return self.stop()
        if heard in {normalise(t, self.profile) for t in self.policy.pause_phrases}:
            self.phase = "paused"
            return self._say(self.policy.paused, kind="prompt")
        result = self.dialogue(self.context(text))
        if not isinstance(result, DialogueReply): raise ValueError("invalid dialogue result")
        self.history.extend([{"role": "learner", "text": text}, {"role": "teacher", "text": result.text}])
        self.decisions.append(asdict(result)); self.turns += 1
        if self.turns == self.policy.max_turns:
            self.phase = "paused"
            return self._say(result.text, self.policy.limit_message)
        return self._say(result.text)

    def stop(self):
        if self.done: return []
        self.phase = "closed"
        return self._say(self.profile.closing, kind="close")

    def pause(self):
        if self.phase != "active": raise ValueError("conversation cannot pause")
        self.phase = "paused"
        return []

    def resume(self):
        if self.phase != "paused" or self.turns >= self.policy.max_turns:
            raise ValueError("conversation cannot resume beyond its turn limit")
        self.phase = "active"
        return self._say(self.history[-1]["text"], kind="intro" if self.turns == 0 else "reply")

    def snapshot(self):
        return _copy({"format_version": 1, "data": {"plan_hash": _hash(self.lesson.to_dict()), "profile_hash": _hash(asdict(self.profile)),
            "phase": self.phase, "turns": self.turns, "history": self.history, "decisions": self.decisions, "last_teacher": self.last_teacher}})

    @classmethod
    def from_snapshot(cls, plan, dialogue, saved, *, profile=UKRAINIAN, clock=None):
        saved = _copy(saved)
        if not isinstance(saved, dict) or set(saved) != {"format_version", "data"} or type(saved["format_version"]) is not int or saved["format_version"] != 1:
            raise ValueError("unsupported free conversation snapshot")
        d = saved["data"]
        if set(d) != {"plan_hash", "profile_hash", "phase", "turns", "history", "decisions", "last_teacher"} or d["plan_hash"] != _hash(plan.to_dict()) or d["profile_hash"] != _hash(asdict(profile)):
            raise ValueError("conversation snapshot does not match pinned inputs")
        engine = cls(plan, dialogue, profile=profile, clock=clock)
        if d["phase"] not in {"active", "paused", "closed"} or type(d["turns"]) is not int or not 0 <= d["turns"] <= engine.policy.max_turns:
            raise ValueError("invalid conversation position")
        if d["turns"] == engine.policy.max_turns and d["phase"] == "active": raise ValueError("conversation exceeds turn limit")
        if not isinstance(d["history"], list) or len(d["history"]) != d["turns"] * 2 + 1 or d["history"][0] != {"role": "teacher", "text": engine.policy.opening}:
            raise ValueError("invalid conversation history")
        for n, row in enumerate(d["history"]):
            role = "teacher" if n % 2 == 0 else "learner"
            if not isinstance(row, dict) or set(row) != {"role", "text"} or row["role"] != role or not isinstance(row["text"], str) or not row["text"].strip() or len(row["text"]) > (1200 if role == "teacher" else 8000):
                raise ValueError("invalid conversation history row")
        if not isinstance(d["decisions"], list) or len(d["decisions"]) != d["turns"]: raise ValueError("invalid dialogue decisions")
        for n, value in enumerate(d["decisions"]):
            reply = DialogueReply(**value)
            if reply.text != d["history"][n * 2 + 2]["text"]: raise ValueError("dialogue decision/history mismatch")
        if not isinstance(d["last_teacher"], list) or not 1 <= len(d["last_teacher"]) <= 2: raise ValueError("invalid conversation presentation")
        for row in d["last_teacher"]:
            if set(row) != {"text", "kind", "display"} or not all(isinstance(v, str) for v in row.values()) or row["kind"] not in {"intro", "reply", "prompt", "close"} or len(row["text"]) > 1200 or row["display"] != plain(row["text"], profile):
                raise ValueError("invalid saved teacher presentation")
        expected = ([profile.closing] if d["phase"] == "closed" else
                    [d["history"][-1]["text"], engine.policy.limit_message] if d["turns"] == engine.policy.max_turns else
                    [d["history"][-1]["text"]])
        texts = [r["text"] for r in d["last_teacher"]]
        if texts != expected and not (d["phase"] == "paused" and d["turns"] < engine.policy.max_turns and texts == [engine.policy.paused]):
            raise ValueError("conversation presentation/history mismatch")
        engine.phase, engine.turns, engine.history, engine.decisions, engine.last_teacher = d["phase"], d["turns"], d["history"], d["decisions"], d["last_teacher"]
        return engine
