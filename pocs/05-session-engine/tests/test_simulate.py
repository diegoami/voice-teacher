import json
from pathlib import Path

import pytest

from engine.judge import Judgement, Verdict
from engine.package import Lesson
from engine.simulate import INTENTS, item_keys, plan, report, run

LESSON_4B = Path(__file__).resolve().parents[1] / "fixtures" / "lessons" / "4B.json"
pytestmark = pytest.mark.skipif(not LESSON_4B.exists(), reason="4B lesson fixture not built")


def lesson():
    return Lesson.from_dict(json.loads(LESSON_4B.read_text(encoding="utf-8"))["lesson"])


def fake_answers(lesson):
    return {key: {"variant": "VARIANT " + key, "russian": "где " + key, "russian_mistake": "где",
                  "ending": "ENDING " + key, "ending_mistake": "x", "word": "WORD " + key, "word_mistake": "y"}
            for key, _, _ in item_keys(lesson)}


class PlantedJudge:
    """Perfect on planted mistakes and unclear turns; rejects every variant (a strict judge)."""
    model = "strict-fake"

    def __call__(self, item, text):
        if text.startswith(("где", "ENDING", "WORD", "VARIANT")):
            verdict = "error"
        elif text.startswith("е…"):
            verdict = "unclear"
        else:
            verdict = "accept"
        return Judgement(Verdict(verdict=verdict, on_task=True, chunk="", reply="", note=""), 0.5, {"cost_usd": 0.001})


def test_plan_is_fixed_by_the_seed():
    l = lesson()
    assert plan(l, 1) == plan(l, 1) and plan(l, 1) != plan(l, 2)
    assert sorted(plan(l, 1).values()) == sorted(n for n, k in INTENTS.items() for _ in range(k))


def test_run_and_report():
    l = lesson()
    result = run(l, fake_answers(l), PlantedJudge())
    assert len(result.rows) == 29
    assert result.count({"russian", "ending", "word"}, {"error"}) == (12, 12)  # one word plant is on an open step
    assert result.count({"exact"}, {"accept"}) == (9, 9)
    assert result.count({"variant"}, {"accept"}) == (0, 6)  # the strict judge rejects them
    text = report([result], l)
    assert "| strict-fake | 12/12 | 9/15 | 1/1 |" in text
    assert "✗ error" in text and "✓ accept" in text


def test_rate_limit_wait_reads_openrouter_reset(monkeypatch):
    import time
    from types import SimpleNamespace
    from engine.judge import rate_limit_wait
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    exc = SimpleNamespace(body={"metadata": {"headers": {"X-RateLimit-Reset": "1012000"}}})
    assert rate_limit_wait(exc) == 12.5
    assert rate_limit_wait(SimpleNamespace(body=None)) == 10.0


def test_word_plants_on_open_answer_steps_are_not_scored():
    from engine.simulate import scored
    assert not scored({"intent": "word", "open_answer": True})
    assert scored({"intent": "word", "open_answer": False}) and scored({"intent": "russian", "open_answer": True})
