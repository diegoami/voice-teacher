"""Read prepared lesson packages from learnukrainian and track the opening.

A package is the `package.md` that `/voice-prepare` writes into
`pimsleur-review/voice-sessions/<folder>/`. The connector never edits it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

STRESS = "́"
TEMPLATE_MARKER = "**Teacher:**"


def plain(text: str) -> str:
    """Remove stress marks (combining acute) for text the teacher speaks."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFD", text).replace(STRESS, ""))


def normalise(text: str) -> str:
    """Comparable form: no stress, lower case, letters and digits only."""
    text = plain(text).lower().replace("’", "").replace("'", "").replace("ʼ", "")
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


@dataclass
class Package:
    folder: Path
    text: str
    prompt_version: str
    session_label: str
    opening_lines: list[str]

    @property
    def name(self) -> str:
        return self.folder.name


def parse_package(folder: Path) -> Package:
    text = (folder / "package.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    version = re.search(r"^Prompt version: (\S+)", text, re.M)
    part = re.search(r"^Lesson part: (\S+)", text, re.M)
    block = re.search(r"^Opening review \((\d+) lines\):\n(.*?)^Active phrase set:", text, re.M | re.S)
    if not (version and part and block):
        raise ValueError(f"{folder}: not a filled VOICE_SESSION_PACKAGE")
    lines = [m.group(1).strip() for m in re.finditer(r"^\d+\. (.+)$", block.group(2), re.M)]
    if len(lines) != int(block.group(1)):
        raise ValueError(f"{folder}: opening declares {block.group(1)} lines, found {len(lines)}")
    return Package(folder, text, version.group(1), part.group(1), lines)


def is_unused(folder: Path) -> bool:
    """True when the folder has a package and its transcript is still the template."""
    transcript = folder / "transcript.md"
    if not (folder / "package.md").exists():
        return False
    return not transcript.exists() or TEMPLATE_MARKER not in transcript.read_text(encoding="utf-8")


def next_package(sessions_dir: Path, pinned: str | None = None) -> Package:
    """The newest unused package, or the pinned folder name."""
    if pinned:
        return parse_package(sessions_dir / pinned)
    candidates = sorted(p for p in sessions_dir.iterdir() if p.is_dir() and is_unused(p))
    if not candidates:
        raise LookupError("No prepared lesson is waiting. Run /voice-prepare in learnukrainian first.")
    return parse_package(candidates[-1])


@dataclass
class OpeningTracker:
    """Derives the opening position from what the teacher actually said.

    The next expected line advances only when the teacher's reported turn
    contains it, so the server's instruction always follows the evidence.
    """

    lines: list[str]
    next_index: int = 0  # index of the next line not yet presented
    resaid: set[int] = field(default_factory=set)
    events: list[str] = field(default_factory=list)
    finished: bool = False

    def _contains(self, said: str, index: int) -> bool:
        return f" {normalise(self.lines[index])} " in f" {normalise(said)} "

    def observe(self, teacher_said: str) -> None:
        """Update the position from the teacher's previous turn."""
        if self.finished:
            return
        k = self.next_index
        if k < len(self.lines) and self._contains(teacher_said, k):
            merged = k + 1 < len(self.lines) and self._contains(teacher_said, k + 1)
            if merged:
                self.events.append(f"line {k + 2} merged into the turn with line {k + 1}")
            self.next_index = k + 2 if merged else k + 1
        elif k > 0 and self._contains(teacher_said, k - 1):
            self.resaid.add(k - 1)
            self.events.append(f"line {k} re-said")
        elif k == len(self.lines) and "почнімо розмову" in normalise(teacher_said):
            self.finished = True
        else:
            self.events.append(f"turn did not contain expected line {k + 1}: {teacher_said[:60]!r}")

    def instruction(self) -> str:
        """What the teacher's next turn must be, while the opening lasts."""
        if self.finished:
            return "Recorded."
        k = self.next_index
        n = len(self.lines)
        if k == 0:
            return ("Opening: your next turn is the Teacher introduction, then «Спочатку послухайте, "
                    f"а потім повторіть.», then «{plain(self.lines[0])}».")
        previous = plain(self.lines[k - 1])
        if k < n:
            text = f"Opening: your whole next turn is exactly «{plain(self.lines[k])}» and nothing else."
        else:
            text = ("Opening complete: say «Добре. А тепер почнімо розмову.» and ask the first "
                    "Guided sequence question in the same turn.")
        if k - 1 not in self.resaid:
            text += (f" Only if the learner's repetition was unintelligible or changed the meaning, "
                     f"say «{previous}» once more instead.")
        return text
