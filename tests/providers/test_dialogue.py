from copy import deepcopy
import json
import math

import httpx2 as httpx
import pytest

from voice_teacher.providers.dialogue import OpenRouterDialogue, DialogueReply, SYSTEM, validate_context


def context():
    return {"language": "uk", "instruction_language": "en", "correction_style": "light_immediate",
        "learner_profile": {"level": "A2"}, "curriculum": {"topic": "Train travel", "lesson_title": "Tickets", "goals": ["Ask a question"]},
        "history": [{"role": "teacher", "text": "Поговорімо."}], "learner_turn": "Я люблю потяги."}


def response(text="Куди ви подорожуєте?"):
    return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"text": text})}}]}


def test_explicit_dialogue_model_strict_text_only_context_and_bounded_http_request():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={**response(), "usage": {"prompt_tokens": 10, "completion_tokens": 6, "cost": .002, "unsafe": "SYNTHETIC_PRIVATE_PAYLOAD"}})
    provider = OpenRouterDialogue("SYNTHETIC_KEY", "synthetic/model", timeout=7, client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = provider(context())
    assert result.text == "Куди ви подорожуєте?" and result.usage == {"prompt_tokens": 10, "completion_tokens": 6, "cost": .002}
    body = json.loads(seen[0].content)
    assert body["model"] == "synthetic/model" and body["max_completion_tokens"] == 256
    assert body["messages"][0] == {"role": "system", "content": SYSTEM}
    assert json.loads(body["messages"][1]["content"]) == context()
    assert set(body["response_format"]["json_schema"]["schema"]["properties"]) == {"text"}
    assert body["response_format"]["json_schema"]["strict"] and body["provider"]["require_parameters"]
    assert "tools" not in body and body["plugins"] == [] and body["stream"] is False
    assert "SYNTHETIC_KEY" not in json.dumps(body)
    assert seen[0].extensions["timeout"]["read"] == 7
    assert seen[0].url == "https://openrouter.ai/api/v1/chat/completions" and len(seen) == 1


@pytest.mark.parametrize("problem", ["rate", "redirect", "length", "tools", "function", "refusal", "extra", "empty", "long", "json", "bytes"])
def test_provider_failure_is_sanitized_and_never_retried_implicitly(problem):
    calls = []
    def handler(request):
        calls.append(request); value = response(); status = 200
        if problem == "rate": status = 429; value = {"error": "SYNTHETIC_SECRET"}
        elif problem == "redirect": return httpx.Response(302, headers={"Location": "https://untrusted.invalid/SYNTHETIC_SECRET"})
        elif problem == "length": value["choices"][0]["finish_reason"] = "length"
        elif problem == "tools": value["choices"][0]["message"]["tool_calls"] = [{"function": {"name": "SYNTHETIC_SECRET"}}]
        elif problem == "function": value["choices"][0]["message"]["function_call"] = {"name": "SYNTHETIC_SECRET"}
        elif problem == "refusal": value["choices"][0]["message"]["refusal"] = "SYNTHETIC_SECRET"
        elif problem == "extra": value["choices"][0]["message"]["content"] = json.dumps({"text": "SYNTHETIC_SECRET", "stop": True})
        elif problem == "empty": value = response(" ")
        elif problem == "long": value = response("SYNTHETIC_SECRET" * 100)
        elif problem == "json": return httpx.Response(200, content=b"not json SYNTHETIC_SECRET")
        elif problem == "bytes": return httpx.Response(200, content=b"SYNTHETIC_SECRET" * 10000)
        return httpx.Response(status, json=value)
    p = OpenRouterDialogue("SYNTHETIC_KEY", "synthetic/model", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(RuntimeError) as caught: p(context())
    assert "SYNTHETIC_SECRET" not in str(caught.value) and len(calls) == 1


@pytest.mark.parametrize("change", ["other-profile", "other-session", "too-many-history", "history-bytes", "tool-role", "long-turn"])
def test_context_allowlist_and_history_budgets_reject_extra_authority_before_network(change):
    value = context()
    if change == "other-profile": value["learner_profile"]["private_note"] = "PRIVATE"
    elif change == "other-session": value["other_sessions"] = ["PRIVATE"]
    elif change == "too-many-history": value["history"] *= 9
    elif change == "history-bytes": value["history"][0]["text"] = "x" * 12001
    elif change == "tool-role": value["history"][0]["role"] = "system"
    elif change == "long-turn": value["learner_turn"] = "x" * 8001
    calls = []
    p = OpenRouterDialogue("SYNTHETIC_KEY", "synthetic/model", client=httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r))))
    with pytest.raises(ValueError): p(value)
    assert calls == []


