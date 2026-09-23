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
