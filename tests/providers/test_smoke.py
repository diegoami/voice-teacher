import importlib.util
import json
from pathlib import Path

import httpx2 as httpx


def test_bounded_smoke_uses_only_synthetic_audio_and_sanitized_artifacts(tmp_path):
    path = Path(__file__).resolve().parents[2] / "tools/voice/smoke.py"
    spec = importlib.util.spec_from_file_location("voice_smoke", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    requests = []
    def handler(request):
        requests.append(request)
        assert request.method == "POST"
        if "text-to-speech" in str(request.url): return httpx.Response(200, content=b"synthetic mp3")
        return httpx.Response(200, json={"text": "Один квиток, будь ласка.", "audio_duration_secs": 2})
    report = module.run_smoke(tmp_path / "private", "SYNTHETIC_SECRET", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert len(requests) == 2 and report["matches_plain_phrase"] is True
    assert "SYNTHETIC_SECRET" not in json.dumps(report)
    assert (tmp_path / "private/synthetic.mp3").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "private/result.json").stat().st_mode & 0o777 == 0o600
