from copy import deepcopy
from dataclasses import asdict, replace
import json

import pytest

from voice_teacher.practice import Lesson, Session, UKRAINIAN
from voice_teacher.practice.session import round_zero
from voice_teacher.practice.text import plain
from test_session import FakeJudge, small_lesson, through_opening


def test_representative_long_sequence_without_curriculum_checkout():
    data = small_lesson().to_dict()
    phrases = [f"Це синтетичне речення номер {i}." for i in range(9)]
    data["opening"], data["opening_item_ids"] = phrases[:3], [f"p{i}" for i in range(3)]
    data["steps"] = [dict(number=i + 1, step_id=f"step{i}", teacher_line=f"Питання {i}.",
                          expected=f"perform task {i}", targets=[phrases[i % 9]],
                          target_item_ids=[f"p{i % 9}"]) for i in range(12)]
    data["recall"] = [dict(number=i + 1, goal_id=f"goal{i}", prompt=f"Пригадайте {i}.",
                           targets=[phrases[i]], target_item_ids=[f"p{i}"]) for i in range(9)]
    lesson = Lesson.from_dict(data)
    judge = FakeJudge(*[("accept",)] * 33)
    s = Session(lesson, judge)
    s.start()
    for line in lesson.opening:
        s.hear(line)
    for line, _ in round_zero(lesson):
        s.hear(line)
    for _ in range(2):
        for step in lesson.steps:
            s.hear(step.targets[0])
    for prompt in lesson.recall:
        s.hear(prompt.targets[0])
    assert s.done and len(judge.asked) == 33 and len(s.evidence) == 45
    assert [e.label for e in s.evidence] == ["repeated"] * 12 + ["independent"] * 33
    assert all((e.source_id, e.course_id, e.lesson_id) == ("synthetic", "basics", "tickets") for e in s.evidence)
    assert [e.item_id for e in s.evidence[3:12]] == [f"p{i}" for i in range(9)]


def test_identical_text_with_distinct_identity_is_not_merged():
    lesson = small_lesson()
    lesson.steps[1].targets = lesson.steps[0].targets[:]
    lesson.steps[1].target_item_ids = ["separate-context"]
    assert len(round_zero(lesson)) == 2
    lesson.steps[1].target_item_ids = lesson.steps[0].target_item_ids[:]
    assert len(round_zero(lesson)) == 1


def test_display_strips_only_profile_stress_and_speech_retains_it():
    s = Session(small_lesson(), FakeJudge())
    line = s.start()[1]
    assert "\u0301" in line.text and "\u0301" not in line.display
    profile = replace(UKRAINIAN, language="fr", stress_mark=None)
    assert plain("Café", profile) == "Café"


def test_another_language_profile_owns_all_teaching_phrases():
    phrases = {k: f"{k} {{task}}" if k in ("turn_card", "model_card") else
               "Correct {chunk}" if k == "correction" else k
               for k, v in asdict(UKRAINIAN).items() if isinstance(v, str)
               and k not in ("language", "instruction_language", "stress_mark")}
    profile = replace(UKRAINIAN, **phrases, language="fr", instruction_language="de",
                      stress_mark=None, stop_words=("finish",))
    data = small_lesson().to_dict()
    data.update(language="fr", instruction_language="de", introduction="Bonjour")
    data["opening"] = ["Café"]
    data["opening_item_ids"] = ["coffee"]
    data["steps"] = [dict(number=1, step_id="ask", teacher_line="Bonjour", expected="ask coffee",
                          targets=["Un café"], target_item_ids=["ask-coffee"])]
    data["recall"] = [dict(number=1, goal_id="coffee", prompt="Ask", targets=["Un café"], target_item_ids=["ask-coffee"])]
    lesson = Lesson.from_dict(data)
    s = Session(lesson, FakeJudge(("error", "lait"), ("accept",), ("accept",), ("accept",)), profile=profile)
    assert [x.text for x in s.start()] == ["Bonjour listen", "Café"]
    assert [x.text for x in s.hear("Café")] == ["new_sentences", "Un café"]
    assert s.card == "model_card ask coffee"
    assert [x.text for x in s.hear("Un café")] == ["start_talk", "Bonjour", "Ask coffee."]
    assert [x.text for x in s.hear("milk")] == ["Correct lait"]
    assert [x.text for x in s.hear("Un café")] == ["round_two", "Bonjour"]
    assert [x.text for x in s.hear("Un café")] == ["recall", "Ask"]
    assert [x.text for x in s.hear("Un café")] == ["closing"]
    stopped = Session(lesson, FakeJudge(), profile=profile)
    stopped.start()
    assert stopped.hear("finish")[0].text == "closing"
    with pytest.raises(ValueError, match="language profile"):
        Session(lesson, FakeJudge())


