"""The teacher model's only job: judge one learner turn.

The engine decides what the teacher says (the step lines, the task cards, a
correction template, the full sentence after two misses). The model returns a
verdict, the chunk to correct and, for a question about meaning, a one-sentence
answer. Less for the model to do means faster turns and no lesson rules for it
to break.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from .llm import Connection, connection, usage_of
from .package import Lesson

SYSTEM = """You judge one learner turn in a spoken Ukrainian lesson. The learner is
an adult reactivating Ukrainian learnt earlier (about A2). The learner's words
come from speech recognition: ignore capital letters, punctuation and missing
stress marks.

Given the step's task, the expected target sentence(s) and the learner's turn,
return:

- verdict:
  - "accept": correct Ukrainian that does the task. A different correct
    sentence is fine, and so is a missing «а» or a small word-order change.
    When the step is an open answer, any correct sentence of the right kind is
    fine.
  - "error": the learner tried the task but the Ukrainian is wrong: a Russian
    word or form (где, как, нет, потом, можно, спасибо …), a wrong ending or
    case, a wrong word, a missing key word; or the learner did something else
    than the task.
  - "unclear": you cannot tell what the learner meant (a few syllables,
    hesitation only, noise).
  - "question": the learner asks what a word means or asks for help.
- on_task: true when the learner tried to do the step's task.
- chunk: for "error" only, the correct Ukrainian for the single most important
  mistake, one to four words, with stress marks (combining acute after the
  stressed vowel) where you are sure. Not the whole sentence unless it is that
  short. "" otherwise.
- reply: for "question" only, one short Ukrainian sentence that answers it. ""
  otherwise.
- note: a few English words on what was wrong, for the log. "" when accepted.

Judge strictly on Russian: a Russian word is an error even when understandable.
Judge generously on everything else a Ukrainian listener would let pass."""


class Verdict(BaseModel):
    verdict: Literal["accept", "error", "unclear", "question"]
    on_task: bool
    chunk: str
    reply: str
    note: str


def lesson_context(lesson: Lesson) -> str:
    """The per-lesson part of the system prompt; stable across the lesson, so providers can cache it."""
    phrases = "\n".join(f"- {p}" for p in lesson.active_phrases)
    return f"Learner: {lesson.learner}\nLesson {lesson.part}: {lesson.title}\nPhrases practised:\n{phrases}"


@dataclass
class Item:
    """What the judge needs about the current step or recall prompt."""
    kind: str  # "step" | "recall"
    teacher_said: str
    task: str  # English
    targets: list[str]
    open_answer: bool = False
    history: list[tuple[str, str]] = field(default_factory=list)  # earlier (learner, teacher) exchanges on this item


def turn_message(item: Item, learner: str) -> str:
    return json.dumps({
        "teacher_said": item.teacher_said,
        "task": item.task,
        "targets": item.targets,
        "open_answer": item.open_answer,
        "earlier_attempts": [{"learner": a, "teacher": b} for a, b in item.history],
        "learner_turn": learner,
    }, ensure_ascii=False)


@dataclass
class Judgement:
    verdict: Verdict
    seconds: float
    usage: dict


class LLMJudge:
    def __init__(self, lesson: Lesson, conn: Connection | None = None, client=None, model: str | None = None):
        self.conn = conn or connection()
        self.client = client or self.conn.client()
        self.model = model or self.conn.model("teacher")
        self.system = SYSTEM + "\n\n" + lesson_context(lesson)

    def __call__(self, item: Item, learner: str) -> Judgement:
        started = time.monotonic()
        completion = self.client.chat.completions.parse(
            model=self.model,
            messages=[{"role": "system", "content": self.system},
                      {"role": "user", "content": turn_message(item, learner)}],
            response_format=Verdict,
            max_tokens=2000,
            extra_body={**self.conn.extra_body(), **self.conn.reasoning()},
        )
        seconds = round(time.monotonic() - started, 2)
        message = completion.choices[0].message
        if message.parsed is None:
            raise RuntimeError(f"no verdict from {self.model}: {message.refusal or completion.choices[0].finish_reason}")
        return Judgement(message.parsed, seconds, usage_of(completion))
