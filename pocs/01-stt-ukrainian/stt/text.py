"""Normalisation, tokenising and the Russian-spelling test."""

from __future__ import annotations

import re
import unicodedata

STRESS = "́"
APOSTROPHES = "’ʼ`′‘´"
UKRAINIAN_ONLY = set("іїєґ")
RUSSIAN_ONLY = set("ыэъё")

# Common words spelt this way only in Russian. The Ukrainian counterpart is in
# the comment where it is not obvious. A word that is also good Ukrainian
# («тут», «там», «до», «не», «тебе», «уже») must not be here.
RUSSIAN_WORDS = {
    "где", "как", "что", "чтобы", "нет", "да", "потом", "мне", "меня", "вот",
    "очень", "спасибо", "пожалуйста", "хорошо", "сейчас", "здесь", "тоже",
    "можно", "нужно", "надо", "или", "если", "когда", "куда", "сюда", "туда",
    "его", "ее", "они", "он", "она", "оно", "будет", "будут", "есть", "после",
    "потому", "почему", "сколько", "извините", "привет", "пока", "еще",
    "с",  # з, із, зі
    "к",  # до
}

ONES = ["нуль", "один", "два", "три", "чотири", "п'ять", "шість", "сім", "вісім", "дев'ять",
        "десять", "одинадцять", "дванадцять", "тринадцять", "чотирнадцять", "п'ятнадцять",
        "шістнадцять", "сімнадцять", "вісімнадцять", "дев'ятнадцять"]
TENS = ["", "", "двадцять", "тридцять", "сорок", "п'ятдесят", "шістдесят", "сімдесят",
        "вісімдесят", "дев'яносто"]
HUNDREDS = ["", "сто", "двісті", "триста", "чотириста", "п'ятсот", "шістсот", "сімсот",
            "вісімсот", "дев'ятсот"]


def number_words(n: int) -> list[str]:
    """Ukrainian cardinal for 0–999, as recognisers may write «5» for «п'ять»."""
    if n < 20:
        return [ONES[n]]
    words = []
    if n >= 100:
        words.append(HUNDREDS[n // 100])
        n %= 100
        if n == 0:
            return words
        if n < 20:
            return words + [ONES[n]]
    words.append(TENS[n // 10])
    if n % 10:
        words.append(ONES[n % 10])
    return words


def plain(text: str) -> str:
    """Drop stress marks and unify apostrophes; keep case and punctuation."""
    text = unicodedata.normalize("NFC", text).replace(STRESS, "")
    for mark in APOSTROPHES:
        text = text.replace(mark, "'")
    return text


def words(text: str) -> list[str]:
    """Lower-case words for scoring: punctuation dropped, digits spelt out."""
    text = plain(text).lower().replace("-", " ").replace("—", " ").replace("–", " ")
    out: list[str] = []
    for token in re.findall(r"[\w']+", text):
        token = token.strip("'_")
        if not token:
            continue
        if token.isdigit() and int(token) < 1000:
            out.extend(number_words(int(token)))
        else:
            out.append(token)
    return out


def is_russian(word: str) -> bool:
    """True when a word's spelling is Russian and not Ukrainian.

    A lower bound: a Russian word spelt with letters both languages share
    («далеко», «метро», «правую») passes as not Russian.
    """
    if UKRAINIAN_ONLY & set(word):
        return False
    if RUSSIAN_ONLY & set(word):
        return True
    if word in RUSSIAN_WORDS:
        return True
    if word.startswith("и"):  # Ukrainian writes і- (Ідіть, і); и- is Russian (Идите, и)
        return True
    if word.endswith("тся"):  # Ukrainian -ться (знаходиться), Russian -тся (находится)
        return True
    if re.search("ь[еиюя]", word):  # Ukrainian п'є, сім'я; Russian пьет, семья
        return True
    return word.endswith(("ия", "ие", "ию", "ии", "ией", "иям", "иях"))  # станція / станция


def is_other_script(word: str) -> bool:
    """True for a word with letters that are neither Cyrillic nor digits."""
    return any(ch.isalpha() and "CYRILLIC" not in unicodedata.name(ch, "") for ch in word)
