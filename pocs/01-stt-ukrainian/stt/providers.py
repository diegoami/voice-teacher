"""Batch speech-to-text requests with the language forced to Ukrainian.

Plain HTTP (httpx) rather than the vendors' SDKs, so the requests are visible
and the tests can replace the network. No provider gets a prompt, keywords or
any other hint about the text: only the language.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

MEDIA_TYPES = {
    ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".mp3": "audio/mpeg", ".mpeg": "audio/mpeg",
    ".mpga": "audio/mpeg", ".wav": "audio/wav", ".webm": "audio/webm", ".ogg": "audio/ogg",
    ".opus": "audio/ogg", ".flac": "audio/flac", ".aac": "audio/aac", ".amr": "audio/amr",
    ".3gp": "audio/3gpp",
}
OPENAI_FORMATS = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"}
OPENAI_MAX_BYTES = 25 * 1024 * 1024


class ProviderError(Exception):
    pass


@dataclass(frozen=True)
class Provider:
    name: str
    model: str
    key_env: str
    request: Callable[[httpx.Client, Path, str, str], httpx.Response]
    text: Callable[[dict], str]
    language: Callable[[dict], str | None]

    def key(self) -> str | None:
        return os.environ.get(self.key_env) or None


def _media_type(path: Path) -> str:
    return MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _elevenlabs(client: httpx.Client, audio: Path, key: str, model: str) -> httpx.Response:
    with audio.open("rb") as fh:
        return client.post(
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": key},
            data={"model_id": model, "language_code": "uk", "tag_audio_events": "false",
                  "diarize": "false"},
            files={"file": (audio.name, fh, _media_type(audio))},
        )


def _openai_check(audio: Path) -> None:
    if audio.suffix.lower() not in OPENAI_FORMATS:
        raise ProviderError(f"OpenAI does not accept {audio.suffix} files; convert to .m4a or .wav first")
    if audio.stat().st_size > OPENAI_MAX_BYTES:
        raise ProviderError("OpenAI accepts at most 25 MB per file")


def _openai(client: httpx.Client, audio: Path, key: str, model: str) -> httpx.Response:
    _openai_check(audio)
    # gpt-transcribe takes a list of expected languages and rejects the older
    # singular field; the gpt-4o models take the singular one.
    language = {"languages[]": ["uk"]} if model == "gpt-transcribe" else {"language": "uk"}
    with audio.open("rb") as fh:
        return client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            data={"model": model, "response_format": "json", **language},
            files={"file": (audio.name, fh, _media_type(audio))},
        )


def _deepgram(client: httpx.Client, audio: Path, key: str, model: str) -> httpx.Response:
    return client.post(
        "https://api.deepgram.com/v1/listen",
        params={"model": model, "language": "uk", "punctuate": "true", "smart_format": "false"},
        headers={"Authorization": f"Token {key}", "Content-Type": _media_type(audio)},
        content=audio.read_bytes(),
    )


def _deepgram_text(raw: dict) -> str:
    return raw["results"]["channels"][0]["alternatives"][0]["transcript"]


def _openai_language(raw: dict) -> str | None:
    if "languages" in raw:
        return ",".join(item.get("code", "?") for item in raw["languages"]) or None
    return raw.get("language")


PROVIDERS = {
    p.name: p
    for p in [
        Provider("elevenlabs", "scribe_v2", "ELEVENLABS_API_KEY", _elevenlabs,
                 lambda raw: raw["text"], lambda raw: raw.get("language_code")),
        Provider("openai", "gpt-transcribe", "OPENAI_API_KEY", _openai,
                 lambda raw: raw["text"], _openai_language),
        Provider("openai-4o", "gpt-4o-transcribe", "OPENAI_API_KEY", _openai,
                 lambda raw: raw["text"], _openai_language),
        Provider("deepgram", "nova-3", "DEEPGRAM_API_KEY", _deepgram,
                 _deepgram_text, lambda raw: None),
    ]
}


def _error_message(response: httpx.Response) -> str:
    """The vendor's one-line error message, or the start of the body."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        detail = body.get("error") or body.get("detail") or body.get("err_msg") or body
        if isinstance(detail, dict):
            detail = detail.get("message") or detail
        return " ".join(str(detail).split())[:300]
    return " ".join(response.text.split())[:300]


def transcribe(provider: Provider, audio: Path, key: str, client: httpx.Client | None = None) -> dict:
    """Send one file; return a record with the raw response and the text."""
    own = client is None
    client = client or httpx.Client(timeout=600)
    try:
        started = time.monotonic()
        response = provider.request(client, audio, key, provider.model)
        seconds = round(time.monotonic() - started, 1)
    finally:
        if own:
            client.close()
    if response.status_code >= 400:
        raise ProviderError(f"HTTP {response.status_code}: {_error_message(response)}")
    raw = response.json()
    return {
        "provider": provider.name,
        "model": provider.model,
        "audio": audio.name,
        "seconds": seconds,
        "detected_language": provider.language(raw),
        "text": provider.text(raw),
        "response": raw,
    }
