"""Untrusted structured feedback must not fabricate learner or item provenance."""
from copy import deepcopy
import json

import httpx2 as httpx
import pytest
from voice_teacher.practice.free_feedback import validate_response
from voice_teacher.providers.feedback import OpenRouterFeedback


CONTEXT={"language":"uk","instruction_language":"en","turn":{"turn_id":"actual-turn","text":"Я їду потяг."},"items":[],"recognition_uncertain":False}
CLAIM={"turn_id":"actual-turn","original":"Я їду потяг.","preferred":"Я їду потягом.","reason":"Use the instrumental form for transport.","item_id":None}


def test_post_attempt_feedback_preserves_real_wording_and_omits_unrelated_context():
    seen=[]
    def transport(request):
        body=json.loads(request.content);seen.append(body)
        assert "actual-turn" in body["messages"][1]["content"]
        assert "synthetic-key" not in str(body)
        assert not body.get("tools") and body["plugins"]==[] and body["max_tokens"]==512
        return httpx.Response(200,json={"choices":[{"finish_reason":"stop","message":{"content":json.dumps({"observations":[CLAIM]})}}]})
    p=OpenRouterFeedback("synthetic-key","explicit-model",client=httpx.Client(transport=httpx.MockTransport(transport)))
    reply=p(CONTEXT)
    assert reply.observations==[CLAIM] and reply.usage=={}
    assert p.identity["model"]=="explicit-model" and len(seen)==1


@pytest.mark.parametrize("mutation",["turn","wording","item","extra","duplicate","missing_reason","identical","too_many"])
def test_wrong_references_and_unsupported_claim_shapes_are_rejected(mutation):
    value={"observations":[deepcopy(CLAIM)]};row=value["observations"][0]
    if mutation=="turn":row["turn_id"]="invented-other-learner-turn"
    elif mutation=="wording":row["original"]="Words never spoken"
    elif mutation=="item":row["item_id"]="invented-item"
    elif mutation=="extra":row["mastery"]=100
    elif mutation=="duplicate":value["observations"].append(deepcopy(row))
    elif mutation=="missing_reason":row["reason"]=None
    elif mutation=="identical":row["preferred"]=row["original"]
    elif mutation=="too_many":value["observations"]*=4
    with pytest.raises(ValueError):validate_response(CONTEXT,value)


def test_known_item_attribution_requires_a_unique_explicit_offered_rendering():
    context=deepcopy(CONTEXT)
    context["items"]=[{"item_id":"ticket","display":"Я їду потягом.","speech":"Я їду потягом.","meaning":"I travel by train"}]
    row={**CLAIM,"item_id":"ticket"}
    assert validate_response(context,{"observations":[row]})["observations"][0]["item_id"]=="ticket"
    context["items"].append({**context["items"][0],"item_id":"another-item"})
    with pytest.raises(ValueError,match="ambiguous"):validate_response(context,{"observations":[row]})


@pytest.mark.parametrize("bad",["tools","truncated","extra","oversized","http"])
def test_provider_failures_are_sanitized_and_never_accepted_as_feedback(bad):
    def transport(request):
        value={"observations":[CLAIM]}
        if bad=="extra":value["tool"]="write curriculum"
        message={"content":json.dumps(value)}
        if bad=="tools":message["tool_calls"]=[{"name":"execute"}]
        if bad=="oversized":return httpx.Response(200,content=b"x"*65537)
        if bad=="http":return httpx.Response(401,text="synthetic-key private body")
        return httpx.Response(200,json={"choices":[{"finish_reason":"length" if bad=="truncated" else "stop","message":message}]})
    p=OpenRouterFeedback("synthetic-key","explicit-model",client=httpx.Client(transport=httpx.MockTransport(transport)))
    with pytest.raises(RuntimeError) as error:p(CONTEXT)
    assert "synthetic-key" not in str(error.value) and "private body" not in str(error.value)


def test_explicit_feedback_reasoning_is_sent_and_pinned_without_changing_legacy_defaults():
    seen = []
    def transport(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": '{"observations":[]}'}}]})
    client = httpx.Client(transport=httpx.MockTransport(transport))
    old = OpenRouterFeedback("key", "model", client=client)
    new = OpenRouterFeedback("key", "model", reasoning_effort="minimal", client=client)
    assert old(CONTEXT).observations == new(CONTEXT).observations == []
    assert "reasoning" not in seen[0] and seen[1]["reasoning"] == {"effort": "minimal"}
    assert old.identity["policy_version"] == 1 and new.identity["policy_version"] == 2
