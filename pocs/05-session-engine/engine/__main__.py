"""Command line: lesson (build lesson.json from a package), review."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from .package import Lesson, parse_package

HERE = Path(__file__).resolve().parent.parent
LESSONS = HERE / "fixtures" / "lessons"
DEFAULT_REPO = HERE.parents[2] / "learnukrainian"


def load_env(path: Path) -> None:
    """KEY=value lines from a git-ignored .env next to this POC; the shell wins."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip().removeprefix("export ").strip(), value.strip().strip("'\""))


def review(data: dict) -> str:
    """A sheet for the learner to check the derived targets."""
    lesson = Lesson.from_dict(data["lesson"])
    lines = [
        f"# {lesson.part} — {lesson.title}: targets to check",
        "",
        f"From `{lesson.source}` in learnukrainian. The teacher does not see a step's targets "
        "until you have tried the step; it uses them to judge your answer and, after two "
        "failed tries, says the first one. Check that each is what you would be expected to "
        "say, and that the stress marks are right.",
        "",
        "## Guided sequence",
        "",
        f"_{lesson.scenario}_",
        "",
        "| # | Teacher says | You are to | Targets | Practises |",
        "| --- | --- | --- | --- | --- |",
    ]
    for s in lesson.steps:
        teacher = (f"_{s.setting}_ " if s.setting else "") + s.teacher_line
        expected = s.expected + (" _(any correct answer)_" if s.open_answer else "")
        lines.append(f"| {s.number} | {teacher} | {expected} | {'<br>'.join(s.targets) or '—'} | {s.phrase or '—'} |")
    lines += ["", "## Delayed recall", "", "| # | Prompt | Targets | Practises |", "| --- | --- | --- | --- |"]
    for r in lesson.recall:
        lines.append(f"| {r.number} | {r.prompt} | {'<br>'.join(r.targets) or '—'} | {r.phrase or '—'} |")
    unverified = data.get("unverified_stress") or []
    lines += ["", "## Stress marks not taken from the brief", ""]
    lines += [f"- {w}" for w in unverified] if unverified else ["None: every mark in the targets is the brief's own."]
    return "\n".join(lines) + "\n"


def main() -> int:
    load_env(HERE / ".env")
    parser = argparse.ArgumentParser(prog="python -m engine")
    parser.add_argument("--learnukrainian", type=Path, default=Path(os.environ.get("LEARNUKRAINIAN", DEFAULT_REPO)))
    sub = parser.add_subparsers(dest="command", required=True)
    lp = sub.add_parser("lesson", help="build fixtures/lessons/<part>.json from a voice-sessions package")
    lp.add_argument("folder", help="voice-sessions folder name, e.g. 2026-09-26-session-4B")
    lp.add_argument("--no-derive", action="store_true", help="parse only; leave the targets empty")
    rp = sub.add_parser("review", help="print the targets of a lesson.json for checking")
    rp.add_argument("lesson", type=Path)
    args = parser.parse_args()

    if args.command == "review":
        print(review(json.loads(args.lesson.read_text(encoding="utf-8"))), end="")
        return 0

    folder = args.learnukrainian / "pimsleur-review" / "voice-sessions" / args.folder
    lesson = parse_package(folder)
    out = {"created": date.today().isoformat(), "lesson": None, "derived_by": None,
           "usage": None, "unverified_stress": []}
    if not args.no_derive:
        from .derive import derive, unverified_stress  # needs a key only here
        lesson, usage = derive(lesson)
        out.update(derived_by=usage["model"], usage=usage,
                   unverified_stress=unverified_stress(lesson, (folder / "package.md").read_text(encoding="utf-8")))
        cost = f", ${usage['cost_usd']:.4f}" if usage.get("cost_usd") is not None else ""
        print(f"Derived with {usage['model']}: {usage['input_tokens']} tokens in, "
              f"{usage['output_tokens']} out{cost}", file=sys.stderr)
    out["lesson"] = lesson.to_dict()
    LESSONS.mkdir(parents=True, exist_ok=True)
    path = LESSONS / f"{lesson.part}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    (LESSONS / f"{lesson.part}-review.md").write_text(review(out), encoding="utf-8")
    print(f"Wrote {path} and {lesson.part}-review.md", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
