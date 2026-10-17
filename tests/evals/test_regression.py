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
