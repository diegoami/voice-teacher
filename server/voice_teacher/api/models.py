"""Public API allowlists. Never return a private session/curriculum directly."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

ID = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Pair(Input):
    code: str = Field(min_length=32, max_length=256)


class PairCode(Input):
    learner_id: str = Field(pattern=ID)
    label: str = Field(min_length=1, max_length=100)


class Learner(Input):
    level: str = Field(min_length=1, max_length=100)


class SourceConfig(Input):
    source_id: str = Field(pattern=ID)
    name: str = Field(min_length=1, max_length=100)
    checkout: str = Field(min_length=1, max_length=4096)
    subdirectory: str = "."
    adapter: Literal["canonical_json", "legacy"] = "canonical_json"
    manifest: str = "voice-teacher.json"
    mapping: dict | None = None
    allow_dirty: bool = False


class Start(Input):
    session_id: str = Field(pattern=ID)
    source_id: str | None = Field(default=None, pattern=ID)
    course_id: str | None = Field(default=None, pattern=ID)
    lesson_id: str | None = Field(default=None, pattern=ID)
    mode: Literal["guided_conversation", "repetition", "free_conversation"] = "guided_conversation"
    activity: Literal["combined", "first_sitting", "second_sitting"] = "combined"
    item_ids: list[str] | None = Field(default=None, min_length=1, max_length=6)
    queue_event_ids: list[str] | None = Field(default=None, min_length=1, max_length=2)
    personal_target_ids: list[str] | None = Field(default=None, min_length=1, max_length=2)
    recall_before_model: bool = False
    routine: Literal["guided", "combined"] = "guided"
    cards: bool = True
    spoken_tasks: bool = True
    max_goals: int = Field(default=3, ge=1, le=6)
    topic: str | None = Field(default=None, min_length=1, max_length=500)
    correction_style: Literal["light_immediate", "end_of_session"] = "light_immediate"
    language: str = Field(default="uk", pattern=r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
    instruction_language: str = Field(default="en", pattern=r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


class Revision(Input):
    request_id: str = Field(pattern=ID)
    expected_revision: int = Field(ge=0)


class Turn(Revision):
    text: str = Field(min_length=1, max_length=8000)

    @field_validator("text")
    @classmethod
    def nonempty(cls, value):
        if not value.strip(): raise ValueError("nonempty text required")
        return value


class Control(Revision):
    operation: Literal["pause", "resume", "finish"]


class LessonCompletion(Revision):
    source_id: str = Field(pattern=ID)
    course_id: str = Field(pattern=ID)
    lesson_id: str = Field(pattern=ID)
    version_id: str = Field(pattern=ID)
    completed: bool


class LessonCompletionResult(BaseModel):
    request_id: str
    decision_id: str
    revision: int
    completed: bool


class Teacher(BaseModel):
    text: str
    kind: str


class Activity(BaseModel):
    activity_id: str
    position: int
    total: int
    complete: bool


class Presentation(BaseModel):
    session_id: str
    request_id: str | None
    revision: int
    status: Literal["active", "paused", "finished"]
    done: bool
    card: str | None
    teacher: list[Teacher]
    audio_ids: list[str]
    activity: Activity | None = None


class Source(BaseModel):
    source_id: str
    name: str
    version_id: str | None
    available: bool


class Course(BaseModel):
    course_id: str
    title: str
    language: str
    instruction_language: str


class Lesson(BaseModel):
    lesson_id: str
    title: str
    authored_modes: list[str]
    available_modes: list[str]


class TranscriptTurn(BaseModel):
    turn_id: str
    role: Literal["learner", "teacher"]
    text: str


class ErrorBody(BaseModel):
    code: str
    message: str


class Error(BaseModel):
    error: ErrorBody


class Identity(BaseModel):
    learner_id: str


class Paired(Identity):
    token: str
    client_id: str
    expires_at: float


class Code(BaseModel):
    code: str
    expires_at: float


class RecognitionView(BaseModel):
    request_id: str
    status: Literal["accepted", "recognized", "empty", "failed"]
    text: str | None
    reported_problem: bool


class Report(Input):
    pass


class Reported(BaseModel):
    status: Literal["reported"]
    revision: int


class SourceRevision(BaseModel):
    commit: str | None
    content_sha256: str
    dirty: bool


class SourceReference(BaseModel):
    source_id: str
    course_id: str
    lesson_id: str
    revision: SourceRevision


class ItemReference(BaseModel):
    source_id: str
    course_id: str
    item_id: str
    item_revision: int


class Provenance(BaseModel):
    original_source: SourceReference | None
    original_item: ItemReference | None
    practice_source: SourceReference | None
    origin_session_id: str
    origin_turn_id: str


class Assistance(BaseModel):
    kind: Literal["none", "task_card", "cue", "model", "correction"]
    help_level: int
    target_exposed: bool


class ItemCoverage(BaseModel):
    lesson_id: str
    title: str
    required_items: int
    covered_items: int
    covered: bool
    completed: bool = False
    learner_completed: bool | None = None


class CourseProgress(BaseModel):
    source_id: str
    course_id: str
    content_sha256: str
    title: str
    required_items: int
    covered_items: int
    next_lesson_id: str | None
    lessons: list[ItemCoverage]
    version_id: str | None = None
    decision_revision: int = 0


class LegacyPosition(BaseModel):
    source_id: str
    course_id: str
    covered_lesson_ids: list[str]
    next_lesson_id: str | None


class HistorySession(BaseModel):
    session_id: str
    title: str
    mode: Literal["guided_conversation", "repetition", "free_conversation"]
    source: SourceReference | None
    status: Literal["created", "active", "paused", "finished"]
    updated_at: str
    accepted_turns: int
    locally_saved: int
    exported: int
    pushed: int


class BackupStatus(BaseModel):
    configured: bool
    locally_saved: int
    exported: int
    pushed: int
    last_push_at: str | None
    error: str | None


class ProgressView(BaseModel):
    criterion: str
    courses: list[CourseProgress]
    legacy_positions: list[LegacyPosition]
    sessions: list[HistorySession]
    more_sessions: bool
    sync: BackupStatus


class EvidenceView(BaseModel):
    event_id: str
    session_id: str
    turn: TranscriptTurn
    outcome: Literal["independent", "repeated", "cued", "modelled_repeated", "corrected_repeated", "needs_turn", "skipped", "observed"]
    attempt: str
    preferred: str | None
    reason: str | None
    recognition_uncertain: bool
    correction: bool
    assistance: Assistance
    provenance: Provenance
    superseded: bool


class EvidencePage(BaseModel):
    session_id: str
    rows: list[EvidenceView]
    next_offset: int | None


class Receipt(BaseModel):
    request_id: str
    status: Literal["pending", "ready", "cancelled"]
    revision: int | None = Field(default=None, ge=0)


class GitSourceConfig(Input):
    name: str = Field(min_length=1,max_length=100)
    remote: str = Field(min_length=1,max_length=4096)
    ref_kind: Literal["branch","tag"] = "branch"
    ref_name: str = Field(default="main",min_length=1,max_length=200)
    subdirectory: str = "."
    adapter: Literal["canonical_json","legacy"] = "canonical_json"
    manifest: str = "voice-teacher.json"
    mapping: dict | None = None
