"""The lesson as a state machine that owns the turn loop.

Phases: opening (the earlier lesson's lines: listen and repeat, no model) →
round 0 (the new sentences of this lesson: listen and repeat, no model) →
round 1 of the guided sequence with a task card on screen → round 2 of the
same sequence without cards → delayed recall → close. In the two repeat
phases the screen says plainly to repeat and not to answer, since many lines
are questions. The engine writes every teacher line; the judge only
classifies the learner's turns (see judge.py).

Help on a step comes in stages: the task card (round 1 only), then either a
correction of the one important mistake or a partial cue, then the full
sentence to repeat. Evidence labels follow the learnukrainian tracker.
"""

from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import asdict, dataclass, field

from ..providers import Item, Judgement, Judge
from .profiles import UKRAINIAN, LanguageProfile
from .models import Lesson
from .text import normalise, plain

PARTS = ("all", "1", "2")
LISTEN = UKRAINIAN.listen
NEW_SENTENCES = UKRAINIAN.new_sentences
START_TALK = UKRAINIAN.start_talk
ROUND_TWO = UKRAINIAN.round_two
CONTINUE = UKRAINIAN.continue_talk
RECALL = UKRAINIAN.recall
REPEAT_PLEASE = UKRAINIAN.repeat_please
LISTENING = UKRAINIAN.listening
CORRECTION = UKRAINIAN.correction
OPENING_CARD = UKRAINIAN.opening_card
MODEL_CARD = UKRAINIAN.model_card

MAX_CHUNK_WORDS = 4
LOOK_AHEAD = 4  # later steps the judge may recognise when the learner runs ahead
STOP_WORDS = UKRAINIAN.stop_words


@dataclass
class Say:
    text: str
    kind: str  # intro, line, cue, correction, model, repeat, reply, prompt, transition, close
    display: str = ""


@dataclass
class Evidence:
    phase: str  # opening | guided | recall
    round: int  # 0 (repeat), 1 (task cards), 2 (no cards) for guided; 0 otherwise
    number: int  # line, step or prompt number
    label: str  # repeated | independent | cued | corrected_repeated | modelled_repeated | needs_turn | skipped
    attempts: int  # judged attempts that failed before the result
    learner: str  # the turn the label rests on
    target: str
    source_id: str = ""
    course_id: str = ""
    lesson_id: str = ""
    item_id: str = ""


def word_edits(a: list[str], b: list[str]) -> int:
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j - 1] + (x != y), previous[j] + 1, current[j - 1] + 1))
        previous = current
    return previous[-1]


