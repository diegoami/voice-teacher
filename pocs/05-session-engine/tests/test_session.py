import json
from pathlib import Path

import pytest

from engine.judge import Item, Judgement, Verdict, turn_message
from engine.package import Lesson
from engine.session import (CORRECTION, LISTEN, LISTENING, MODEL_CARD, NEW_SENTENCES, OPENING_CARD, RECALL,
                            REPEAT_PLEASE, ROUND_TWO, START_TALK, Session, cue_for, round_zero, wants_to_stop)

HERE = Path(__file__).resolve().parents[1]
LESSON_4B = HERE / "fixtures" / "lessons" / "4B.json"


def small_lesson() -> Lesson:
    return Lesson.from_dict({
        "source": "test", "part": "9A", "title": "Tickets", "learner": "Test learner.", "main_goal": "",
        "introduction": "Сього́дні ми ку́пимо квито́к.",
        "opening": ["Оди́н квито́к, будь ла́ска.", "Скі́льки це ко́штує?"],
        "active_phrases": [], "weak_expressions": [], "scenario": "",
        "steps": [
            {"number": 1, "teacher_line": "До́брий день!", "expected": "ask for one ticket",
             "targets": ["Оди́н квито́к, будь ла́ска."]},
            {"number": 2, "teacher_line": "Ось, будь ла́ска.", "expected": "ask the price",
             "targets": ["Скі́льки це ко́штує?"]},
        ],
        "recall": [{"number": 1, "prompt": "Запита́йте ціну́.", "targets": ["Скі́льки це ко́штує?"]}],
    })


class FakeJudge:
    """Returns queued verdicts and records what it was asked."""

    def __init__(self, *verdicts):
        self.queue = list(verdicts)
        self.asked: list[tuple[Item, str]] = []

    def __call__(self, item, learner):
        self.asked.append((item, learner))
        entry = self.queue.pop(0)
        verdict, chunk, reply, step = entry + ("accept", "", "", 0)[len(entry):]
        v = Verdict(verdict=verdict, on_task=verdict != "unclear", chunk=chunk, reply=reply, step=step, note="")
        return Judgement(v, 0.4, {"cost_usd": 0.001})


def texts(says):
    return [s.text for s in says]


def through_opening(session):
    """Opening review and round 0 with good repetitions; returns the first step of round 1."""
    session.start()
    session.hear("один квиток будь ласка")
    session.hear("скільки це коштує")  # opening done → round 0
    session.hear("один квиток будь ласка")
    return session.hear("скільки це коштує")


def test_opening_needs_no_model_and_resays_once():
    judge = FakeJudge()
    s = Session(small_lesson(), judge)
    first = s.start()
    assert texts(first) == ["Сього́дні ми ку́пимо квито́к. " + LISTEN, "Оди́н квито́к, будь ла́ска."]
    assert s.card == OPENING_CARD and "Don't answer" in s.card
    assert texts(s.hear("е… що?")) == ["Оди́н квито́к, будь ла́ска."]  # said once more
    assert texts(s.hear("один квиток будь ласка")) == ["Скі́льки це ко́штує?"]
    says = s.hear("скільки коштує")  # one word lost in recognition: still a repetition
    # Round 0: the lesson's own sentences, to repeat, not to answer.
    assert texts(says) == [NEW_SENTENCES, "Оди́н квито́к, будь ла́ска."]
    assert s.card == MODEL_CARD.format(task="ask for one ticket")
    assert texts(s.hear("один квиток будь ласка")) == ["Скі́льки це ко́штує?"]
    assert s.card.startswith("Repeat exactly what you hear; don't answer it.")
    says = s.hear("це коштує двадцять")  # an answer, not a repetition: said once more
    assert texts(says) == ["Скі́льки це ко́штує?"]
    says = s.hear("скільки це коштує")
    assert texts(says) == [START_TALK, "До́брий день!"]
    assert s.card == "Your turn: Ask for one ticket."
    assert judge.asked == []
    assert [(e.phase, e.round, e.label, e.attempts) for e in s.evidence] == [
        ("opening", 0, "repeated", 1), ("opening", 0, "repeated", 0),
        ("guided", 0, "repeated", 0), ("guided", 0, "repeated", 1)]


