import json

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from voice_teacher.__main__ import build_app
from voice_teacher.providers import Item
from voice_teacher.providers.judge import OpenRouterJudge


def test_judge_ports_structured_policy_with_explicit_model_and_bounded_call():
    seen = []
    verdict = dict(verdict="accept", on_task=True, chunk="", reply="", step=0, note="")
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(verdict)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": .001, "unsafe": "SYNTHETIC_SECRET"}})
    judge = OpenRouterJudge("SYNTHETIC_KEY", "synthetic/model", client=httpx.Client(transport=httpx.MockTransport(handler)), timeout=8)
    result = judge(Item("step", "Say hello", "Greet", ["Приві́т"]), "привіт")
    assert result.verdict.verdict == "accept" and result.usage == {"prompt_tokens": 10, "completion_tokens": 5, "cost": .001}
    body = json.loads(seen[0].content)
    assert body["model"] == "synthetic/model" and body["response_format"]["json_schema"]["strict"] is True
    assert json.loads(body["messages"][1]["content"])["targets"] == ["Приві́т"]
    assert seen[0].extensions["timeout"]["read"] == 8


@pytest.mark.parametrize("status,body", [(429, {"error": "SYNTHETIC_SECRET"}), (200, {"choices": []}),
    (200, {"choices": [{"finish_reason": "length", "message": {"content": "SYNTHETIC_SECRET"}}]})])
def test_judge_failures_are_sanitized_and_do_not_retry_implicitly(status, body):
    calls = []
    def handler(request): calls.append(request); return httpx.Response(status, json=body)
    judge = OpenRouterJudge("SYNTHETIC_KEY", "synthetic/model", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(RuntimeError) as caught: judge(Item("step", "Say hello", "Greet", ["Приві́т"]), "answer")
    assert "SYNTHETIC_SECRET" not in str(caught.value) and len(calls) == 1


def test_server_composition_requires_explicit_settings_without_live_calls(tmp_path):
    operator = "synthetic-operator-" + "x" * 32
    with pytest.raises(ValueError): OpenRouterJudge("key", "")
    app = build_app(tmp_path / "data", operator_token=operator, speech_key="SYNTHETIC_SPEECH",
                    judge_key="SYNTHETIC_JUDGE", judge_model="synthetic/model", origin="http://teacher.test")
    client = TestClient(app, base_url="http://teacher.test")
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/api/v1/sources").status_code == 401
