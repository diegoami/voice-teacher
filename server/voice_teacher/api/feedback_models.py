"""Public personal-review allowlists; private engine/provider state stays private."""
from typing import Literal
from pydantic import BaseModel, Field
from .models import Revision, ID


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


class PersonalTarget(BaseModel):
    target_id: str
    observation_id: str
    form: Literal["original","preferred"]
    text: str
    meaning: str
    origin_session_id: str
    origin_turn_id: str
    language: str
    instruction_language: str
    original_source: SourceReference | None
    original_item: ItemReference | None


class Promotion(Revision):
    observation_id: str = Field(pattern=ID)
    form: Literal["original","preferred"]
    meaning: str = Field(min_length=1,max_length=500)


class Promoted(BaseModel):
    target: PersonalTarget
    revision: int
