from conftest import LEARNUKRAINIAN, read_aloud, russianised
import pytest

from stt.report import opening_pairs
from stt.score import score_pairs, score_recording, summarise


def test_reading_list(sentences):
    assert len(sentences) == 32
    assert [s.number for s in sentences] == list(range(1, 33))
    assert sum("4A" in s.tags for s in sentences) == 14
    assert sentences[3].plain == "Потім поверніть праворуч."
    assert "<!--" not in sentences[0].text


def test_perfect_reading_scores_zero(sentences):
    s = summarise(score_recording(sentences, read_aloud(sentences)))
    assert s.wer == 0 and s.cer == 0 and s.russian == 0
    assert s.exact == 32 and s.tagged_exact == 14


def test_russian_lines_are_found_and_placed(sentences):
    results = score_recording(sentences, russianised(sentences))
    wrong = {r.sentence.number: r for r in results if not r.exact}
    assert set(wrong) == {1, 4, 7}
    assert wrong[1].russian == ["извините", "где", "находится", "станция"]
    assert wrong[4].russian == ["потом"]
    assert wrong[7].russian == ["нет"]
    assert wrong[1].heard == "извините где находится станция метро".split()
    s = summarise(results)
    assert s.russian == 6
    assert s.tagged_exact == 11


def test_missing_and_extra_words(sentences):
    text = read_aloud(sentences).replace("Ду́же дя́кую.", "").replace("Дуже дякую.", "")
    text = text.replace("Нема за що.", "Нема за що, ну.")
    results = {r.sentence.number: r for r in score_recording(sentences, text)}
    assert results[18].dels == 2 and results[18].heard == []
    assert results[19].ins == 1
    assert summarise(list(results.values())).wer == pytest.approx(3 / sum(len(s.words) for s in sentences))


def test_score_pairs(sentences):
    results = score_pairs([(sentences[3], "Потом поверните направо."), (sentences[3], "Потім поверніть праворуч.")])
    assert [r.errors for r in results] == [3, 0]
    assert results[0].russian == ["потом"]


def test_opening_pairs_both_transcript_formats(sentences):
    claude = """Learner: Почнимо урок
Teacher: Вступ. Спочатку послухайте, а потім повторіть. Перепрошую, де знаходиться станція метро?
Learner: Извините, где метро?
Teacher: Note to self. Ідіть прямо до перехрестя.
Learner: Идите.
Teacher: Добре. А тепер почнімо розмову. Добрий день!
Learner: Добрый.
Teacher: Перепрошую, де знаходиться станція метро?
Learner: не рахується
"""
    pairs = opening_pairs(claude, sentences)
    assert [(s.number, heard) for s, heard in pairs] == [(1, "Извините, где метро?"), (3, "Идите.")]
    chatgpt = """**Learner** (text): [package]
**Teacher** (text): Ready.
**Learner** (voice): Почнімо.
**Teacher** (voice): Ідіть прямо до перехрестя, а потім поверніть праворуч.
**Learner** (voice): Ідіть прямо до перехрестя, а потім поверніть праворуч
"""
    assert [s.number for s, _ in opening_pairs(chatgpt, sentences)] == [13]  # the longest line wins


@pytest.mark.skipif(not LEARNUKRAINIAN.exists(), reason="learnukrainian checkout not found")
def test_4a_openings_claude_versus_chatgpt(sentences):
    claude = score_pairs(opening_pairs((LEARNUKRAINIAN / "2026-09-24-session-4A" / "transcript.md").read_text(), sentences))
    chatgpt = score_pairs(opening_pairs((LEARNUKRAINIAN / "2026-09-25-session-4A-chatgpt" / "transcript.md").read_text(), sentences))
    assert len(claude) >= 12 and len(chatgpt) == 12
    assert summarise(claude).russian >= 15
    assert summarise(chatgpt).russian == 0
    assert summarise(chatgpt).wer < 0.05
