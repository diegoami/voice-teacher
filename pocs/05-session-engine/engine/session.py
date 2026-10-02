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
from dataclasses import asdict, dataclass, field

from .judge import Item, Judgement
from .package import Lesson, normalise, plain

# Fixed teacher phrases, stress-marked for the voice. TODO(milestone 3): check
# the marks against a dictionary with the rest of the voice output.
LISTEN = "Споча́тку послу́хайте, а по́тім повторі́ть."
NEW_SENTENCES = "Тепе́р нові́ ре́чення. Слу́хайте і повто́рюйте."
START_TALK = "До́бре. А тепе́р почні́мо розмо́ву."
ROUND_TWO = "До́бре. А тепе́р ще раз, без підка́зок."
RECALL = "Тепе́р кі́лька запита́нь."
REPEAT_PLEASE = "Повторі́ть, будь ла́ска."
LISTENING = "Слу́хаю вас."  # after a greeting back: the learner's turn is still to come
CORRECTION = "Ви́правлення: {chunk}. Скажі́ть усе́ ре́чення."

OPENING_CARD = "Listen and repeat exactly what you hear. Don't answer, even when it is a question."
MODEL_CARD = "Repeat exactly what you hear; don't answer it. You will need it to {task}."

MAX_CHUNK_WORDS = 4
LOOK_AHEAD = 4  # later steps the judge may recognise when the learner runs ahead
STOP_WORDS = ("закінч", "закинч", "стоп", "досить", "кінець")  # «Закінчимо» ends the lesson


@dataclass
class Say:
    text: str
    kind: str  # intro, line, cue, correction, model, repeat, reply, prompt, transition, close


@dataclass
class Evidence:
    phase: str  # opening | guided | recall
    round: int  # 0 (repeat), 1 (task cards), 2 (no cards) for guided; 0 otherwise
    number: int  # line, step or prompt number
    label: str  # repeated | independent | cued | corrected_repeated | modelled_repeated | needs_turn | skipped
    attempts: int  # judged attempts that failed before the result
    learner: str  # the turn the label rests on
    target: str


def word_edits(a: list[str], b: list[str]) -> int:
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j - 1] + (x != y), previous[j] + 1, current[j - 1] + 1))
        previous = current
    return previous[-1]


