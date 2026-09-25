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
    guided_steps: list[str] = field(default_factory=list)
    recall_prompts: list[str] = field(default_factory=list)

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
    return Package(folder, text, version.group(1), part.group(1), lines,
                   guided_steps(section(text, "Guided sequence:", "Delayed recall:")),
                   [line[2:].strip() for line in section(text, "Delayed recall:",
                                                         "Earlier weak expressions included:").splitlines()
                    if line.startswith("- ")])


def section(text: str, start: str, end: str) -> str:
    match = re.search(rf"^{re.escape(start)}\n(.*?)^{re.escape(end)}", text, re.M | re.S)
    return match.group(1) if match else ""


def guided_steps(block: str) -> list[str]:
    """Numbered steps; unnumbered lines continue the previous step (the setup text before step 1 is dropped)."""
    steps: list[str] = []
    for line in block.splitlines():
        match = re.match(r"^\d+\.\s+(.*)", line)
        if match:
            steps.append(match.group(1).strip())
        elif steps and line.strip():
            steps[-1] += " " + line.strip()
    return steps


def spoken_line(step: str) -> str:
    """The teacher's line in a step: the first «…» after "Say", else the first «…», else the step itself."""
    match = re.search(r"Say «([^»]+)»", step) or re.search(r"«([^»]+)»", step)
    return match.group(1) if match else step


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
    for folder in reversed(candidates):
        package = parse_package(folder)
        if not package.prompt_version.startswith("g"):  # g1, g2, … are ChatGPT packages
            return package
    raise LookupError("No prepared lesson is waiting. Run /voice-prepare in learnukrainian first.")


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


def says(teacher_said: str, line: str) -> bool:
    """True when the teacher's turn contains the line, allowing small rewording.

    Lines of one or two words must appear exactly; longer ones need three
    quarters of their words in the turn.
    """
    want = normalise(line).split()
    if not want:
        return False
    if f" {' '.join(want)} " in f" {normalise(teacher_said)} ":
        return True
    if len(want) <= 2:
        return False
    have = set(normalise(teacher_said).split())
    return sum(word in have for word in want) / len(want) >= 0.75


@dataclass
class StepTracker:
    """Guided steps followed by recall prompts, advanced by what the teacher said."""

    guided: list[str]
    recall: list[str]
    current: int = -1  # index of the last item the teacher presented
    events: list[str] = field(default_factory=list)

    @property
    def items(self) -> list[tuple[str, str]]:
        return [("guided", s) for s in self.guided] + [("recall", r) for r in self.recall]

    def label(self, index: int) -> str:
        kind, _ = self.items[index]
        if kind == "guided":
            return f"Guided step {index + 1} of {len(self.guided)}"
        return f"Delayed recall prompt {index - len(self.guided) + 1} of {len(self.recall)}"

    def observe(self, teacher_said: str) -> None:
        items = self.items
        for j in range(self.current + 1, len(items)):  # earliest match ahead wins: briefs repeat lines
            if says(teacher_said, spoken_line(items[j][1])):
                if j > self.current + 1:
                    skipped = ", ".join(self.label(i) for i in range(self.current + 1, j))
                    self.events.append(f"skipped {skipped}")
                self.current = j
                return

    def instruction(self) -> str:
        items = self.items
        if self.current < 0:
            return f"Next: {self.label(0)}: {plain(items[0][1])}"
        now = f"Now: {self.label(self.current)}."
        nxt = self.current + 1
        if nxt < len(items):
            kind = items[nxt][0]
            if kind == "recall" and items[self.current][0] == "guided":
                lead = ("When the learner has done it and any correction is finished, go straight to the "
                        "Delayed recall, one prompt at a time, with no model and no cue before the first "
                        "attempt.")
            else:
                lead = "When the learner has done it and any correction is finished, go on."
            return f"{now} {lead} Next: {self.label(nxt)}: {plain(items[nxt][1])}"
        return (f"{now} This is the last item. When the learner has answered it, call end_session "
                "with the complete transcript, then say the closing sentence.")


@dataclass
class LessonTracker:
    """Opening first, then guided steps and recall prompts."""

    opening: OpeningTracker
    steps: StepTracker

    @classmethod
    def for_package(cls, package: Package) -> "LessonTracker":
        return cls(OpeningTracker(package.opening_lines),
                   StepTracker(package.guided_steps, package.recall_prompts))

    @property
    def phase(self) -> str:
        if not self.opening.finished:
            return "opening"
        return "lesson" if self.steps.current < len(self.steps.guided) else "recall"

    def observe(self, teacher_said: str) -> None:
        if not self.opening.finished:
            self.opening.observe(teacher_said)
            all_said = self.opening.next_index >= len(self.opening.lines)
            if all_said and not self.opening.finished and self.steps.items and \
                    says(teacher_said, spoken_line(self.steps.items[0][1])):
                self.opening.finished = True
        if self.opening.finished:
            self.steps.observe(teacher_said)

    def instruction(self) -> str:
        if not self.opening.finished:
            text = self.opening.instruction()
            if "Opening complete" in text and self.steps.items:
                text += f" {self.steps.label(0)}: {plain(self.steps.items[0][1])}"
            return text
        if not self.steps.items:
            return "Recorded."
        return self.steps.instruction()

    @property
    def events(self) -> list[str]:
        return self.opening.events + self.steps.events
