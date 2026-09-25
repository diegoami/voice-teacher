import json
from pathlib import Path

import httpx
import pytest

from stt.score import reading_list

HERE = Path(__file__).resolve().parents[1]
READING = HERE / "reading_list.md"
LEARNUKRAINIAN = HERE.parents[2] / "learnukrainian" / "pimsleur-review" / "voice-sessions"


@pytest.fixture
def sentences():
    return reading_list(READING)


def read_aloud(sentences) -> str:
    """The reading list as a perfect recogniser would write it."""
    return " ".join(s.plain for s in sentences)


def russianised(sentences) -> str:
    """The reading list with lines 1, 4 and 7 in the Russian spelling a recogniser might produce."""
    swap = {
        1: "Извините, где находится станция метро?",
        4: "Потом поверните направо.",
        7: "Нет, минут пять пешком.",
    }
    return " ".join(swap.get(s.number, s.plain) for s in sentences)


@pytest.fixture
def fake_api(sentences):
    """A stand-in for the three vendors' HTTP APIs; records every request it gets."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        host = request.url.host
        if host == "api.elevenlabs.io":
            return httpx.Response(200, json={"text": read_aloud(sentences), "language_code": "ukr",
                                             "language_probability": 0.99, "words": []})
        if host == "api.openai.com":
            if b"gpt-4o-transcribe" in request.content:
                return httpx.Response(200, json={"text": russianised(sentences)})
            text = read_aloud(sentences).replace("п'ять", "5").replace("двісті", "200")
            return httpx.Response(200, json={"text": text, "languages": [{"code": "uk"}]})
        if host == "api.deepgram.com":
            text = read_aloud(sentences[:-1])  # the last sentence is lost
            return httpx.Response(200, json={"results": {"channels": [{"alternatives": [
                {"transcript": text, "confidence": 0.9}]}]}})
        return httpx.Response(404)

    return seen, httpx.MockTransport(handler)


@pytest.fixture
def audio(tmp_path: Path) -> Path:
    path = tmp_path / "reading-1.m4a"
    path.write_bytes(b"\x00\x00\x00\x18ftypM4A not really audio")
    return path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
