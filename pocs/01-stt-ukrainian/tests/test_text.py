from stt.align import align, distance
from stt.text import is_other_script, is_russian, number_words, plain, words


def test_words_drop_stress_punctuation_and_unify_apostrophes():
    assert words("Ні, хвили́н п’ять пі́шки.") == ["ні", "хвилин", "п'ять", "пішки"]
    assert plain("Іді́ть") == "Ідіть"
    assert words("Ідіть") == ["ідіть"]  # й and ї survive: no decomposition
    assert words("йти, їхати") == ["йти", "їхати"]


def test_digits_are_spelt_out():
    assert words("5 хвилин") == ["п'ять", "хвилин"]
    assert words("ще 200 метрів") == ["ще", "двісті", "метрів"]
    assert number_words(20) == ["двадцять"]
    assert number_words(125) == ["сто", "двадцять", "п'ять"]
    assert number_words(310) == ["триста", "десять"]


def test_russian_spellings_are_caught():
    russian = "где находится станция это нет потом идите мне можно выходить пьет перекрестия".split()
    assert [w for w in russian if not is_russian(w)] == []


def test_ukrainian_is_not_russian():
    ukrainian = words(
        "Перепрошую, де знаходиться станція метро? Як пройти до центру? Ідіть прямо до "
        "перехрестя, а потім поверніть праворуч. Ні, хвилин п'ять пішки. Дякую. Мені "
        "потрібно до автовокзалу. Він зупиняється тут? Добрий день, тебе, уже, там, сім'я.")
    assert [w for w in ukrainian if is_russian(w)] == []


def test_other_script():
    assert is_other_script("hello")
    assert is_other_script("καλά")
    assert not is_other_script("станція")
    assert not is_other_script("п'ять")


def test_align_counts_edits():
    ops = align("a b c d".split(), "a x c d e".split())
    assert [op.kind for op in ops] == ["ok", "sub", "ok", "ok", "ins"]
    ops = align("a b c".split(), "a c".split())
    assert [op.kind for op in ops] == ["ok", "del", "ok"]
    assert distance("праворуч", "правую") == 3
