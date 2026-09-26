from conftest import HERE

from stt.report import recording_report
from stt.score import reading_list, score_recording, summarise
from stt.text import words

ERRORS = HERE / "reading_list_errors.md"


def tidied(sentences) -> str:
    """The reading with every planted mistake replaced by the correct Ukrainian."""
    out = []
    for s in sentences:
        text = " ".join(s.words)
        if s.error:
            said, correct = (" ".join(words(x)) for x in s.error)
            text = f" {text} ".replace(f" {said} ", f" {correct} ", 1).strip()
        out.append(text)
    return " ".join(out)


def test_errors_list_is_consistent():
    sentences = reading_list(ERRORS)
    assert [s.number for s in sentences] == list(range(1, 27))
    planted = [s for s in sentences if s.error]
    assert len(planted) == 18
    for s in planted:
        said, correct = (words(x) for x in s.error)
        joined = " " + " ".join(s.words) + " "
        assert " " + " ".join(said) + " " in joined, s.number  # the mistake is in the line as read
        assert said != correct


def test_verbatim_recogniser_keeps_every_mistake():
    sentences = reading_list(ERRORS)
    s = summarise(score_recording(sentences, " ".join(x.plain for x in sentences)))
    assert (s.kept, s.corrected, s.planted) == (18, 0, 18)
    assert (s.controls_exact, s.controls) == (8, 8)
    assert s.wer == 0


def test_tidying_recogniser_is_caught():
    sentences = reading_list(ERRORS)
    results = score_recording(sentences, tidied(sentences))
    s = summarise(results)
    assert (s.kept, s.corrected) == (0, 18)
    assert s.controls_exact == 8
    report = recording_report("errors-1.m4a", ERRORS.name, sentences,
                              [({"provider": "tidy", "model": "m", "seconds": 1}, results)], [])
    assert "| tidy | 0/18 | 18/18 | 0/18 | 8/8 |" in report
    assert "| 1 | где → де | corrected |" in report
    assert "## Lines misrecognised" not in report