def repeats(line: str, heard: str, profile: LanguageProfile = UKRAINIAN) -> bool:
    """A repetition, not an answer: at most one word in three changed, missing or added (at least one).

    Speech recognition drops and garbles a word here and there; an answer adds
    words («це коштує двадцять» for «Скільки це коштує?») and fails.
    """
    want, got = normalise(line, profile).split(), normalise(heard, profile).split()
    allowed = max(1, len(want) // 3)
    if word_edits(want, got) <= allowed:
        return True
    # The learner may repeat the teacher's instruction too («Тепер нові речення… Як краще…»): what counts
    # is that the turn ends with the line. An answer does not end with the question it answers.
    return any(word_edits(want, got[-n:]) <= allowed for n in range(max(1, len(want) - allowed), len(want) + allowed + 1)
               if n <= len(got))


def overlap(line: str, heard: str, profile: LanguageProfile = UKRAINIAN) -> float:
    want = normalise(line, profile).split()
    got = set(normalise(heard, profile).split())
    return sum(w in got for w in want) / len(want) if want else 1.0


@dataclass
class ItemState:
    attempts: int = 0  # failed judged attempts
    help: str = ""  # "", cue, correction, model
    unclear: int = 0
    awaiting_repeat: bool = False
    repeat_tries: int = 0
    history: list[tuple[str, str]] = field(default_factory=list)


class Session:
    def __init__(self, lesson: Lesson, judge: Judge, clock=time.monotonic, part: str = "all",
                 profile: LanguageProfile = UKRAINIAN):
        if part not in PARTS:
            raise ValueError(f"part must be one of {PARTS}, not {part!r}")
        lesson.validate()
        if (lesson.language, lesson.instruction_language) != (profile.language, profile.instruction_language):
            raise ValueError("lesson languages do not match the language profile")
        self.profile = profile
        self.part = part  # "1": opening, round 0, round 1; "2": round 2 and recall
        self.lesson = deepcopy(lesson)
        self.judge = judge
        self.clock = clock
        self.phase = "new"  # new, opening, guided, recall, closed
        self.model_items = round_zero(lesson, profile)  # (sentence, task) pairs for round 0
        self.round = 0
        self.index = 0  # opening line, step or recall prompt (0-based)
        self.resaid = False
        self.state = ItemState()
        self.card: str | None = None
        self.evidence: list[Evidence] = []
        self.log: list[dict] = []

    # --- public -----------------------------------------------------------

    @property
    def done(self) -> bool:
        return self.phase == "closed"

    def start(self) -> list[Say]:
        if self.phase != "new":
            raise RuntimeError("the lesson has already started")
        if self.part == "2":
            self.phase, self.round, self.index = "guided", 2, 0
            return self._teacher([Say(self.profile.continue_talk, "intro")] + self._begin_item())
        self.phase = "opening"
        self.card = self.profile.opening_card
        return self._teacher([Say(self.lesson.introduction + " " + self.profile.listen, "intro"),
                              Say(self.lesson.opening[0], "line")])

    def hear(self, text: str) -> list[Say]:
        if self.done:
            raise RuntimeError("the lesson is closed")
        if self.phase == "new":
            raise RuntimeError("start the lesson before accepting a turn")
        self._log("learner", text=text)
        if wants_to_stop(text, self.profile):
            return self.stop()
        if self.phase == "opening" or (self.phase == "guided" and self.round == 0):
            return self._teacher(self._opening(text))
        return self._teacher(self._answer(text))

    def stop(self) -> list[Say]:
        """Stop through an app control without inventing a learner transcript."""
        if self.done:
            return []
        self.phase, self.card = "closed", None
        self._log("stopped")
        return self._teacher([Say((self.lesson.closing or self.profile.closing), "close")])

    # --- opening ----------------------------------------------------------

    def _opening(self, text: str) -> list[Say]:
        """Listen and repeat: the opening review, then round 0. No model call."""
        lines = self.lesson.opening if self.phase == "opening" else [s for s, _ in self.model_items]
        line = lines[self.index]
        if not repeats(line, text, self.profile) and not self.resaid:
            self.resaid = True
            return [Say(line, "repeat")]
        label = "repeated" if repeats(line, text, self.profile) else "needs_turn"
        self._record_evidence(Evidence(self.phase, self.round, self.index + 1, label, int(self.resaid), text, line))
        self.index += 1
        self.resaid = False
        if self.index < len(lines):
            return self._repeat_line(self.index)
        if self.phase == "opening":
            self.phase, self.round, self.index = "guided", 0, 0
            return [Say(self.profile.new_sentences, "transition")] + self._repeat_line(0)
        self.round, self.index = 1, 0
        return [Say(self.profile.start_talk, "transition")] + self._begin_item()

    def _repeat_line(self, index: int) -> list[Say]:
        if self.phase == "opening":
            self.card = self.profile.opening_card
            return [Say(self.lesson.opening[index], "line")]
        sentence, task = self.model_items[index]
        self.card = self.profile.model_card.format(task=task)
        return [Say(sentence, "line")]

    # --- guided and recall ------------------------------------------------

    def _item(self) -> Item:
        if self.phase == "guided":
            step = self.lesson.steps[self.index]
            later = [(s.number, s.expected) for s in self.lesson.steps[self.index + 1:self.index + 1 + LOOK_AHEAD]]
            return Item("step", step.teacher_line, step.expected, step.targets, step.open_answer,
                        self.state.history, later)
        prompt = self.lesson.recall[self.index]
        return Item("recall", prompt.prompt, plain(prompt.prompt, self.profile), prompt.targets, False, self.state.history)

    def _begin_item(self) -> list[Say]:
        self.state = ItemState()
        if self.phase == "guided":
            step = self.lesson.steps[self.index]
            self.card = None
            if self.round == 1:
                task = step.expected[0].upper() + step.expected[1:] + "."
                self.card = self.profile.turn_card.format(task=task) + (self.profile.open_answer_card if step.open_answer else "")
                # Spoken too, in English, as Pimsleur does: in the first voice lesson the learner
                # repeated the teacher instead of answering when the card on screen went unseen.
                return [Say(step.teacher_line, "line"), Say(task, "task")]
            return [Say(step.teacher_line, "line")]
        self.card = None
        return [Say(self.lesson.recall[self.index].prompt, "prompt")]

    def _answer(self, text: str) -> list[Say]:
        item, st = self._item(), self.state
        target = item.targets[0]
        if st.awaiting_repeat:
            if repeats(target, text, self.profile):
                return self._finish(text, "modelled_repeated" if st.help == "model" else "corrected_repeated")
            if st.repeat_tries == 0:
                st.repeat_tries = 1
                return self._reply(text, [Say(target, "model")])
            return self._finish(text, "needs_turn")

        judgement: Judgement = self.judge(item, text)
        v = judgement.verdict
        self._log("judge", verdict=asdict(v), seconds=judgement.seconds, usage=judgement.usage)

        if v.verdict == "question":
            return self._reply(text, [Say(v.reply, "reply"), Say(item.teacher_said, "repeat")])
        if v.verdict == "social":
            return self._reply(text, [Say(self.profile.listening, "reply")])
        if v.verdict == "later_step" and item.kind == "step" and v.step in [n for n, _ in item.later]:
            return self._jump(text, v.step)
        if v.verdict == "unclear" and st.unclear == 0:
            st.unclear = 1
            return self._reply(text, [Say(self.profile.repeat_please, "repeat")])
        if v.verdict == "accept":
            label = {"": "independent", "cue": "cued", "correction": "corrected_repeated"}[st.help]
            return self._finish(text, label)

        # An error (or a second unclear turn) is a failed attempt.
        st.attempts += 1
        if st.attempts == 1:
            chunk = v.chunk.strip()
            if v.on_task and chunk and len(chunk.split()) <= MAX_CHUNK_WORDS and \
                    overlap(target, chunk, self.profile) < 0.75:  # a "chunk" that is the whole sentence is a model, not a correction
                st.help = "correction"
                return self._reply(text, [Say(self.profile.correction.format(chunk=chunk.rstrip(".!?")), "correction")])
            st.help = "cue"
            return self._reply(text, [Say(cue_for(target), "cue")])
        st.help, st.awaiting_repeat = "model", True
        return self._reply(text, [Say(target, "model"), Say(self.profile.repeat_please, "repeat")])

    def _jump(self, learner: str, number: int) -> list[Say]:
        """The learner did a later step's task: the steps in between are skipped, that one is done."""
        for skipped in range(self.index, number - 1):
            step = self.lesson.steps[skipped]
            self._record_evidence(Evidence("guided", self.round, step.number, "skipped", 0, "", step.targets[0]))
        self.index = number - 1
        self.state = ItemState()
        return self._finish(learner, "independent")

    def _reply(self, learner: str, says: list[Say]) -> list[Say]:
        self.state.history.append((learner, " ".join(s.text for s in says)))
        return says

    def _finish(self, learner: str, label: str) -> list[Say]:
        item = self._item()
        self._record_evidence(Evidence(self.phase, self.round if self.phase == "guided" else 0,
                                      self.index + 1, label, self.state.attempts, learner, item.targets[0]))
        self.index += 1
        if self.phase == "guided" and self.index < len(self.lesson.steps):
            return self._begin_item()
        if self.phase == "guided" and self.round == 1 and self.part == "1":
            self.phase, self.card = "closed", None
            return [Say((self.lesson.closing or self.profile.closing), "close")]
        if self.phase == "guided" and self.round == 1:
            self.round, self.index = 2, 0
            return [Say(self.profile.round_two, "transition")] + self._begin_item()
        if self.phase == "guided":
            self.phase, self.round, self.index = "recall", 0, 0
            return [Say(self.profile.recall, "transition")] + self._begin_item()
        if self.index < len(self.lesson.recall):
            return self._begin_item()
        self.phase, self.card = "closed", None
        return [Say((self.lesson.closing or self.profile.closing), "close")]

    def snapshot(self) -> dict:
        from .state import snapshot
        return snapshot(self)

    def save(self, store, session_id: str) -> None:
        store.save(session_id, self.snapshot())

    @classmethod
    def from_snapshot(cls, lesson: Lesson, judge: Judge, saved: dict, *,
                      profile: LanguageProfile = UKRAINIAN, clock=time.monotonic) -> "Session":
        from .state import restore
        return restore(cls, lesson, judge, saved, profile=profile, clock=clock)

    def _record_evidence(self, evidence: Evidence) -> None:
        evidence.source_id = self.lesson.source_id
        evidence.course_id = self.lesson.course_id
        evidence.lesson_id = self.lesson.lesson_id
        n = evidence.number - 1
        if evidence.phase == "opening":
            evidence.item_id = self.lesson.opening_item_ids[n]
        elif evidence.phase == "guided" and evidence.round == 0:
            ids = list(dict.fromkeys(s.target_item_ids[0] for s in self.lesson.steps))
            evidence.item_id = ids[n]
        else:
            rows = self.lesson.steps if evidence.phase == "guided" else self.lesson.recall
            evidence.item_id = rows[n].target_item_ids[0]
        self.evidence.append(evidence)

    # --- log --------------------------------------------------------------

    def _teacher(self, says: list[Say]) -> list[Say]:
        for say in says:
            say.display = plain(say.text, self.profile)
        self._log("teacher", says=[asdict(s) for s in says], card=self.card)
        return says

    def _log(self, event: str, **data) -> None:
        self.log.append({"t": round(self.clock(), 3), "event": event, "phase": self.phase,
                         "round": self.round, "index": self.index + 1, **data})


def wants_to_stop(text: str, profile: LanguageProfile = UKRAINIAN) -> bool:
    return any(word.startswith(profile.stop_words) for word in normalise(text, profile).split())


def round_zero(lesson: Lesson, profile: LanguageProfile = UKRAINIAN) -> list[tuple[str, str]]:
    """Each step's first target once, in step order, with the step's task for the card."""
    seen: set[str] = set()
    items = []
    for step in lesson.steps:
        sentence = step.targets[0] if step.targets else ""
        if sentence and step.target_item_ids[0] not in seen:
            seen.add(step.target_item_ids[0])
            items.append((sentence, step.expected))
    return items


def cue_for(target: str) -> str:
    """The first words of the target, about a third of it and at least one word, trailing off."""
    words = target.rstrip(".!?").split()
    keep = max(1, min(2, len(words) // 3 or 1))
    return " ".join(words[:keep]) + "…"