def test_unknown_usage_remains_unknown_and_invalid_config_never_calls_provider():
    p = OpenRouterDialogue("SYNTHETIC_KEY", "synthetic/model", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response()))))
    assert p(context()).usage == {}
    for kwargs in [dict(key="", model="model"), dict(key="key", model=""), dict(key="key", model="model", timeout=math.inf), dict(key="key", model="model", max_reply_tokens=0)]:
        with pytest.raises(ValueError): OpenRouterDialogue(**kwargs)
    for text in ["", " ", "x" * 1201]:
        with pytest.raises(ValueError): DialogueReply(text, 0, {})


def test_optional_dialogue_configuration_does_not_make_network_calls_at_composition(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from voice_teacher.__main__ import build_app
    def forbidden(*args, **kwargs): raise AssertionError("composition must not call a provider")
    monkeypatch.setattr(httpx.Client, "stream", forbidden)
    app = build_app(tmp_path / "data", operator_token="synthetic-operator-" + "x" * 32,
        speech_key="SYNTHETIC_SPEECH", judge_key="SYNTHETIC_JUDGE", judge_model="synthetic/judge",
        dialogue_model="synthetic/dialogue", origin="http://teacher.test")
    assert TestClient(app, base_url="http://teacher.test").get("/healthz").json() == {"status": "ok"}


def test_explicit_reasoning_effort_leaves_the_small_budget_for_a_complete_reply():
    def handler(request):
        body = json.loads(request.content)
        # Reproduces the observed provider boundary without a paid call.
        value = response()
        if body.get("reasoning") != {"effort": "minimal"}:
            value["choices"][0].update(finish_reason="length")
            value["choices"][0]["message"]["content"] = ""
        assert body["max_completion_tokens"] == 512
        return httpx.Response(200, json=value)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    legacy = OpenRouterDialogue("key", "synthetic/model", max_reply_tokens=512, client=client)
    with pytest.raises(RuntimeError):
        legacy(context())
    configured = OpenRouterDialogue("key", "synthetic/model", max_reply_tokens=512,
                                    reasoning_effort="minimal", client=client)
    assert configured(context()).text == "Куди ви подорожуєте?"
    assert configured.identity == {**legacy.identity, "policy_version": 2, "reasoning_effort": "minimal"}


def test_reasoning_identity_is_closed_versioned_and_preserves_legacy_capsules():
    from voice_teacher.providers.dialogue import provider_identity
    old = OpenRouterDialogue("key", "model").identity
    assert provider_identity(old) == old and old["policy_version"] == 1
    new = {**old, "policy_version": 2, "reasoning_effort": "minimal"}
    assert provider_identity(new) == new
    for bad in [{**new, "policy_version": 1}, {**old, "policy_version": 2},
                {**new, "reasoning_effort": "automatic"}, {**new, "reasoning_effort": []},
                {**new, "reasoning_effort": None}, {**new, "hidden_config": True}]:
        with pytest.raises(ValueError):
            provider_identity(bad)


def test_server_pins_explicit_effort_for_both_free_roles_without_network(tmp_path, monkeypatch):
    from voice_teacher.__main__ import build_app
    def forbidden(*args, **kwargs):
        raise AssertionError("composition must not call a provider")
    monkeypatch.setattr(httpx.Client, "stream", forbidden)
    import importlib
    module = importlib.import_module("voice_teacher.__main__")
    monkeypatch.setattr(module, "create_app", lambda store, coordinator, **kwargs: coordinator)
    coordinator = build_app(tmp_path / "data", operator_token="operator-" + "x" * 40,
                    speech_key="speech", judge_key="judge", judge_model="judge",
                    dialogue_model="dialogue", free_reasoning_effort="minimal", dialogue_reply_tokens=512)
    assert coordinator.dialogue.identity["reasoning_effort"] == "minimal"
    assert coordinator.dialogue.identity["max_reply_tokens"] == 512
    assert coordinator.feedback.identity["reasoning_effort"] == "minimal"
    with pytest.raises(ValueError, match="requires explicitly configured"):
        build_app(tmp_path / "other", operator_token="operator-" + "x" * 40,
                  speech_key="speech", judge_key="judge", judge_model="judge", free_reasoning_effort="minimal")
