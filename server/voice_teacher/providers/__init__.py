"""Provider boundaries. Importing the core never instantiates a network client."""
from dataclasses import dataclass, field
from typing import Protocol, Literal
import json


@dataclass(frozen=True)
class Verdict:
    verdict: Literal["accept", "error", "unclear", "question", "social", "later_step"]
    on_task: bool
    chunk: str
    reply: str
    step: int
    note: str

    def __post_init__(self):
        if self.verdict not in {"accept", "error", "unclear", "question", "social", "later_step"}:
            raise ValueError("unsupported judge verdict")
        if type(self.on_task) is not bool or type(self.step) is not int or self.step < 0:
            raise ValueError("invalid judge fields")
        if not all(isinstance(v, str) for v in [self.chunk, self.reply, self.note]):
            raise ValueError("judge text fields must be strings")


@dataclass
class Item:
    kind: str
    teacher_said: str
    task: str
    targets: list[str]
    open_answer: bool = False
    history: list[tuple[str, str]] = field(default_factory=list)
    later: list[tuple[int, str]] = field(default_factory=list)


@dataclass(frozen=True)
class Judgement:
    verdict: Verdict
    seconds: float
    usage: dict


class Judge(Protocol):
    def __call__(self, item: Item, learner: str) -> Judgement: ...


class SpeechRecognizer(Protocol):
    def transcribe(self, audio: bytes, *, language: str) -> str: ...


class SpeechSynthesizer(Protocol):
    def synthesize(self, text: str, *, language: str) -> bytes: ...


class SessionStore(Protocol):
    def save(self, session_id: str, state: dict) -> None: ...
    def load(self, session_id: str) -> dict: ...


def turn_message(item: Item, learner: str) -> str:
    """Post-attempt judging input; never a pre-attempt teacher prompt."""
    return json.dumps({"teacher_said": item.teacher_said, "task": item.task, "targets": item.targets,
                       "open_answer": item.open_answer,
                       "earlier_attempts": [{"learner": a, "teacher": b} for a, b in item.history],
                       "later_steps": [{"step": n, "task": task} for n, task in item.later],
                       "learner_turn": learner}, ensure_ascii=False)
