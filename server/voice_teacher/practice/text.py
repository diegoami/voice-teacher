import re
import unicodedata
from .profiles import LanguageProfile, UKRAINIAN


def plain(text: str, profile: LanguageProfile = UKRAINIAN) -> str:
    if profile.stress_mark is None:
        return text
    return unicodedata.normalize("NFC", unicodedata.normalize("NFD", text).replace(profile.stress_mark, ""))


def normalise(text: str, profile: LanguageProfile = UKRAINIAN) -> str:
    text = plain(text, profile).lower()
    for mark in "’ʼ'`":
        text = text.replace(mark, "")
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())
