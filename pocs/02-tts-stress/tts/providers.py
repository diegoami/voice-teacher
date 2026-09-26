"""Text-to-speech requests. Plain HTTP so the tests can replace the network."""

from __future__ import annotations

import os
import time

import httpx

from .items import Variant

# A premade ElevenLabs voice every account can use without the voices_read
# permission; the stress comes from the model, not the voice.
ELEVENLABS_VOICE = "JBFqnCBsd6RMkjVDRZzb"
OPENAI_VOICE = "coral"
OPENAI_INSTRUCTIONS = "Speak Ukrainian clearly, at the pace of a language teacher."
OPENAI_MARKS = " An acute accent after a vowel marks the stressed syllable; do not pronounce the mark."
KEYS = {"elevenlabs": "ELEVENLABS_API_KEY", "openai": "OPENAI_API_KEY"}


class ProviderError(Exception):
    pass


def key_for(provider: str) -> str | None:
    return os.environ.get(KEYS[provider]) or None


def _request(client: httpx.Client, variant: Variant, text: str, key: str) -> httpx.Response:
    if variant.provider == "elevenlabs":
        body = {"text": text, "model_id": variant.model, "seed": 1}
        if variant.model == "eleven_flash_v2_5":
            body["language_code"] = "uk"  # Flash takes a language to enforce; the others detect it
        return client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE}",
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": key},
            json=body,
        )
    instructions = OPENAI_INSTRUCTIONS + (OPENAI_MARKS if variant.marks else "")
    return client.post(
        "https://api.openai.com/v1/audio/speech",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": variant.model, "voice": OPENAI_VOICE, "input": text,
              "instructions": instructions, "response_format": "mp3"},
    )


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return " ".join(response.text.split())[:300]
    detail = body.get("detail") or body.get("error") or body if isinstance(body, dict) else body
    if isinstance(detail, dict):
        detail = detail.get("message") or detail
    return " ".join(str(detail).split())[:300]


def synthesise(variant: Variant, text: str, key: str, client: httpx.Client | None = None) -> tuple[bytes, float]:
    """Return the MP3 bytes and the request time in seconds."""
    own = client is None
    client = client or httpx.Client(timeout=120)
    try:
        started = time.monotonic()
        response = _request(client, variant, text, key)
        seconds = round(time.monotonic() - started, 2)
    finally:
        if own:
            client.close()
    if response.status_code >= 400:
        raise ProviderError(f"HTTP {response.status_code}: {_error_message(response)}")
    return response.content, seconds
