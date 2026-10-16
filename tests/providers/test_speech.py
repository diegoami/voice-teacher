from dataclasses import replace
import json

import httpx2 as httpx
import pytest

from voice_teacher.providers.speech import ElevenLabs, SpeechConfig, SpeechError


def provider(handler, **kwargs):
    return ElevenLabs("SYNTHETIC_KEY", client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def test_recognition_locks_language_preserves_raw_text_and_has_no_confidence():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"text": "  Зве́тки помилка  ", "audio_duration_secs": 1.25, "language_probability": .95, "words": [{"logprob": -1}]})
    service = provider(handler, timeout=7)
    result = service.transcribe(b"synthetic recording", language="uk", media_type="audio/ogg")
    assert result.text == "Зве́тки помилка" and result.audio_seconds == 1.25
    assert not hasattr(result, "confidence")
    body = seen[0].read()
    assert b'language_code"\r\n\r\nuk' in body
    assert b'scribe_v2' in body and b'tag_audio_events"\r\n\r\nfalse' in body
    assert b'no_verbatim"\r\n\r\nfalse' in body and b'keyterms' not in body
    assert seen[0].headers["xi-api-key"] == "SYNTHETIC_KEY"
    assert seen[0].extensions["timeout"]["read"] == 7


def test_synthesis_preserves_authored_stress_and_explicit_voice_settings():
    seen = []
    service = provider(lambda request: (seen.append(request), httpx.Response(200, content=b"synthetic MP3"))[1])
    text = "Оди́н квито́к, будь ла́ска."
    assert service.synthesize(text, language="uk") == b"synthetic MP3"
    sent = json.loads(seen[0].content)
    assert sent["text"] == text and sent["model_id"] == "eleven_multilingual_v2" and sent["seed"] == 1
    assert sent["voice_settings"] == service.config.definition()["voice_settings"]
    assert "JBFqnCBsd6RMkjVDRZzb" in str(seen[0].url)
    assert seen[0].url.params["output_format"] == "mp3_44100_128"


@pytest.mark.parametrize("change", [dict(synthesis_model="another-model"), dict(voice="another-voice"),
    dict(voice_settings_json='{"stability":0.6,"similarity_boost":0.75,"style":0.0,"use_speaker_boost":true,"speed":1.0}'),
    dict(pronunciation_version="authored-v2"), dict(seed=2), dict(output_format="mp3_22050_32")])
def test_cache_identity_includes_every_rendering_input(change):
    config = SpeechConfig()
    assert config.cache_key("Приві́т", "uk") != replace(config, **change).cache_key("Приві́т", "uk")
    assert config.cache_key("Приві́т", "uk") != config.cache_key("Привіт", "uk")
    assert config.cache_key("Приві́т", "uk") != config.cache_key("Приві́т", "en")
    assert "output_format" in config.definition()


@pytest.mark.parametrize("response", [httpx.Response(401, text="SYNTHETIC_SECRET /private/key"), httpx.Response(200, content=b"x" * 40)])
def test_http_error_and_oversized_output_do_not_echo_payload(response):
    service = provider(lambda request: response, max_response_bytes=20)
    with pytest.raises(SpeechError) as caught: service.synthesize("Hello", language="en")
    assert "SYNTHETIC_SECRET" not in str(caught.value) and "/private" not in str(caught.value)


def test_transport_failure_and_malformed_recognition_are_sanitized():
    def failed(request): raise httpx.ReadTimeout("SYNTHETIC_SECRET")
    with pytest.raises(SpeechError, match="operation failed"):
        provider(failed).transcribe(b"audio", language="uk")
    with pytest.raises(SpeechError, match="invalid recognition"):
        provider(lambda request: httpx.Response(200, json={"text": ["not text"]})).transcribe(b"audio", language="uk")
    with pytest.raises(ValueError): provider(failed).transcribe(b"audio", language="")
    with pytest.raises(ValueError): replace(SpeechConfig(), output_format="unknown").definition()