@pytest.mark.parametrize("misses", [1, 2])
def test_resume_mid_help_preserves_outputs_labels_and_history(misses):
    judge = FakeJudge(*[("error",)] * misses, ("accept",), ("accept",))
    s = Session(small_lesson(), judge, clock=lambda: 0)
    through_opening(s)
    for _ in range(misses):
        s.hear("wrong")
    saved = json.loads(json.dumps(s.snapshot()))
    resumed_judge = FakeJudge(("accept",), ("accept",))
    resumed = Session.from_snapshot(small_lesson(), resumed_judge, saved, clock=lambda: 0)
    for turn in ["один квиток будь ласка", "скільки це коштує"]:
        assert resumed.hear(turn) == s.hear(turn)
        assert resumed.snapshot() == s.snapshot()
    assert resumed.evidence[-2].label == ("cued" if misses == 1 else "modelled_repeated")


def test_persistence_interface_and_pinned_input_guards():
    class Store:
        def save(self, session_id, state):
            self.saved = (session_id, json.dumps(state))
        def load(self, session_id):
            assert self.saved[0] == session_id
            return json.loads(self.saved[1])
    s = Session(small_lesson(), FakeJudge())
    s.start()
    store = Store()
    s.save(store, "session-1")
    state = store.load("session-1")
    assert Session.from_snapshot(small_lesson(), FakeJudge(), state).snapshot() == s.snapshot()
    changed = small_lesson()
    changed.steps[0].targets[0] = "changed"
    with pytest.raises(ValueError, match="pinned"):
        Session.from_snapshot(changed, FakeJudge(), state)
    for path, value in [("format_version", 2), ("index", 100), ("round", True)]:
        bad = deepcopy(state)
        if path == "format_version":
            bad[path] = value
        else:
            bad["data"][path] = value
        with pytest.raises(ValueError):
            Session.from_snapshot(small_lesson(), FakeJudge(), bad)


def test_pre_attempt_prompt_does_not_expose_target_to_teacher():
    judge = FakeJudge(("accept",))
    s = Session(small_lesson(), judge, part="2")
    says = s.start()
    assert all(s.lesson.steps[0].targets[0] not in x.text for x in says)
    assert judge.asked == []
    s.hear("answer")
    assert judge.asked[0][0].targets == s.lesson.steps[0].targets


def test_session_owns_a_copy_of_prepared_inputs():
    lesson = small_lesson()
    s = Session(lesson, FakeJudge())
    lesson.opening[0] = "mutated"
    assert s.start()[1].text != "mutated"


def test_speech_interfaces_accept_fake_providers_without_sdk():
    class Speech:
        def transcribe(self, audio, *, language):
            assert language == "uk"
            return audio.decode()
        def synthesize(self, text, *, language):
            assert language == "uk"
            return text.encode()
    speech = Speech()
    s = Session(small_lesson(), FakeJudge())
    line = s.start()[1]
    assert speech.transcribe(speech.synthesize(line.text, language="uk"), language="uk") == line.text
    s.hear(speech.transcribe(b"stop", language="uk"))