def test_full_lesson_with_every_kind_of_help():
    judge = FakeJudge(
        ("accept",),  # round 1 step 1: independent (with the card)
        ("error", "ко́штує"),  # round 1 step 2: correction…
        ("accept",),  # …then the corrected sentence
        ("unclear",),  # round 2 step 1: repeat request
        ("error",),  # off task: a cue
        ("accept",),  # cued
        ("error",), ("error",),  # round 2 step 2: two misses → the full sentence
        ("question", "", "Ціна́ — це скі́льки гро́шей."),  # recall: a question about meaning
        ("accept",),
    )
    s = Session(small_lesson(), judge)
    through_opening(s)
    assert texts(s.hear("один квиток будь ласка")) == ["Ось, будь ла́ска."]
    assert s.card == "Your turn: Ask the price."
    assert texts(s.hear("сколько это стоит")) == [CORRECTION.format(chunk="ко́штує")]
    says = s.hear("скільки це коштує")
    assert texts(says) == [ROUND_TWO, "До́брий день!"] and s.card is None
    assert texts(s.hear("ееее")) == [REPEAT_PLEASE]
    assert texts(s.hear("добрий день")) == ["Оди́н…"]
    assert texts(s.hear("один квиток будь ласка")) == ["Ось, будь ла́ска."]
    s.hear("ціна")
    assert texts(s.hear("яка ціна")) == ["Скі́льки це ко́штує?", REPEAT_PLEASE]
    assert texts(s.hear("скільки це коштує")) == [RECALL, "Запита́йте ціну́."]
    assert texts(s.hear("що таке ціна?")) == ["Ціна́ — це скі́льки гро́шей.", "Запита́йте ціну́."]
    assert texts(s.hear("скільки це коштує")) == ["Заня́ття закі́нчено."]
    assert s.done
    labels = [(e.phase, e.round, e.number, e.label, e.attempts) for e in s.evidence
              if e.phase != "opening" and not (e.phase == "guided" and e.round == 0)]
    assert labels == [
        ("guided", 1, 1, "independent", 0),
        ("guided", 1, 2, "corrected_repeated", 1),
        ("guided", 2, 1, "cued", 1),
        ("guided", 2, 2, "modelled_repeated", 2),
        ("recall", 0, 1, "independent", 0),
    ]
    # The judge sees earlier attempts on the same item, and never the opening.
    item, learner = judge.asked[2]
    assert learner == "скільки це коштує" and item.history[0][0] == "сколько это стоит"
    with pytest.raises(RuntimeError, match="closed"):
        s.hear("ще")


def test_a_whole_sentence_is_never_passed_off_as_a_correction():
    judge = FakeJudge(("error", "Оди́н квито́к, будь ла́ска"))  # the model offers the whole target as its chunk
    s = Session(small_lesson(), judge)
    through_opening(s)
    assert texts(s.hear("два квитки")) == ["Оди́н…"]  # a cue instead


def test_failed_repeat_moves_on():
    judge = FakeJudge(("error",), ("error",))
    s = Session(small_lesson(), judge)
    through_opening(s)
    s.hear("х")
    s.hear("у")  # second miss: the full sentence
    assert texts(s.hear("не знаю")) == ["Оди́н квито́к, будь ла́ска."]  # said once more
    assert texts(s.hear("не знаю")) == ["Ось, будь ла́ска."]  # then on to the next step
    assert s.evidence[-1].label == "needs_turn"


def test_log_records_teacher_learner_and_judge():
    s = Session(small_lesson(), FakeJudge(("accept",)), clock=iter(range(1000)).__next__)
    through_opening(s)
    s.hear("один квиток будь ласка")
    events = [e["event"] for e in s.log]
    assert events[:2] == ["teacher", "learner"] and "judge" in events
    judge_event = next(e for e in s.log if e["event"] == "judge")
    assert judge_event["verdict"]["verdict"] == "accept" and judge_event["seconds"] == 0.4
    assert json.dumps(s.log, ensure_ascii=False)  # serialisable for the session file


def test_cue_and_turn_message():
    assert cue_for("Де мені́ вихо́дити?") == "Де…"
    assert cue_for("Я ї́ду до це́нтру. Як туди́ дої́хати?") == "Я ї́ду…"
    item = Item("step", "Метро́ шви́дше.", "ask where the nearest station is", ["Де найбли́жча ста́нція?"])
    message = json.loads(turn_message(item, "де найближча станція"))
    assert message["task"] == "ask where the nearest station is" and message["earlier_attempts"] == []


