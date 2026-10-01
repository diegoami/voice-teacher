"""Speech services behind two small functions the server calls (tests replace them).

Scribe v2 for hearing the learner (batch, one request per turn) and ElevenLabs
Multilingual v2 for the teacher's voice. Requests as in POC 1 and POC 2.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

import httpx

STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
STT_MODEL = "scribe_v2"
TTS_VOICE = "JBFqnCBsd6RMkjVDRZzb"
TTS_MODEL = "eleven_multilingual_v2"
TTS_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{TTS_VOICE}"
TTS_FORMAT = "mp3_44100_128"

STT_USD_PER_HOUR = 0.22
TTS_USD_PER_1000_CHARS = 0.10


class ProviderError(RuntimeError):
    pass


@dataclass
class Transcript:
    text: str
    audio_seconds: float | None = None  # when the service says how long the audio was


def cache_key(text: str) -> str:
    """Names a synthesised line: the same model, voice and marked text give the same file."""
    return hashlib.sha256(f"{TTS_MODEL}|{TTS_VOICE}|{text}".encode()).hexdigest()[:32]


def _error(response: httpx.Response) -> str:
    try:
        body = response.json()
        detail = body.get("detail") or body.get("error") or body if isinstance(body, dict) else body
        if isinstance(detail, dict):
            detail = detail.get("message") or detail
    except ValueError:
        detail = response.text
    return f"HTTP {response.status_code}: " + " ".join(str(detail).split())[:300]


class ElevenLabs:
    def __init__(self, key: str | None = None, client: httpx.Client | None = None):
        self.key = key or os.environ.get("ELEVENLABS_API_KEY")
        if not self.key:
            raise RuntimeError("ELEVENLABS_API_KEY is not set (put it in .env)")
        self.client = client or httpx.Client(timeout=60)

    def transcribe(self, audio: bytes, content_type: str) -> Transcript:
        extension = "mp4" if "mp4" in content_type else "ogg" if "ogg" in content_type else \
            "mp3" if "mpeg" in content_type else "webm"
        response = self.client.post(
            STT_URL, headers={"xi-api-key": self.key},
            data={"model_id": STT_MODEL, "language_code": "uk", "tag_audio_events": "false", "diarize": "false"},
            files={"file": (f"turn.{extension}", audio, content_type.split(";")[0] or "audio/webm")})
        if response.status_code != 200:
            raise ProviderError("speech recognition failed, " + _error(response))
        raw = response.json()
        return Transcript(raw.get("text", "").strip(), raw.get("audio_duration_secs"))

    def synthesise(self, text: str) -> bytes:
        response = self.client.post(
            TTS_URL, params={"output_format": TTS_FORMAT}, headers={"xi-api-key": self.key},
            json={"text": text, "model_id": TTS_MODEL, "seed": 1})
        if response.status_code != 200:
            raise ProviderError("speech synthesis failed, " + _error(response))
        return response.content
