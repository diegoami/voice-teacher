import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine import __main__ as cli
from engine.derive import Derived, RecallTargets, StepTargets, apply, derive, request_text, unverified_stress
from engine.llm import PROVIDERS, Connection, connection
from engine.package import Lesson, parse_package, parse_step

VOICE_SESSIONS = Path(__file__).resolve().parents[4] / "learnukrainian" / "pimsleur-review" / "voice-sessions"

# A made-up package in the /voice-prepare format, so the tests do not depend on curriculum files.
PACKAGE = """VOICE_SESSION_PACKAGE
Prompt version: g1

(controller text the engine does not use)

SESSION_BRIEF
Session: 9 — Test
Lesson part: 9A — Buying a ticket
Length: short.
Learner: Test learner. Uses masculine forms.
Main goal: Ask for a ticket and the price.
Preparation section: none
Teacher introduction:
Сього́дні ми ку́пимо квито́к.
Opening review (2 lines):
1. Оди́н квито́к, будь ла́ска.
2. Скі́льки це ко́штує?
Active phrase set:
- Оди́н квито́к, будь ла́ска.
- Скі́льки це ко́штує?
Guided sequence:
You are a ticket seller. Speak your own line, then wait.
1. Say «До́брий день!» Wait for the learner to ask for one ticket.
2. Say «Ось, будь ла́ска.» Wait for the learner to ask the price
   (earlier weak expression).
3. New cycle: say «Щось іще́?» (keep it short) Wait for the learner to thank you.
Delayed recall:
- Запита́йте ціну́.
Earlier weak expressions included:
- Скі́льки це ко́штує? — Test, Session 8
Source: Test
Coverage criterion:
Anything.
END_SESSION_BRIEF
"""


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "package.md").write_text(PACKAGE, encoding="utf-8")
    return tmp_path


def test_parse_package(folder):
    lesson = parse_package(folder)
    assert (lesson.part, lesson.title) == ("9A", "Buying a ticket")
    assert lesson.opening == ["Оди́н квито́к, будь ла́ска.", "Скі́льки це ко́штує?"]
    assert lesson.introduction == "Сього́дні ми ку́пимо квито́к."
    assert lesson.scenario == "You are a ticket seller. Speak your own line, then wait."
    assert [s.teacher_line for s in lesson.steps] == ["До́брий день!", "Ось, будь ла́ска.", "Щось іще́?"]
    assert lesson.steps[1].expected == "ask the price (earlier weak expression)"  # continuation line joined
    assert lesson.steps[2].setting == "New cycle (keep it short)"
    assert lesson.steps[2].expected == "thank you"
    assert [r.prompt for r in lesson.recall] == ["Запита́йте ціну́."]
    assert lesson.weak_expressions == ["Скі́льки це ко́штує? — Test, Session 8"]
    assert Lesson.from_dict(json.loads(json.dumps(lesson.to_dict()))) == lesson


def test_opening_count_is_checked(folder):
    (folder / "package.md").write_text(PACKAGE.replace("(2 lines)", "(3 lines)"), encoding="utf-8")
    with pytest.raises(ValueError, match="declares 3 lines, found 2"):
        parse_package(folder)


def test_step_formats():
    assert parse_step(1, "Ask «Ви бу́дете щось ї́сти?» The learner asks whether you have borshch.").expected \
        == "asks whether you have borshch"
    with pytest.raises(ValueError, match="no «…» line"):
        parse_step(7, "New cycle: the learner orders tea instead.")


@pytest.mark.skipif(not VOICE_SESSIONS.exists(), reason="learnukrainian checkout not found")
def test_real_4b_package():
    lesson = parse_package(VOICE_SESSIONS / "2026-09-26-session-4B")
    assert (lesson.part, len(lesson.opening), len(lesson.steps), len(lesson.recall)) == ("4B", 12, 12, 5)
    assert lesson.steps[7].setting == "New cycle, in the street"
    assert lesson.steps[0].expected == "ask the best way to get to the centre"


def derived_for(lesson):
    return Derived(
        steps=[StepTargets(step=1, targets=["Оди́н квито́к, будь ла́ска."], phrase="Оди́н квито́к, будь ла́ска.", open_answer=False),
               StepTargets(step=2, targets=["Скі́льки це ко́штує?"], phrase="Скі́льки це ко́штує?", open_answer=False),
               StepTargets(step=3, targets=["Дя́кую.", "Ду́же дя́кую.", "Дякую ще раз.", "Спасибі."], phrase="", open_answer=True)],
        recall=[RecallTargets(prompt=1, targets=["Скі́льки це ко́штує?"], phrase="Скі́льки це ко́штує?")])


class FakeClient:
    """Stands in for openai.OpenAI: records the request, returns a canned completion."""

    def __init__(self, parsed=None, refusal=None, finish="stop", cost=0.012):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self.parse))
        self.completion = SimpleNamespace(
            model="openai/gpt-6-sol",
            choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(parsed=parsed, refusal=refusal))],
            usage=SimpleNamespace(prompt_tokens=1200, completion_tokens=300, model_extra={"cost": cost}))

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.completion


