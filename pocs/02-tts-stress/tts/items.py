"""The stress items and the variants every item is rendered in."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

STRESS = "́"
LINE = re.compile(r"^(\d+)\.\s+(.*?)\s*<!--\s*targets:\s*(.*?)\s*-->\s*$")


def plain(text: str) -> str:
    return unicodedata.normalize("NFC", text).replace(STRESS, "")


@dataclass(frozen=True)
class Item:
    number: int
    marked: str  # with stress marks
    targets: tuple[str, ...]  # words whose stress is judged, with marks

    @property
    def plain(self) -> str:
        return plain(self.marked)


def load_items(path: Path) -> list[Item]:
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = LINE.match(line)
        if match:
            items.append(Item(int(match.group(1)), match.group(2), tuple(match.group(3).split())))
    return items


@dataclass(frozen=True)
class Variant:
    name: str
    provider: str  # "elevenlabs" | "openai"
    model: str
    marks: bool  # send the text with stress marks

    def text(self, item: Item) -> str:
        return item.marked if self.marks else item.plain


VARIANTS = [
    Variant(f"{short}-{'marks' if marks else 'plain'}", provider, model, marks)
    for short, provider, model in [
        ("el-v2", "elevenlabs", "eleven_multilingual_v2"),
        ("el-v3", "elevenlabs", "eleven_v3"),
        ("el-flash", "elevenlabs", "eleven_flash_v2_5"),
        ("openai", "openai", "gpt-4o-mini-tts"),
    ]
    for marks in (False, True)
]
