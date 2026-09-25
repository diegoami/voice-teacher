import sys

import httpx
import pytest
from conftest import load

from stt import __main__ as cli
from stt import providers
from stt.providers import PROVIDERS, ProviderError, transcribe


def test_every_request_forces_ukrainian_and_sends_no_hints(fake_api, audio):
    seen, transport = fake_api
    with httpx.Client(transport=transport) as client:
        records = {name: transcribe(p, audio, "KEY", client) for name, p in PROVIDERS.items()}
    assert len(seen) == 4
    eleven, gpt, gpt4o, deepgram = seen

    assert eleven.headers["xi-api-key"] == "KEY"
    assert b'name="language_code"\r\n\r\nuk\r\n' in eleven.content
    assert b'name="model_id"\r\n\r\nscribe_v2\r\n' in eleven.content

    assert gpt.headers["authorization"] == "Bearer KEY"
    assert b'name="languages[]"\r\n\r\nuk\r\n' in gpt.content
    assert b'name="language"\r\n' not in gpt.content  # gpt-transcribe rejects both fields together
    assert b'name="language"\r\n\r\nuk\r\n' in gpt4o.content
    assert b'name="model"\r\n\r\ngpt-4o-transcribe\r\n' in gpt4o.content

    assert deepgram.headers["authorization"] == "Token KEY"
    assert deepgram.url.params["language"] == "uk"
    assert deepgram.url.params["model"] == "nova-3"
    assert deepgram.headers["content-type"] == "audio/mp4"

    for request in seen:
        assert b"prompt" not in request.content and b"keyterms" not in request.content
        assert b"keywords" not in request.content

    assert records["elevenlabs"]["detected_language"] == "ukr"
    assert records["openai"]["detected_language"] == "uk"
    assert records["deepgram"]["text"].startswith("Перепрошую")


def test_http_error_is_reported(audio):
    transport = httpx.MockTransport(lambda r: httpx.Response(401, json={"detail": "bad key"}))
    with httpx.Client(transport=transport) as client, pytest.raises(ProviderError, match="HTTP 401"):
        transcribe(PROVIDERS["elevenlabs"], audio, "KEY", client)


def test_openai_refuses_formats_it_cannot_read(tmp_path):
    ogg = tmp_path / "reading-1.ogg"
    ogg.write_bytes(b"OggS")
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as client:
        with pytest.raises(ProviderError, match="convert"):
            transcribe(PROVIDERS["openai"], ogg, "KEY", client)


def test_run_end_to_end(fake_api, audio, tmp_path, monkeypatch, capsys):
    """`python -m stt run`, against the fake APIs, with one provider's key missing."""
    seen, transport = fake_api
    real_client = httpx.Client
    monkeypatch.setattr(providers.httpx, "Client", lambda **kw: real_client(transport=transport))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k1")
    monkeypatch.setenv("OPENAI_API_KEY", "k2")
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    monkeypatch.setattr(cli, "load_env", lambda path: None)
    out = tmp_path / "transcripts"
    monkeypatch.setattr(sys, "argv", ["stt", "--transcripts", str(out), "run", str(audio)])

    assert cli.main() == 0
    report = capsys.readouterr().out
    assert len(seen) == 3
    assert load(out / "reading-1" / "elevenlabs.json")["text"].startswith("Перепрошую")
    assert (out / "reading-1" / "report.md").read_text(encoding="utf-8") == report

    rows = {line.split(" (")[0].strip("| "): line for line in report.splitlines() if line.startswith("| ")}
    assert "| 0.0% (0/0/0) | 0.0% | 0 (0.0%) | 0 | 32/32 | 14/14 | ukr |" in rows["elevenlabs"]
    assert "| 0.0% (0/0/0) |" in rows["openai"]  # «5» and «200» count as the words read
    assert "| 6 (" in rows["openai-4o"] and "| 29/32 | 11/14 |" in rows["openai-4o"]
    assert "Not run: deepgram (set DEEPGRAM_API_KEY)." in report
    assert "| 4 | Потім поверніть праворуч. | ✓ | ✓ | 3 err, 1 RU |" in report

    # A second run reuses the saved transcripts and makes no requests.
    capsys.readouterr()
    assert cli.main() == 0
    assert len(seen) == 3
