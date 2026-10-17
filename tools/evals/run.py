"""Offline transcript regression checks, with separate results for each mode.

The expected observation/label is authored by the fixture, never inferred from
another model. These narrow checks do not measure general teaching quality.
"""
import argparse
import json
from pathlib import Path
import re

from voice_teacher.practice.free_feedback import validate_response

MODES = ("repetition", "guided_conversation", "free_conversation")


def evaluate(case):
    mode = case["mode"]
    if mode not in MODES:
        raise ValueError("unknown evaluation mode")
    issues = []
    response = case["response"]
    text = response["text"]
    if len(text) > 1200 or len(re.findall(r"[.!?]+(?:\s|$)", text)) > 3:
        issues.append("reply_bound")
    if any(t.casefold() in text.casefold() for t in case.get("forbidden_claims", [])):
        issues.append("task_adherence")
    # An authored oracle supplies required topic/task content for this sample.
    if case.get("required_any") and not any(t.casefold() in text.casefold() for t in case["required_any"]):
        issues.append("task_adherence")
    if not case["attempt_recorded"] and any(t in json.dumps(response, ensure_ascii=False) for t in case["hidden_targets"]):
        issues.append("premature_target")
    if response["evidence_label"] != case["expected_label"]:
        issues.append("evidence_label")
    if mode == "free_conversation":
        context = case["feedback_context"]
        try:
            validate_response(context, {"observations": response["observations"]})
        except ValueError:
            issues.append("unsupported_reference")
        # Shape/substring validity alone cannot prove a linguistic correction.
        # The fixture's reviewed correction pairs are the semantic ground truth.
        allowed = {(v["original"], v["preferred"]) for v in case["supported_corrections"]}
        if any(o["preferred"] is not None and (o["original"], o["preferred"]) not in allowed for o in response["observations"]):
            issues.append("invented_correction")
    return sorted(set(issues))


def report(cases):
    result = {m: {"passed": 0, "failed": 0, "cases": []} for m in MODES}
    for case in cases:
        issues = evaluate(case)
        passed = issues == sorted(case["expected_issues"])
        row = {"id": case["id"], "detected": issues, "expected": sorted(case["expected_issues"]), "passed": passed}
        mode = result[case["mode"]]
        mode["passed" if passed else "failed"] += 1
        mode["cases"].append(row)
    return {"kind": "offline_regression", "modes": result, "human_quality": "incomplete", "live_check": "not run"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=Path(__file__).parents[2] / "tests/evals/cases.json")
    args = parser.parse_args()
    result = report(json.loads(args.fixtures.read_text()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(any(m["failed"] for m in result["modes"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
