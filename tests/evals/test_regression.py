"""Original, synthetic mode-specific evaluation oracles."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from tools.evals.run import evaluate, report

CASES = json.loads(Path(__file__).with_name("cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_original_regression_cases(case):
    assert evaluate(case) == sorted(case["expected_issues"])


def test_report_keeps_mode_results_and_human_limits_separate():
    result = report(CASES)
    assert set(result["modes"]) == {"repetition", "guided_conversation", "free_conversation"}
    assert all(m["passed"] >= 3 and m["failed"] == 0 for m in result["modes"].values())
    assert result["human_quality"] == "incomplete"
    broken = deepcopy(CASES)
    broken[0]["response"]["evidence_label"] = "independent"
    assert report(broken)["modes"]["repetition"]["failed"] == 1


@pytest.mark.parametrize("value", ["0", "7", "100"])
def test_live_probe_refuses_more_than_six_turns(value):
    import argparse
    from tools.evals.live import bounded_turns
    with pytest.raises(argparse.ArgumentTypeError):
        bounded_turns(value)


def test_live_artifacts_cannot_be_written_to_a_checkout(tmp_path):
    from tools.evals.live import private_output
    (tmp_path / ".git").mkdir()
    with pytest.raises(ValueError, match="outside Git"):
        private_output(tmp_path / "private-output")


def test_probe_metadata_observes_production_stream_without_bypassing_byte_limit():
    import httpx2
    from tools.evals.live import observe_response
    seen = []
    transport = httpx2.MockTransport(lambda r: httpx2.Response(200, stream=httpx2.ByteStream(b'{"choices":[]}')))
    with httpx2.Client(transport=transport, event_hooks={"response": [lambda r: observe_response(r, lambda status, raw: seen.append((status, json.loads(raw))))]}) as client:
        assert client.post("https://synthetic.invalid").status_code == 200
    assert seen == [(200, {"choices": []})]
    oversized = httpx2.MockTransport(lambda r: httpx2.Response(200, stream=httpx2.ByteStream(b"x" * 65537)))
    with httpx2.Client(transport=oversized, event_hooks={"response": [lambda r: observe_response(r, lambda *a: seen.append(a))]}) as client:
        with pytest.raises(ValueError, match="metadata limit"):
            client.post("https://synthetic.invalid")
    assert len(seen) == 1


def test_probe_metadata_decodes_compressed_responses_before_reading_token_counts():
    import gzip
    import httpx2
    from tools.evals.live import observe_response
    payload = {"usage": {"completion_tokens": 80, "completion_tokens_details": {"reasoning_tokens": 10}}}
    wire = gzip.compress(json.dumps(payload).encode())
    seen = []
    transport = httpx2.MockTransport(lambda r: httpx2.Response(200, headers={"Content-Encoding": "gzip"}, stream=httpx2.ByteStream(wire)))
    with httpx2.Client(transport=transport, event_hooks={"response": [lambda r: observe_response(r, lambda status, raw: seen.append(json.loads(raw)))]}) as client:
        assert client.post("https://synthetic.invalid").json() == payload
    assert seen == [payload]
