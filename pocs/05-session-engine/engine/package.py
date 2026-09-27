"""Read a `/voice-prepare` package from learnukrainian into lesson data.

Everything that can be read from the package deterministically is read here:
the opening, each guided step's teacher line and expected outcome, the recall
prompts. Only the per-step target sentences, which the package does not
state, are derived with Claude (`derive.py`).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

STRESS = "́"


def plain(text: str) -> str:
    """Remove stress marks (combining acute)."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFD", text).replace(STRESS, ""))


def normalise(text: str) -> str:
    """Comparable form: no stress, lower case, apostrophes unified, letters and digits only."""
    text = plain(text).lower()
    for mark in "’ʼ'`":
        text = text.replace(mark, "")
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


@dataclass
class Step:
    number: int
    teacher_line: str  # with stress marks, as authored
    expected: str  # English, from the package: what the learner is to say
    setting: str = ""  # text before the teacher line, e.g. "New cycle, in the street:"
    targets: list[str] = field(default_factory=list)  # Ukrainian, stress-marked; hidden until an attempt
    phrase: str = ""  # the Active phrase set item or earlier weak expression practised
    open_answer: bool = False  # any correct sentence will do (thanks, where he is going, …)


@dataclass
class RecallPrompt:
    number: int
    prompt: str  # with stress marks
    targets: list[str] = field(default_factory=list)
    phrase: str = ""


@dataclass
class Lesson:
    source: str  # the package folder name in learnukrainian
    part: str  # "4B"
    title: str
    learner: str
    main_goal: str
    introduction: str
    opening: list[str]
    active_phrases: list[str]
    weak_expressions: list[str]
    scenario: str  # the Guided sequence's setup text
    steps: list[Step]
    recall: list[RecallPrompt]
    closing: str = "Заня́ття закі́нчено."

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Lesson:
        data = dict(data)
        data["steps"] = [Step(**s) for s in data["steps"]]
        data["recall"] = [RecallPrompt(**r) for r in data["recall"]]
        return cls(**data)


def _field(brief: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:[ \t]*(.*)$", brief, re.M)
    if not match:
        raise ValueError(f"package brief has no '{name}:' line")
    return match.group(1).strip()


def _block(brief: str, start: str, end: str) -> str:
    match = re.search(rf"^{re.escape(start)}.*?\n(.*?)^{re.escape(end)}", brief, re.M | re.S)
    if not match:
        raise ValueError(f"package brief has no '{start}' … '{end}' section")
    return match.group(1)


def _items(block: str, bullet: str) -> list[str]:
    pattern = r"^\d+\.\s+(.*)$" if bullet == "number" else r"^-\s+(.*)$"
    return [m.group(1).strip() for m in re.finditer(pattern, block, re.M)]


STEP = re.compile(r"^(?P<setting>.*?)\b(?:[Ss]ay|[Aa]sk) «(?P<line>[^»]+)»\s*(?P<rest>.*)$", re.S)


def parse_step(number: int, text: str) -> Step:
    match = STEP.match(text)
    if not match:
        raise ValueError(f"guided step {number} has no «…» line to say: {text!r}")
    rest = match.group("rest").strip()
    wait = re.search(r"\bWait for (the learner|him|her) to\s+|\bThe learner\s+", rest)  # 2B/2C: "The learner orders…"
    if not wait:
        raise ValueError(f"guided step {number} does not say what the learner is to do: {text!r}")
    # A note between the line and "Wait for…" is for the teacher: keep it with the setting.
    setting = " ".join(p for p in (match.group("setting").strip().rstrip(":").strip(),
                                   rest[:wait.start()].strip()) if p)
    return Step(number, match.group("line").strip(), rest[wait.end():].strip().rstrip("."), setting)


def parse_package(folder: Path) -> Lesson:
    text = (folder / "package.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    if "SESSION_BRIEF" not in text:
        raise ValueError(f"{folder}: no SESSION_BRIEF in package.md")
    brief = text[text.index("\nSESSION_BRIEF") + 1:]

    declared = re.search(r"^Opening review \((\d+) lines\):", brief, re.M)
    opening = _items(_block(brief, "Opening review", "Active phrase set:"), "number")
    if not declared or int(declared.group(1)) != len(opening):
        raise ValueError(f"{folder}: opening declares {declared and declared.group(1)} lines, found {len(opening)}")

    guided = _block(brief, "Guided sequence:", "Delayed recall:")
    first_step = re.search(r"^1\.\s", guided, re.M)
    scenario = " ".join(guided[:first_step.start()].split()) if first_step else ""
    raw_steps: list[str] = []
    for line in guided[first_step.start() if first_step else 0:].splitlines():
        match = re.match(r"^\d+\.\s+(.*)", line)
        if match:
            raw_steps.append(match.group(1).strip())
        elif raw_steps and line.strip():
            raw_steps[-1] += " " + line.strip()

    part_line = _field(brief, "Lesson part")  # "4B — Getting to the centre by transport"
    part, _, title = part_line.partition("—")
    intro_block = _block(brief, "Teacher introduction:", "Opening review")
    return Lesson(
        source=folder.name,
        part=part.strip(),
        title=title.strip(),
        learner=_field(brief, "Learner"),
        main_goal=_field(brief, "Main goal"),
        introduction=" ".join(intro_block.split()),
        opening=opening,
        active_phrases=_items(_block(brief, "Active phrase set:", "Guided sequence:"), "bullet"),
        weak_expressions=_items(_block(brief, "Earlier weak expressions included:", "Source:"), "bullet"),
        scenario=scenario,
        steps=[parse_step(n, s) for n, s in enumerate(raw_steps, 1)],
        recall=[RecallPrompt(n, p) for n, p in
                enumerate(_items(_block(brief, "Delayed recall:", "Earlier weak expressions included:"), "bullet"), 1)],
    )