OPENROUTER = Connection("openrouter", *PROVIDERS["openrouter"])


def test_derive_request_and_result(folder, monkeypatch):
    monkeypatch.delenv("TARGETS_MODEL", raising=False)
    lesson = parse_package(folder)
    client = FakeClient(parsed=derived_for(lesson))
    lesson, usage = derive(lesson, OPENROUTER, client)
    call = client.calls[0]
    assert call["model"] == "openai/gpt-6-sol" and call["response_format"] is Derived
    assert call["extra_body"] == {"provider": {"require_parameters": True}, "usage": {"include": True}}
    assert call["messages"][0]["role"] == "system"
    assert "the teacher says «Ось, будь ла́ска.»; the learner is to ask the price (earlier weak expression)." \
        in call["messages"][1]["content"]
    assert lesson.steps[2].targets == ["Дя́кую.", "Ду́же дя́кую.", "Дякую ще раз."]  # at most three kept
    assert lesson.steps[2].open_answer and lesson.recall[0].phrase == "Скі́льки це ко́штує?"
    assert usage == {"model": "openai/gpt-6-sol", "input_tokens": 1200, "output_tokens": 300, "cost_usd": 0.012}


def test_derive_refuses_bad_answers(folder):
    lesson = parse_package(folder)
    bad = derived_for(lesson)
    bad.steps = bad.steps[:2]
    with pytest.raises(ValueError, match="do not match"):
        apply(lesson, bad)
    empty = derived_for(lesson)
    empty.recall[0].targets = []
    with pytest.raises(ValueError, match="no targets for recall 1"):
        apply(parse_package(folder), empty)
    with pytest.raises(RuntimeError, match="declined"):
        derive(parse_package(folder), OPENROUTER, FakeClient(refusal="no"))
    with pytest.raises(RuntimeError, match="finish reason length"):
        derive(parse_package(folder), OPENROUTER, FakeClient(parsed=derived_for(lesson), finish="length"))


def test_connection_settings(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "opencode")
    monkeypatch.setenv("TARGETS_MODEL", "openai/gpt-6-sol")
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    conn = connection()
    assert conn.base_url == "https://opencode.ai/zen/v1" and conn.extra_body() == {}
    assert conn.model("targets") == "gpt-6-sol"  # vendor prefix is OpenRouter's naming only
    with pytest.raises(RuntimeError, match="OPENCODE_API_KEY is not set"):
        conn.client()
    with pytest.raises(RuntimeError, match="TEACHER_MODEL is not set"):
        conn.model("teacher")
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(RuntimeError, match="must be one of"):
        connection()


def test_unverified_stress(folder):
    lesson = apply(parse_package(folder), derived_for(parse_package(folder)))
    lesson.steps[0].targets = ["Оди́н квито́к, будь ласка́."]  # ласка stressed differently from the brief
    lesson.steps[1].targets = ["Скі́льки кошту́є квито́к?", "Яка ціна?"]  # new mark; unmarked word
    flagged = unverified_stress(lesson, PACKAGE)
    assert "ласка́ (brief: ла́ска)" in flagged
    assert "кошту́є (brief: ко́штує)" in flagged
    assert "ціна (no stress mark)" in flagged
    assert "Дя́кую" in flagged and "Ду́же" in flagged  # marks from Claude, not from the brief; listed once each
    assert not any(w.startswith("Оди́н") or w.startswith("квито́к") for w in flagged)


def test_cli_parse_only_and_review(folder, tmp_path, monkeypatch, capsys):
    sessions = tmp_path / "repo" / "pimsleur-review" / "voice-sessions" / "2026-10-01-session-9A"
    sessions.mkdir(parents=True)
    (sessions / "package.md").write_text(PACKAGE, encoding="utf-8")
    monkeypatch.setattr(cli, "LESSONS", tmp_path / "lessons")
    monkeypatch.setattr(sys, "argv", ["engine", "--learnukrainian", str(tmp_path / "repo"),
                                      "lesson", "2026-10-01-session-9A", "--no-derive"])
    assert cli.main() == 0
    data = json.loads((tmp_path / "lessons" / "9A.json").read_text(encoding="utf-8"))
    assert data["lesson"]["part"] == "9A" and data["derived_by"] is None
    sheet = (tmp_path / "lessons" / "9A-review.md").read_text(encoding="utf-8")
    assert "| 2 | Ось, будь ла́ска. | ask the price (earlier weak expression) | — | — |" in sheet

    data["lesson"] = apply(Lesson.from_dict(data["lesson"]), derived_for(None)).to_dict()
    data["unverified_stress"] = ["ціна (no stress mark)"]
    text = cli.review(data)
    assert "| 3 | _New cycle (keep it short)_ Щось іще́? | thank you _(any correct answer)_ | Дя́кую.<br>Ду́же дя́кую.<br>Дякую ще раз. | — |" in text
    assert "- ціна (no stress mark)" in text