@pytest.mark.skipif(not LESSON_4B.exists(), reason="4B lesson fixture not built")
def test_4b_runs_end_to_end_with_perfect_answers():
    lesson = Lesson.from_dict(json.loads(LESSON_4B.read_text(encoding="utf-8"))["lesson"])
    s = Session(lesson, FakeJudge(*[("accept",)] * (2 * len(lesson.steps) + len(lesson.recall))))
    s.start()
    for line in lesson.opening:
        s.hear(line)
    zero = round_zero(lesson)
    assert len(zero) == 9  # 12 steps, three sentences used twice
    for sentence, _ in zero:
        s.hear(sentence)
    for _ in range(2):
        for step in lesson.steps:
            s.hear(step.targets[0])
    for prompt in lesson.recall:
        s.hear(prompt.targets[0])
    assert s.done
    guided = [e for e in s.evidence if e.phase == "guided"]
    assert len(guided) == 9 + 24
    assert {e.label for e in guided if e.round == 0} == {"repeated"}
    assert {e.label for e in guided if e.round > 0} == {"independent"}


def test_repeats_tells_repetition_from_answer():
    from engine.session import repeats
    assert repeats("Скі́льки це ко́штує?", "скільки це коштує")
    assert repeats("Скі́льки це ко́штує?", "Скільки коштує?")  # a dropped word
    assert repeats("Як кра́ще дої́хати до це́нтру?", "як краще доехать до центру")  # one garbled word
    assert not repeats("Скі́льки це ко́штує?", "це коштує двадцять")  # an answer
    assert not repeats("Як пройти́ до це́нтру?", "ідіть прямо до центру")  # an answer to the question


def three_step_lesson() -> Lesson:
    lesson = small_lesson()
    data = lesson.to_dict()
    data["steps"].append({"number": 3, "teacher_line": "Два́дцять гри́вень.", "expected": "thank you",
                          "targets": ["Дя́кую."], "open_answer": True})
    return Lesson.from_dict(data)


def test_greeting_back_is_not_an_attempt():
    judge = FakeJudge(("social",), ("accept",))
    s = Session(small_lesson(), judge)
    through_opening(s)
    assert texts(s.hear("добрий день")) == [LISTENING]
    assert texts(s.hear("один квиток будь ласка")) == ["Ось, будь ла́ска."]
    assert s.evidence[-1].label == "independent" and s.evidence[-1].attempts == 0


def test_running_ahead_jumps_to_that_step():
    lesson = three_step_lesson()
    s = Session(lesson, FakeJudge(("later_step", "", "", 2)))
    s.start()
    for line in lesson.opening:
        s.hear(line)
    for sentence, _ in round_zero(lesson):
        s.hear(sentence)
    says = s.hear("скільки це коштує")  # at step 1 the learner asks step 2's question
    assert texts(says) == ["Два́дцять гри́вень."]  # the teacher answers it: step 3's line
    assert [(e.number, e.label) for e in s.evidence if e.phase == "guided" and e.round == 1] == \
        [(1, "skipped"), (2, "independent")]


def test_the_judge_sees_the_next_steps():
    judge = FakeJudge(("accept",))
    s = Session(three_step_lesson(), judge)
    through_opening(s)
    s.hear("дякую")  # round 0 has a third sentence here
    s.hear("один квиток будь ласка")
    item, _ = judge.asked[0]
    assert item.later == [(2, "ask the price"), (3, "thank you")]
    assert json.loads(turn_message(item, "x"))["later_steps"][0] == {"step": 2, "task": "ask the price"}


def test_a_later_step_the_judge_was_not_offered_is_an_error():
    s = Session(small_lesson(), FakeJudge(("later_step", "", "", 7)))
    through_opening(s)
    assert texts(s.hear("щось")) == ["Оди́н…"]  # treated as a miss, not a jump


def test_stop_words_end_the_lesson():
    assert wants_to_stop("Закінчимо") and wants_to_stop("закинчимо") and wants_to_stop("Стоп!")
    assert not wants_to_stop("Де мені виходити?")
    s = Session(small_lesson(), FakeJudge())
    s.start()
    assert texts(s.hear("закінчимо, будь ласка")) == ["Заня́ття закі́нчено."] and s.done
