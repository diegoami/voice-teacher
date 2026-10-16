"""Configurable ElevenLabs transport; no confidence inference or error payload echo."""
from dataclasses import dataclass
import hashlib
import json
import math
import re

import httpx2 as httpx

from schemas.validate import canonical_json
from . import Recognition


class SpeechError(RuntimeError):
    pass


@dataclass(frozen=True)
class SpeechConfig:
    recognition_model: str = "scribe_v2"
    synthesis_model: str = "eleven_multilingual_v2"
    voice: str = "JBFqnCBsd6RMkjVDRZzb"
    output_format: str = "mp3_44100_128"
    pronunciation_version: str = "authored-stress-v1"
    voice_settings_json: str = '{"similarity_boost":0.75,"stability":0.5,"style":0.0,"use_speaker_boost":true,"speed":1.0}'
    seed: int = 1

    def definition(self):
        for value in (self.recognition_model, self.synthesis_model, self.voice, self.pronunciation_version):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", value): raise ValueError("invalid speech configuration")
        if self.output_format not in {"mp3_44100_128", "mp3_22050_32"}: raise ValueError("unsupported MP3 output format")
        if type(self.seed) is not int or not 0 <= self.seed < 2**32: raise ValueError("invalid synthesis seed")
        settings = json.loads(self.voice_settings_json)
        if not isinstance(settings, dict) or set(settings) != {"stability", "similarity_boost", "style", "use_speaker_boost", "speed"}:
            raise ValueError("explicit voice settings required")
        for key in ("stability", "similarity_boost", "style"):
            if type(settings[key]) not in {int, float} or not math.isfinite(settings[key]) or not 0 <= settings[key] <= 1: raise ValueError("invalid voice settings")
        if type(settings["use_speaker_boost"]) is not bool or type(settings["speed"]) not in {int, float} or not .7 <= settings["speed"] <= 1.2:
            raise ValueError("invalid voice settings")
        return dict(provider="elevenlabs", recognition_model=self.recognition_model, synthesis_model=self.synthesis_model,
                    voice=self.voice, output_format=self.output_format, pronunciation_version=self.pronunciation_version,
                    voice_settings=settings, seed=self.seed)

    def cache_key(self, text, language):
        if not isinstance(text, str) or not text.strip(): raise ValueError("nonempty speech text required")
        return hashlib.sha256(canonical_json({"speech": self.definition(), "text": text, "language": language}).encode()).hexdigest()


class ElevenLabs:
    def __init__(self, key, *, config=None, client=None, timeout=30, max_response_bytes=16 * 1024 * 1024):
        if not isinstance(key, str) or not key: raise ValueError("selected ElevenLabs credential is missing")
        if type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 120: raise ValueError("invalid speech timeout")
        if type(max_response_bytes) is not int or max_response_bytes <= 0: raise ValueError("invalid response byte limit")
        self._key, self.config, self.timeout = key, config or SpeechConfig(), timeout
        self.config.definition()
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=False)
        self.max_response_bytes = max_response_bytes

    def _post(self, path, **kwargs):
        try:
            with self.client.stream("POST", "https://api.elevenlabs.io/v1/" + path,
                                    headers={"xi-api-key": self._key}, timeout=self.timeout, follow_redirects=False, **kwargs) as response:
                if response.status_code != 200: raise SpeechError(f"speech provider rejected the request (HTTP {response.status_code})")
                parts, size = [], 0
                for part in response.iter_bytes():
                    size += len(part)
                    if size > self.max_response_bytes: raise SpeechError("speech provider response exceeds limit")
                    parts.append(part)
                return b"".join(parts)
        except SpeechError: raise
        except Exception: raise SpeechError("speech provider operation failed") from None

    def transcribe(self, audio, *, language, media_type="audio/webm"):
        if not isinstance(language, str) or not re.fullmatch(r"[a-z]{2,3}", language): raise ValueError("explicit recognition language required")
        extensions = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/wav": "wav", "audio/mp4": "mp4", "audio/mpeg": "mp3"}
        if media_type not in extensions or not isinstance(audio, bytes) or not audio or len(audio) > 8 * 1024 * 1024: raise SpeechError("invalid recording")
        raw = self._post("speech-to-text", data={"model_id": self.config.recognition_model, "language_code": language,
            "tag_audio_events": "false", "diarize": "false", "no_verbatim": "false"},
            files={"file": ("turn." + extensions[media_type], audio, media_type)})
        try:
            value = json.loads(raw)
            text, duration = value["text"], value.get("audio_duration_secs")
            if not isinstance(text, str) or len(text) > 8000: raise ValueError()
            if duration is not None and (type(duration) not in {int, float} or not math.isfinite(duration) or duration < 0): raise ValueError()
            return Recognition(text.strip(), duration)
        except Exception: raise SpeechError("invalid recognition response") from None

    def synthesize(self, text, *, language):
        # The POC has mixed English instructions/Ukrainian models. Preserve that
        # multilingual rendering; recognition alone locks the learner language.
        config = self.config.definition()
        if not isinstance(text, str) or not text.strip() or len(text) > 10000: raise SpeechError("invalid speech text")
        data = self._post("text-to-speech/" + self.config.voice, params={"output_format": self.config.output_format},
                         json={"text": text, "model_id": self.config.synthesis_model, "voice_settings": config["voice_settings"], "seed": self.config.seed})
        if not data: raise SpeechError("empty synthesis response")
        return data
