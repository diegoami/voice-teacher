"""Simulated lessons: the same learner turns for every candidate teacher model.

A strong model writes, once per lesson, learner answers for every step and
recall prompt: a different correct sentence, and three versions with one
planted mistake (a Russian word, a wrong ending, a wrong word). A seeded plan
decides which answer the learner gives on each first attempt; after any help
the learner says the target. Every teacher model therefore judges the same
turns, and because the planted mistakes are known, what it misses and what it
wrongly rejects can be counted.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field

from pydantic import BaseModel

from .llm import Connection, connection, usage_of
from .package import Lesson, plain
from .session import Session

WRITER = """You write answers a learner of Ukrainian might give in a lesson, to test
a teacher. For every item you get the learner's task and the expected Ukrainian
sentence. Write, in plain spelling without stress marks and without explanations:

- variant: a different, correct and natural Ukrainian sentence that does the same
  task (other words or order; not the expected sentence).
- russian: the expected sentence with exactly one word replaced by its Russian
  form, the way a learner who also knows Russian slips (де → где, можна → можно,
  потім → потом, дякую → спасибо, ні → нет).
- ending: the expected sentence with exactly one wrong ending: case, gender
  agreement or verb form (найближча станція → найближчий станція, до центру →
  до центр).
- word: the expected sentence with exactly one wrong but Ukrainian word that
  changes or breaks the meaning.
- mistake: for russian, ending and word, the wrong word or words, as written.

Each mistaken version must differ from the expected sentence in exactly that one
place."""

INTENTS = {"exact": 9, "variant": 6, "russian": 6, "ending": 4, "word": 3, "unclear": 1}  # per 29 first attempts
SHOULD = {"exact": "accept", "variant": "accept", "russian": "error", "ending": "error", "word": "error",
          "unclear": "unclear"}
UNCLEAR = "е… ну… е"


class Answers(BaseModel):
    item: str
    variant: str
    russian: str
    russian_mistake: str
    ending: str
    ending_mistake: str
    word: str
    word_mistake: str


class Script(BaseModel):
    items: list[Answers]


def item_keys(lesson: Lesson) -> list[tuple[str, str, str]]:
    """(key, task, expected sentence) for every step and recall prompt."""
    keys = [(f"step {s.number}", s.expected, s.targets[0]) for s in lesson.steps]
    keys += [(f"recall {r.number}", plain(r.prompt), r.targets[0]) for r in lesson.recall]
    return keys


def write_script(lesson: Lesson, conn: Connection | None = None, client=None) -> tuple[dict, dict]:
    conn = conn or connection()
    client = client or conn.client()
    listing = "\n".join(f"{key}: task: {task}; expected: {plain(target)}" for key, task, target in item_keys(lesson))
    completion = client.chat.completions.parse(
        model=conn.model("targets"),
        messages=[{"role": "system", "content": WRITER}, {"role": "user", "content": listing}],
        response_format=Script, max_tokens=8000, extra_body=conn.extra_body())
    script = completion.choices[0].message.parsed
    if script is None:
        raise RuntimeError(f"no learner script: {completion.choices[0].finish_reason}")
    answers = {a.item: a.model_dump() for a in script.items}
    missing = [key for key, _, _ in item_keys(lesson) if key not in answers]
    if missing:
        raise ValueError(f"learner script lacks {missing}")
    return answers, usage_of(completion)


def plan(lesson: Lesson, seed: int = 1) -> dict[tuple[int, str], str]:
    """Intent per (round, item key) for every first attempt: rounds 1 and 2 and recall (round 0)."""
    slots = [(r, f"step {s.number}") for r in (1, 2) for s in lesson.steps] + \
            [(0, f"recall {p.number}") for p in lesson.recall]
    intents = [name for name, n in INTENTS.items() for _ in range(n)]
    while len(intents) < len(slots):
        intents.append("exact")
    random.Random(seed).shuffle(intents)
    return dict(zip(slots, intents))


@dataclass
class Result:
    model: str
    rows: list[dict] = field(default_factory=list)  # one per first attempt
    seconds: list[float] = field(default_factory=list)
    cost: float = 0.0
    calls: int = 0

    def count(self, intents: set[str], verdicts: set[str]) -> tuple[int, int]:
        mine = [r for r in self.rows if r["intent"] in intents and scored(r)]
        return sum(r["verdict"] in verdicts for r in mine), len(mine)

    def to_dict(self) -> dict:
        return {"model": self.model, "rows": self.rows, "seconds": self.seconds, "cost": self.cost, "calls": self.calls}


def scored(row: dict) -> bool:
    """A different word on an open-answer step («я їду до вокзалу») may be a good answer: not scored."""
    return not (row["intent"] == "word" and row.get("open_answer"))


def learner_text(session: Session, lesson: Lesson, answers: dict, intents: dict) -> str:
    """What the simulated learner says next, from the session's state."""
    say = lambda s: plain(s).rstrip(".!?")  # noqa: E731 - speech recognition gives plain spelling
    if session.phase == "opening":
        return say(lesson.opening[session.index])
    if session.phase == "guided" and session.round == 0:
        return say(session.model_items[session.index][0])
    item = session._item()
    st = session.state
    if st.history or st.awaiting_repeat or st.unclear:
        return say(item.targets[0])  # after any help, the learner gets it right
    key = f"step {session.index + 1}" if session.phase == "guided" else f"recall {session.index + 1}"
    intent = intents[(session.round if session.phase == "guided" else 0, key)]
    if intent == "exact":
        return say(item.targets[0])
    if intent == "unclear":
        return UNCLEAR
    return answers[key][intent]


