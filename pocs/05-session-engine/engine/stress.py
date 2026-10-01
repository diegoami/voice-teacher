"""Stress marks for text the engine did not take from the lesson.

Multilingual v2 stresses Ukrainian correctly only when it is given the marks
(POC 2). Almost everything the engine says is already marked: the lesson's
lines, targets and the fixed phrases. Only a correction chunk or a short
answer comes from the model, in plain spelling. So there is no stress library:

1. a word that already has a mark is left alone;
2. an unmarked word is looked up in a dictionary of every marked word of the
   lesson (and of the engine's fixed phrases), keeping its capitalisation;
3. then in `CORRECTIONS`, words every voice gets wrong;
4. anything else stays unmarked.
"""

from __future__ import annotations

import re

from .derive import marked_words
from .package import STRESS, Lesson, normalise

# Words every voice stresses wrongly, keyed by plain lower-case spelling. Add more as the lessons show them.
CORRECTIONS = {
    "мене": "мене́",
}

WORD = re.compile(r"[\w" + STRESS + r"]+(?:[’ʼ'][\w" + STRESS + r"]+)*")


def lesson_texts(lesson: Lesson) -> list[str]:
    texts = [lesson.introduction, lesson.closing, *lesson.opening, *lesson.active_phrases, *lesson.weak_expressions]
    for step in lesson.steps:
        texts += [step.setting, step.teacher_line, *step.targets, step.phrase]
    for prompt in lesson.recall:
        texts += [prompt.prompt, *prompt.targets, prompt.phrase]
    return texts


def fixed_phrases() -> list[str]:
    from . import session
    return [v for k, v in vars(session).items() if k.isupper() and isinstance(v, str) and STRESS in v]


class Stresser:
    def __init__(self, lesson: Lesson, corrections: dict[str, str] | None = None):
        self.known: dict[str, str] = {}
        for text in [*lesson_texts(lesson), *fixed_phrases()]:
            for key, word in marked_words(text).items():
                self.known.setdefault(key, word.lower())
        self.corrections = {normalise(k): v for k, v in (CORRECTIONS if corrections is None else corrections).items()}

    def mark(self, text: str) -> str:
        return WORD.sub(self._word, text)

    def _word(self, match: re.Match) -> str:
        word = match.group(0)
        if STRESS in word:
            return word
        key = normalise(word)
        marked = self.known.get(key) or self.corrections.get(key)
        if not marked:
            return word
        if len(word) > 1 and word.isupper():
            return marked.upper()
        if word[0].isupper():
            return marked[0].upper() + marked[1:]
        return marked
