"""Markdown reports: one recording across providers, and lesson openings."""

from __future__ import annotations

import re
from pathlib import Path

from .score import Sentence, SentenceResult, Summary, score_pairs, summarise
from .text import words

TURN = re.compile(r"^(?:\*\*)?(Teacher|Learner)(?:\*\*)?(?:\s*\((voice|text)\))?:\s*(.*)$")
OPENING_END = "почнімо розмову"


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def summary_row(label: str, s: Summary, extra: list[str]) -> str:
    cells = [
        label,
        f"{_pct(s.wer)} ({s.subs}/{s.dels}/{s.ins})",
        _pct(s.cer),
        f"{s.russian} ({_pct(s.russian_share)})",
        str(s.other_script),
        f"{s.exact}/{s.sentences}",
        f"{s.tagged_exact}/{s.tagged}" if s.tagged else "–",
        *extra,
    ]
    return "| " + " | ".join(cells) + " |"


SUMMARY_HEAD = ("| {first} | WER (sub/del/ins) | CER | Russian-spelt words | Other-script words "
                "| Sentences exact | 4A lines exact |{extra}\n| --- | --- | --- | --- | --- | --- | --- |{rule}")


def _verdict(r: SentenceResult) -> str:
    if r.exact:
        return "✓"
    text = f"{r.errors} err"
    if r.russian:
        text += f", {len(r.russian)} RU"
    return text


def recording_report(audio_name: str, reading_name: str, sentences: list[Sentence], runs: list[tuple[dict, list[SentenceResult]]],
                     missing: list[str]) -> str:
    total = sum(len(s.words) for s in sentences)
    lines = [
        f"# STT report — {audio_name}",
        "",
        f"Reading list: `{reading_name}`, {len(sentences)} sentences, {total} words. Language forced to Ukrainian; "
        "no prompt or keywords. WER and CER after lower-casing, dropping punctuation and "
        "stress marks, and spelling out digits. Russian-spelt words are a lower bound "
        "(see `stt/text.py`).",
        "",
        "## Summary",
        "",
        SUMMARY_HEAD.format(first="Provider (model)", extra=" Detected language | Request time |",
                            rule=" --- | --- |"),
    ]
    for record, results in runs:
        lines.append(summary_row(
            f"{record['provider']} (`{record['model']}`)", summarise(results),
            [str(record.get("detected_language") or "–"), f"{record['seconds']} s"]))
    if missing:
        lines += ["", "Not run: " + "; ".join(missing) + "."]
    if not runs:
        return "\n".join(lines) + "\n"

    providers = " | ".join(r["provider"] for r, _ in runs)
    if any(s.error for s in sentences):
        lines += ["", "## Deliberate errors", "",
                  "Kept: the recogniser wrote the mistake that was read. Corrected: it wrote the "
                  "correct Ukrainian instead, hiding the mistake. Other: neither. Controls are the "
                  "lines read without a mistake.", "",
                  "| Provider | Kept | Corrected | Other | Controls exact |", "| --- | --- | --- | --- | --- |"]
        for record, results in runs:
            s = summarise(results)
            lines.append(f"| {record['provider']} | {s.kept}/{s.planted} | {s.corrected}/{s.planted} | "
                         f"{s.planted - s.kept - s.corrected}/{s.planted} | {s.controls_exact}/{s.controls} |")
        lines += ["", "| # | Read (mistake → correct) | " + providers + " |", "| --- | --- |" + " --- |" * len(runs)]
        for k, sentence in enumerate(sentences):
            if sentence.error:
                said, correct = sentence.error
                lines.append(f"| {sentence.number} | {said} → {correct} | "
                             + " | ".join(results[k].planted for _, results in runs) + " |")

    if any("4A" in s.tags for s in sentences):
        lines += ["", "## Lines misrecognised by Claude voice mode in 4A", "",
                  "| # | Sentence | " + providers + " |", "| --- | --- |" + " --- |" * len(runs)]
        for k, sentence in enumerate(sentences):
            if "4A" in sentence.tags:
                lines.append(f"| {sentence.number} | {sentence.plain} | "
                             + " | ".join(_verdict(results[k]) for _, results in runs) + " |")

    lines += ["", "## Details", "",
              "What each provider heard, for the sentences it got wrong. This is a transcript "
              "of your voice: keep it out of the repository.", ""]
    for record, results in runs:
        lines += [f"### {record['provider']}", "", "| # | Read | Heard | Russian-spelt |",
                  "| --- | --- | --- | --- |"]
        for r in results:
            if not r.exact:
                lines.append(f"| {r.sentence.number} | {' '.join(r.sentence.words)} | "
                             f"{' '.join(r.heard) or '—'} | {', '.join(r.russian)} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def opening_pairs(transcript: str, sentences: list[Sentence]) -> list[tuple[Sentence, str]]:
    """Pair each learner voice turn of a lesson's opening with the line it repeats.

    The line is the longest reading-list sentence contained in the teacher's
    previous turn; reading stops at «Добре. А тепер почнімо розмову.», so a
    file holding several records of one lesson yields the first one only.
    """
    keyed = sorted(((" " + " ".join(s.words) + " ", s) for s in sentences), key=lambda x: -len(x[0]))
    pairs: list[tuple[Sentence, str]] = []
    pending: Sentence | None = None
    for line in transcript.splitlines():
        match = TURN.match(line.strip())
        if not match or match.group(2) == "text":
            continue
        role, said = match.group(1), match.group(3)
        if role == "Teacher":
            spoken = " " + " ".join(words(said)) + " "
            if OPENING_END in spoken:
                break
            pending = next((s for key, s in keyed if key in spoken), None)
        elif pending is not None:
            pairs.append((pending, said))
            pending = None
    return pairs


def opening_report(files: list[Path], sentences: list[Sentence]) -> str:
    lines = [
        "# Lesson openings — learner repetitions as the teacher app heard them",
        "",
        "Each learner voice turn in the opening is scored against the line the teacher had "
        "just said. Errors are the learner's and the recogniser's together.",
        "",
        SUMMARY_HEAD.format(first="Transcript (turns)", extra="", rule=""),
    ]
    for path in files:
        results = score_pairs(opening_pairs(path.read_text(encoding="utf-8"), sentences))
        lines.append(summary_row(f"{path.parent.name}/{path.name} ({len(results)})", summarise(results), []))
    return "\n".join(lines) + "\n"