def run(lesson: Lesson, answers: dict, judge, seed: int = 1) -> Result:
    """One simulated lesson; returns the first-attempt verdicts and the model's timings."""
    intents = plan(lesson, seed)
    result = Result(getattr(judge, "model", "fake"))
    first: dict[tuple[int, str], dict] = {}

    def recording_judge(item, text):
        judgement = judge(item, text)
        result.calls += 1
        result.seconds.append(judgement.seconds)
        result.cost += judgement.usage.get("cost_usd") or 0
        if not item.history:
            key = current_key()
            if key not in first:
                v = judgement.verdict
                first[key] = {"round": key[0], "item": key[1], "intent": intents[key], "learner": text,
                              "open_answer": item.open_answer,
                              "verdict": v.verdict, "chunk": v.chunk, "note": v.note}
        return judgement

    session = Session(lesson, recording_judge)

    def current_key():
        if session.phase == "guided":
            return session.round, f"step {session.index + 1}"
        return 0, f"recall {session.index + 1}"

    session.start()
    while not session.done:
        session.hear(learner_text(session, lesson, answers, intents))
    result.rows = [first[k] for k in intents if k in first]
    return result


def report(results: list[Result], lesson: Lesson) -> str:
    lines = [
        f"# Teacher models on simulated lesson {lesson.part}",
        "",
        f"{len(results[0].rows)} first attempts per model, the same for every model: "
        + ", ".join(f"{n} {name}" for name, n in INTENTS.items())
        + ". A different word on an open-answer step can be a good answer and is not scored (marked «–»).",
        "",
        "| Teacher model | Mistakes caught | Correct answers accepted | Unclear handled | Median / slowest call | Calls | Cost |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        caught, planted = r.count({"russian", "ending", "word"}, {"error"})
        accepted, correct = r.count({"exact", "variant"}, {"accept"})
        unclear_ok, unclear = r.count({"unclear"}, {"unclear", "error"})
        med = statistics.median(r.seconds) if r.seconds else 0
        lines.append(f"| {r.model} | {caught}/{planted} | {accepted}/{correct} | {unclear_ok}/{unclear} | "
                     f"{med:.2f} / {max(r.seconds, default=0):.2f} s | {r.calls} | ${r.cost:.4f} |")
    lines += ["", "## Every first attempt", "",
              "| Round | Item | Planted | Learner said | " + " | ".join(r.model for r in results) + " |",
              "| --- | --- | --- | --- |" + " --- |" * len(results)]
    for i, row in enumerate(results[0].rows):
        cells = []
        for r in results:
            other = r.rows[i]
            ok = other["verdict"] == SHOULD[row["intent"]] or (row["intent"] == "unclear" and other["verdict"] == "error")
            mark = "– " if not scored(row) else ("✓ " if ok else "✗ ")
            cells.append(mark + other["verdict"] + (f" «{other['chunk']}»" if other["chunk"] else ""))
        lines.append(f"| {row['round'] or 'recall'} | {row['item']} | {row['intent']} | {row['learner']} | "
                     + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
