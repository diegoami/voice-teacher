from connector.lesson import OpeningTracker, next_package, normalise, plain


def test_plain_and_normalise():
    assert plain("Котра́ за́раз годи́на?") == "Котра зараз година?"
    assert normalise("Мо́же, зустрі́немося о сьо́мій?") == "може зустрінемося о сьомій"


def test_next_package_reads_the_3a_brief(sessions_dir):
    package = next_package(sessions_dir)
    assert package.session_label == "3A"
    assert package.prompt_version == "v4"
    assert len(package.opening_lines) == 11
    assert package.opening_lines[0] == "Котра́ за́раз годи́на?"


def test_opening_advances_on_evidence_and_allows_one_resay(sessions_dir):
    lines = next_package(sessions_dir).opening_lines
    tracker = OpeningTracker(lines)
    assert "Teacher introduction" in tracker.instruction()
    tracker.observe("Сьогодні ми повторимо час... Спочатку послухайте, а потім повторіть. Котра зараз година?")
    assert tracker.next_index == 1
    assert "«О котрій годині?»" in tracker.instruction()
    assert "«Котра зараз година?» once more" in tracker.instruction()
    tracker.observe("Котра зараз година?")  # re-said line 1
    assert tracker.next_index == 1
    assert "once more" not in tracker.instruction()
    for line in lines[1:]:
        tracker.observe(plain(line))
    assert tracker.next_index == 11
    assert "Opening complete" in tracker.instruction()
    tracker.observe("Добре. А тепер почнімо розмову. Ви вільні сьогодні ввечері?")
    assert tracker.finished and tracker.instruction() == "Recorded."
    assert tracker.events == ["line 1 re-said"]


def test_opening_flags_merged_and_skipped_lines(sessions_dir):
    lines = next_package(sessions_dir).opening_lines
    tracker = OpeningTracker(lines)
    tracker.observe(f"Вступ. {plain(lines[0])}")
    tracker.observe(f"{plain(lines[1])} {plain(lines[2])}")
    assert tracker.next_index == 3 and "merged" in tracker.events[0]
    tracker.observe("Чудово!")
    assert tracker.next_index == 3 and "did not contain expected line 4" in tracker.events[1]


def test_package_steps_and_recall(sessions_dir):
    package = next_package(sessions_dir)
    assert len(package.guided_steps) == 10 and len(package.recall_prompts) == 6
    from connector.lesson import spoken_line
    assert spoken_line(package.guided_steps[0]) == "До́брий день! Ви ві́льні сього́дні вве́чері?"
    assert spoken_line(package.guided_steps[7]) == "О дру́гій я за́йнятий."


def test_replay_of_the_real_3a_lesson(sessions_dir):
    """Feed the teacher turns of the recorded 3A lesson; the tracker must follow it to the last recall prompt."""
    from conftest import SOURCE
    from connector.lesson import LessonTracker
    text = (SOURCE / "transcript.md").read_text(encoding="utf-8")
    if "## Source 3" not in text:
        import pytest
        pytest.skip("3A transcript without the teacher's write-up")
    block = text.split("## Source 3")[1].split("```text\n")[1].split("```")[0]
    teacher = [line[len("Teacher: "):] for line in block.splitlines() if line.startswith("Teacher: ")]
    tracker = LessonTracker.for_package(next_package(sessions_dir))
    for said in teacher[:-1]:  # the last turn is the close
        tracker.observe(said)
    assert tracker.opening.finished
    assert tracker.phase == "recall" and tracker.steps.current == 15
    assert "call end_session" in tracker.instruction()
    # Step 8 was said with a different hour («О шостій я зайнятий.») and still matched; nothing was skipped.
    assert tracker.events == ["line 1 re-said"]
