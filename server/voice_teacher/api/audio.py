"""Authenticated audio transport boundary. T10 supplies durable providers/cache."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Audio:
    data: bytes
    media_type: str


class AudioGateway(Protocol):
    def submit(self, learner: str, session: str, request: str, *, expected_revision: int,
               data: bytes, media_type: str) -> dict: ...
    def read(self, learner: str, session: str, audio_id: str) -> Audio | None: ...
