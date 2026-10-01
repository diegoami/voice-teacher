from engine.package import Lesson
from engine.stress import Stresser
from test_session import small_lesson


def lesson() -> Lesson:
    return small_lesson()


def test_marked_words_are_untouched():
    marked = Stresser(lesson()).mark("Скі́льки це ко́штує?")
    assert marked == "Скі́льки це ко́штує?"
    # a word that carries a mark is never changed, even if the lesson marks it differently
    assert Stresser(lesson()).mark("кви́ток") == "кви́ток"


def test_unmarked_words_come_from_the_lesson_dictionary_keeping_case_and_punctuation():
    s = Stresser(lesson())
    assert s.mark("Квиток, будь ласка!") == "Квито́к, будь ла́ска!"
    assert s.mark("«КВИТОК»?") == "«КВИТО́К»?"
    assert s.mark("ось квиток.") == "ось квито́к."  # «ось» is unknown and stays; «квиток» is found


def test_dictionary_covers_every_lesson_text_and_the_fixed_phrases():
    s = Stresser(lesson())
    assert s.mark("добрий") == "до́брий"  # step line
    assert s.mark("запитайте ціну") == "запита́йте ціну́"  # recall prompt
    assert s.mark("слухаю") == "слу́хаю"  # a fixed phrase of the engine
    assert s.mark("закінчено") == "закі́нчено"  # the closing line


def test_correction_list_and_extending_it():
    s = Stresser(lesson())
    assert s.mark("У мене є квиток.") == "У мене́ є квито́к."
    assert s.mark("Мене") == "Мене́"
    assert Stresser(lesson(), {"тут": "ту́т"}).mark("тут і мене") == "ту́т і мене"  # a custom list replaces the default


def test_unknown_words_stay_unmarked():
    assert Stresser(lesson()).mark("Холодно, правда?") == "Холодно, правда?"


def test_apostrophes_and_marks_do_not_split_words():
    lesson_ = lesson()
    lesson_.opening.append("Ім’я́ моє́.")
    s = Stresser(lesson_)
    assert s.mark("ім’я") == "ім’я́"
    assert s.mark("Ім'я моє") == "Ім’я́ моє́"  # an ASCII apostrophe finds the same word