def repeats(line: str, heard: str) -> bool:
    """A repetition, not an answer: at most one word in three changed, missing or added (at least one).

    Speech recognition drops and garbles a word here and there; an answer adds
    words («це коштує двадцять» for «Скільки це коштує?») and fails.
    """
    want, got = normalise(line).split(), normalise(heard).split()
    return word_edits(want, got) <= max(1, len(want) // 3)


def overlap(line: str, heard: str) -> float:
    want = normalise(line).split()
    got = set(normalise(heard).split())
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
    def __init__(self, lesson: Lesson, judge, clock=time.monotonic):
        self.lesson = lesson
        self.judge = judge
        self.clock = clock
        self.phase = "new"  # new, opening, guided, recall, closed
        self.model_items = round_zero(lesson)  # (sentence, task) pairs for round 0
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
        self.phase = "opening"
        self.card = OPENING_CARD
        return self._teacher([Say(self.lesson.introduction + " " + LISTEN, "intro"),
                              Say(self.lesson.opening[0], "line")])

    def hear(self, text: str) -> list[Say]:
        if self.done:
            raise RuntimeError("the lesson is closed")
        self._log("learner", text=text)
        if wants_to_stop(text):
            self.phase, self.card = "closed", None
            self._log("stopped")
            return self._teacher([Say(self.lesson.closing, "close")])
        if self.phase == "opening" or (self.phase == "guided" and self.round == 0):
            return self._teacher(self._opening(text))
        return self._teacher(self._answer(text))

    # --- opening ----------------------------------------------------------

    def _opening(self, text: str) -> list[Say]:
        """Listen and repeat: the opening review, then round 0. No model call."""
        lines = self.lesson.opening if self.phase == "opening" else [s for s, _ in self.model_items]
        line = lines[self.index]
        if not repeats(line, text) and not self.resaid:
            self.resaid = True
            return [Say(line, "repeat")]
        label = "repeated" if repeats(line, text) else "needs_turn"
        self.evidence.append(Evidence(self.phase, self.round, self.index + 1, label, int(self.resaid), text, line))
        self.index += 1
        self.resaid = False
        if self.index < len(lines):
            return self._repeat_line(self.index)
        if self.phase == "opening":
            self.phase, self.round, self.index = "guided", 0, 0
            return [Say(NEW_SENTENCES, "transition")] + self._repeat_line(0)
        self.round, self.index = 1, 0
        return [Say(START_TALK, "transition")] + self._begin_item()

    def _repeat_line(self, index: int) -> list[Say]:
        if self.phase == "opening":
            self.card = OPENING_CARD
            return [Say(self.lesson.opening[index], "line")]
        sentence, task = self.model_items[index]
        self.card = MODEL_CARD.format(task=task)
        return [Say(sentence, "line")]

    # --- guided and recall ------------------------------------------------

    def _item(self) -> Item:
        if self.phase == "guided":
            step = self.lesson.steps[self.index]
            later = [(s.number, s.expected) for s in self.lesson.steps[self.index + 1:self.index + 1 + LOOK_AHEAD]]
            return Item("step", step.teacher_line, step.expected, step.targets, step.open_answer,
                        self.state.history, later)
        prompt = self.lesson.recall[self.index]
        return Item("recall", prompt.prompt, plain(prompt.prompt), prompt.targets, False, self.state.history)

    def _begin_item(self) -> list[Say]:
        self.state = ItemState()
        if self.phase == "guided":
            step = self.lesson.steps[self.index]
            self.card = None
            if self.round == 1:
                task = step.expected[0].upper() + step.expected[1:] + "."
                self.card = "Your turn: " + task + (" Any correct answer will do." if step.open_answer else "")
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
            if repeats(target, text):
                return self._finish(text, "modelled_repeated" if st.help == "model" else "corrected_repeated")
            if st.repeat_tries == 0:
                st.repeat_tries = 1
                return self._reply(text, [Say(target, "model")])
            return self._finish(text, "needs_turn")

        judgement: Judgement = self.judge(item, text)
        v = judgement.verdict
        self._log("judge", verdict=v.model_dump(), seconds=judgement.seconds, usage=judgement.usage)

        if v.verdict == "question":
            return self._reply(text, [Say(v.reply, "reply"), Say(item.teacher_said, "repeat")])
        if v.verdict == "social":
            return self._reply(text, [Say(LISTENING, "reply")])
        if v.verdict == "later_step" and item.kind == "step" and v.step in [n for n, _ in item.later]:
            return self._jump(text, v.step)
        if v.verdict == "unclear" and st.unclear == 0:
            st.unclear = 1
            return self._reply(text, [Say(REPEAT_PLEASE, "repeat")])
        if v.verdict == "accept":
            label = {"": "independent", "cue": "cued", "correction": "corrected_repeated"}[st.help]
            return self._finish(text, label)

        # An error (or a second unclear turn) is a failed attempt.
        st.attempts += 1
        if st.attempts == 1:
            chunk = v.chunk.strip()
            if v.on_task and chunk and len(chunk.split()) <= MAX_CHUNK_WORDS and \
                    overlap(target, chunk) < 0.75:  # a "chunk" that is the whole sentence is a model, not a correction
                st.help = "correction"
                return self._reply(text, [Say(CORRECTION.format(chunk=chunk.rstrip(".!?")), "correction")])
            st.help = "cue"
            return self._reply(text, [Say(cue_for(target), "cue")])
        st.help, st.awaiting_repeat = "model", True
        return self._reply(text, [Say(target, "model"), Say(REPEAT_PLEASE, "repeat")])

    def _jump(self, learner: str, number: int) -> list[Say]:
        """The learner did a later step's task: the steps in between are skipped, that one is done."""
        for skipped in range(self.index, number - 1):
            step = self.lesson.steps[skipped]
            self.evidence.append(Evidence("guided", self.round, step.number, "skipped", 0, "", step.targets[0]))
        self.index = number - 1
        self.state = ItemState()
        return self._finish(learner, "independent")

    def _reply(self, learner: str, says: list[Say]) -> list[Say]:
        self.state.history.append((learner, " ".join(s.text for s in says)))
        return says

    def _finish(self, learner: str, label: str) -> list[Say]:
        item = self._item()
        self.evidence.append(Evidence(self.phase, self.round if self.phase == "guided" else 0,
                                      self.index + 1, label, self.state.attempts, learner, item.targets[0]))
        self.index += 1
        if self.phase == "guided" and self.index < len(self.lesson.steps):
            return self._begin_item()
        if self.phase == "guided" and self.round == 1:
            self.round, self.index = 2, 0
            return [Say(ROUND_TWO, "transition")] + self._begin_item()
        if self.phase == "guided":
            self.phase, self.round, self.index = "recall", 0, 0
            return [Say(RECALL, "transition")] + self._begin_item()
        if self.index < len(self.lesson.recall):
            return self._begin_item()
        self.phase, self.card = "closed", None
        return [Say(self.lesson.closing, "close")]

    # --- log --------------------------------------------------------------

    def _teacher(self, says: list[Say]) -> list[Say]:
        self._log("teacher", says=[asdict(s) for s in says], card=self.card)
        return says

    def _log(self, event: str, **data) -> None:
        self.log.append({"t": round(self.clock(), 3), "event": event, "phase": self.phase,
                         "round": self.round, "index": self.index + 1, **data})


def wants_to_stop(text: str) -> bool:
    return any(word.startswith(STOP_WORDS) for word in normalise(text).split())


def round_zero(lesson: Lesson) -> list[tuple[str, str]]:
    """Each step's first target once, in step order, with the step's task for the card."""
    seen: set[str] = set()
    items = []
    for step in lesson.steps:
        sentence = step.targets[0] if step.targets else ""
        if sentence and normalise(sentence) not in seen:
            seen.add(normalise(sentence))
            items.append((sentence, step.expected))
    return items


def cue_for(target: str) -> str:
    """The first words of the target, about a third of it and at least one word, trailing off."""
    words = target.rstrip(".!?").split()
    keep = max(1, min(2, len(words) // 3 or 1))
    return " ".join(words[:keep]) + "…"
