"""Derive each guided step's and recall prompt's target sentences with a language model.

One structured-output call per lesson part. The package says what the learner
is to do in English («Wait for the learner to ask which is faster») but not
the Ukrainian sentence; the engine needs that sentence to judge an attempt
and to model it after two failed ones.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from .llm import Connection, connection, usage_of
from .package import Lesson, normalise, plain

MAX_TARGETS = 3
MAX_OUTPUT_TOKENS = 4000  # 17 sets of targets fit easily; OpenRouter reserves credit for this many

SYSTEM = """You prepare lesson data for a spoken Ukrainian lesson engine. The engine
hides each step's target sentence from the teacher until the learner has tried,
then uses it to judge the attempt and, after two failed attempts, to say it.

For every guided step and every delayed-recall prompt, write what the learner is
expected to say:

- targets: one to three short, natural Ukrainian sentences the learner could
  say, the most expected first. Build them from the Active phrase set, the
  earlier weak expressions and the other wording of the brief. Use the
  learner's gender as the brief states it. Do not add vocabulary the brief does
  not use unless the step cannot be answered without it.
- Mark the stress of every word of two or more syllables with a combining acute
  accent after the stressed vowel, exactly as the brief marks it. Copy the
  brief's marks for its words; do not re-stress them.
- phrase: the Active phrase set item or earlier weak expression the step
  practises, copied verbatim from the brief, or "" if none.
- open_answer (steps only): true when any correct sentence of the right kind is
  fine (thanking, saying where one is going), false when a particular question
  or answer is expected.

Return the steps and prompts in the brief's order, numbered as in the input."""


class StepTargets(BaseModel):
    step: int
    targets: list[str]
    phrase: str
    open_answer: bool


class RecallTargets(BaseModel):
    prompt: int
    targets: list[str]
    phrase: str


class Derived(BaseModel):
    steps: list[StepTargets]
    recall: list[RecallTargets]


def request_text(lesson: Lesson) -> str:
    steps = "\n".join(
        f"{s.number}. {s.setting + ': ' if s.setting else ''}the teacher says «{s.teacher_line}»; "
        f"the learner is to {s.expected}." for s in lesson.steps)
    recall = "\n".join(f"{r.number}. {r.prompt}" for r in lesson.recall)
    phrases = "\n".join(f"- {p}" for p in lesson.active_phrases)
    weak = "\n".join(f"- {w}" for w in lesson.weak_expressions) or "- none"
    return (f"Lesson part {lesson.part}: {lesson.title}\n"
            f"Learner: {lesson.learner}\nMain goal: {lesson.main_goal}\n\n"
            f"Opening review lines:\n" + "\n".join(f"- {o}" for o in lesson.opening) + "\n\n"
            f"Active phrase set:\n{phrases}\n\nEarlier weak expressions:\n{weak}\n\n"
            f"Guided sequence ({lesson.scenario}):\n{steps}\n\nDelayed recall prompts:\n{recall}\n")


def apply(lesson: Lesson, derived: Derived) -> Lesson:
    """Copy the derived targets into the lesson; refuse anything that does not line up."""
    if [s.step for s in derived.steps] != [s.number for s in lesson.steps]:
        raise ValueError(f"derived steps {[s.step for s in derived.steps]} do not match "
                         f"the package's {[s.number for s in lesson.steps]}")
    if [r.prompt for r in derived.recall] != [r.number for r in lesson.recall]:
        raise ValueError("derived recall prompts do not match the package's")
    empty = [f"step {d.step}" for d in derived.steps if not d.targets] + \
            [f"recall {d.prompt}" for d in derived.recall if not d.targets]
    if empty:
        raise ValueError(f"no targets for {', '.join(empty)}")
    for step, d in zip(lesson.steps, derived.steps):
        step.targets, step.phrase, step.open_answer = d.targets[:MAX_TARGETS], d.phrase, d.open_answer
    for prompt, d in zip(lesson.recall, derived.recall):
        prompt.targets, prompt.phrase = d.targets[:MAX_TARGETS], d.phrase
    return lesson


def marked_words(text: str) -> dict[str, str]:
    """Stress-marked words of a text, keyed by their normalised form."""
    return {normalise(w): w for w in re.findall(r"[\ẃ’ʼ']+", text) if "́" in w}


def unverified_stress(lesson: Lesson, brief: str) -> list[str]:
    """Target words whose stress mark the brief does not already contain.

    Returns the word as marked in the target, or with «(brief: …)» when the brief
    marks the same word differently.
    """
    known = marked_words(brief)
    found: dict[str, str] = {}
    for sentence in [t for s in lesson.steps for t in s.targets] + [t for r in lesson.recall for t in r.targets]:
        for key, word in marked_words(sentence).items():
            if key not in known:
                found.setdefault(key, word)
            elif known[key].lower() != word.lower():
                found.setdefault(key, f"{word} (brief: {known[key]})")
        for raw in re.findall(r"[\w’ʼ']+", plain(sentence)):  # unmarked polysyllables
            if len(re.findall(r"[аеєиіїоуюя]", raw.lower())) > 1 and normalise(raw) not in marked_words(sentence):
                found.setdefault(normalise(raw), f"{raw} (no stress mark)")
    return sorted(found.values(), key=str.lower)


def derive(lesson: Lesson, conn: Connection | None = None, client=None) -> tuple[Lesson, dict]:
    """Ask the targets model. Returns the lesson and the usage for the cost log."""
    conn = conn or connection()
    client = client or conn.client()
    completion = client.chat.completions.parse(
        model=conn.model("targets"),
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": request_text(lesson)}],
        response_format=Derived,
        max_tokens=MAX_OUTPUT_TOKENS,
        extra_body=conn.extra_body(),
    )
    message = completion.choices[0].message
    if message.refusal:
        raise RuntimeError(f"the model declined to derive the targets: {message.refusal}")
    if completion.choices[0].finish_reason == "length" or message.parsed is None:
        raise RuntimeError(f"no complete answer (finish reason {completion.choices[0].finish_reason})")
    return apply(lesson, message.parsed), usage_of(completion)
