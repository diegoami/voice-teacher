"""Authored teaching phrases and normalization policy for a language pair."""
from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageProfile:
    language: str
    instruction_language: str
    stress_mark: str | None
    stop_words: tuple[str, ...]
    listen: str
    new_sentences: str
    start_talk: str
    round_two: str
    continue_talk: str
    recall: str
    repeat_please: str
    listening: str
    correction: str
    opening_card: str
    model_card: str
    turn_card: str
    open_answer_card: str
    closing: str


UKRAINIAN = LanguageProfile(
    language="uk", instruction_language="en", stress_mark="\u0301",
    stop_words=("закінч", "закинч", "стоп", "досить", "кінець"),
    listen="Споча́тку послу́хайте, а по́тім повторі́ть.",
    new_sentences="Тепе́р нові́ ре́чення. Слу́хайте і повто́рюйте.",
    start_talk="До́бре. А тепе́р почні́мо розмо́ву.",
    round_two="До́бре. А тепе́р ще раз, без підка́зок.",
    continue_talk="Продо́вжимо розмо́ву. Тепе́р без підка́зок.",
    recall="Тепе́р кі́лька запита́нь.", repeat_please="Повторі́ть, будь ла́ска.",
    listening="Слу́хаю вас.", correction="Ви́правлення: {chunk}. Скажі́ть усе́ ре́чення.",
    opening_card="Listen and repeat exactly what you hear. Don't answer, even when it is a question.",
    model_card="Repeat exactly what you hear; don't answer it. You will need it to {task}.",
    turn_card="Your turn: {task}", open_answer_card=" Any correct answer will do.",
    closing="Заня́ття закі́нчено.",
)
