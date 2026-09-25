"""Reading list, sentence-level scoring and the per-provider summary."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .align import align, distance
from .text import is_other_script, is_russian, plain, words

LINE = re.compile(r"^(\d+)\.\s+(.*?)\s*(?:<!--\s*(.*?)\s*-->)?\s*$")


@dataclass(frozen=True)
class Sentence:
    number: int
    text: str  # as read, with stress marks
    tags: tuple[str, ...] = ()

    @property
    def plain(self) -> str:
        return plain(self.text)

    @property
    def words(self) -> list[str]:
        return words(self.text)


def reading_list(path: Path) -> list[Sentence]:
    """The numbered lines under `## Sentences`; `<!-- 4A -->` becomes a tag."""
    out = []
    inside = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            inside = line.strip() == "## Sentences"
            continue
        match = LINE.match(line)
        if inside and match:
            tags = tuple((match.group(3) or "").split())
            out.append(Sentence(int(match.group(1)), match.group(2), tags))
    return out


@dataclass
class SentenceResult:
    sentence: Sentence
    heard: list[str]  # hypothesis words aligned to this sentence
    subs: int = 0
    dels: int = 0
    ins: int = 0
    russian: list[str] = field(default_factory=list)
    other_script: list[str] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return self.subs + self.dels + self.ins

    @property
    def exact(self) -> bool:
        return self.errors == 0

    @property
    def char_errors(self) -> int:
        return distance(" ".join(self.sentence.words), " ".join(self.heard))


def _result(sentence: Sentence, ref: list[str], hyp: list[str], ops) -> SentenceResult:
    heard = [hyp[op.hyp] for op in ops if op.hyp is not None]
    result = SentenceResult(sentence, heard)
    for op in ops:
        if op.kind == "sub":
            result.subs += 1
        elif op.kind == "del":
            result.dels += 1
        elif op.kind == "ins":
            result.ins += 1
    result.russian = [w for w in heard if is_russian(w)]
    result.other_script = [w for w in heard if is_other_script(w)]
    return result


def score_recording(sentences: list[Sentence], hypothesis: str) -> list[SentenceResult]:
    """Align one transcript of the whole reading with the whole list, then split by sentence.

    An inserted word belongs to the sentence of the reference word before it
    (the first sentence if it comes before everything).
    """
    ref: list[str] = []
    owner: list[int] = []
    for k, sentence in enumerate(sentences):
        ref.extend(sentence.words)
        owner.extend([k] * len(sentence.words))
    hyp = words(hypothesis)
    per_sentence: list[list] = [[] for _ in sentences]
    current = 0
    for op in align(ref, hyp):
        if op.ref is not None:
            current = owner[op.ref]
        per_sentence[current].append(op)
    return [_result(s, s.words, hyp, ops) for s, ops in zip(sentences, per_sentence)]


def score_pairs(pairs: list[tuple[Sentence, str]]) -> list[SentenceResult]:
    """Score turns whose reference sentence is known one by one (a lesson's opening)."""
    results = []
    for sentence, heard in pairs:
        hyp = words(heard)
        results.append(_result(sentence, sentence.words, hyp, align(sentence.words, hyp)))
    return results


@dataclass
class Summary:
    ref_words: int
    heard_words: int
    subs: int
    dels: int
    ins: int
    ref_chars: int
    char_errors: int
    russian: int
    other_script: int
    sentences: int
    exact: int
    tagged: int
    tagged_exact: int

    @property
    def wer(self) -> float:
        return (self.subs + self.dels + self.ins) / self.ref_words if self.ref_words else 0.0

    @property
    def cer(self) -> float:
        return self.char_errors / self.ref_chars if self.ref_chars else 0.0

    @property
    def russian_share(self) -> float:
        return self.russian / self.heard_words if self.heard_words else 0.0


def summarise(results: list[SentenceResult], tag: str = "4A") -> Summary:
    tagged = [r for r in results if tag in r.sentence.tags]
    return Summary(
        ref_words=sum(len(r.sentence.words) for r in results),
        heard_words=sum(len(r.heard) for r in results),
        subs=sum(r.subs for r in results),
        dels=sum(r.dels for r in results),
        ins=sum(r.ins for r in results),
        ref_chars=sum(len(" ".join(r.sentence.words)) for r in results),
        char_errors=sum(r.char_errors for r in results),
        russian=sum(len(r.russian) for r in results),
        other_script=sum(len(r.other_script) for r in results),
        sentences=len(results),
        exact=sum(r.exact for r in results),
        tagged=len(tagged),
        tagged_exact=sum(r.exact for r in tagged),
    )
