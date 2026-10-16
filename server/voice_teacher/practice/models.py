"""Prepared practice inputs. Repository parsing belongs to content adapters."""
from dataclasses import asdict, dataclass, field


@dataclass
class Step:
    number: int
    step_id: str
    teacher_line: str
    expected: str
    targets: list[str]
    target_item_ids: list[str]
    setting: str = ""
    open_answer: bool = False


@dataclass
class RecallPrompt:
    number: int
    goal_id: str
    prompt: str
    targets: list[str]
    target_item_ids: list[str]


@dataclass
class Lesson:
    source_id: str
    course_id: str
    lesson_id: str
    title: str
    introduction: str
    opening: list[str]
    opening_item_ids: list[str]
    steps: list[Step]
    recall: list[RecallPrompt]
    language: str = "uk"
    instruction_language: str = "en"
    closing: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Lesson":
        data = dict(data)
        data["steps"] = [Step(**s) for s in data["steps"]]
        data["recall"] = [RecallPrompt(**r) for r in data["recall"]]
        lesson = cls(**data)
        lesson.validate()
        return lesson

    def validate(self) -> None:
        if not all([self.source_id, self.course_id, self.lesson_id, self.language, self.instruction_language]):
            raise ValueError("lesson identities and languages are required")
        if not self.opening or not self.steps or not self.recall:
            raise ValueError("the extracted combined routine requires opening, guided steps and recall")
        known = {}
        for section, rows, key in [("steps", self.steps, "step_id"), ("recall", self.recall, "goal_id")]:
            ids = [getattr(row, key) for row in rows]
            if not all(ids) or len(set(ids)) != len(ids):
                raise ValueError(f"{section}: IDs must be nonempty and unique")
            for index, row in enumerate(rows, 1):
                if row.number != index or not row.targets or not all(row.targets):
                    raise ValueError(f"{section}: ordered numbers and nonempty targets required")
                if isinstance(row, Step) and (not row.expected or not row.teacher_line):
                    raise ValueError("guided task and teacher line are required")
                if isinstance(row, RecallPrompt) and not row.prompt:
                    raise ValueError("recall prompt is required")
        pairs = [(self.opening, self.opening_item_ids)] + [(r.targets, r.target_item_ids) for r in [*self.steps, *self.recall]]
        for lines, ids in pairs:
            if len(lines) != len(ids) or not all(lines) or not all(ids):
                raise ValueError("every practice rendering needs an explicit item ID")
            for identity, line in zip(ids, lines):
                if identity in known and known[identity] != line:
                    raise ValueError("one item ID cannot name different speech renderings")
                known[identity] = line
