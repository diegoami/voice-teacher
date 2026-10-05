"""Command line: lesson (build lesson.json from a package), review, play, simulate, serve."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from .package import Lesson, parse_package, plain

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


def load_lesson(path: Path) -> Lesson:
    return Lesson.from_dict(json.loads(path.read_text(encoding="utf-8"))["lesson"])


def save_session(session, name: str) -> Path:
    from datetime import datetime
    folder = HERE / "fixtures" / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    with path.open("w", encoding="utf-8") as out:
        for event in session.log:
            out.write(json.dumps(event, ensure_ascii=False) + "\n")
        for e in session.evidence:
            out.write(json.dumps({"event": "evidence", **e.__dict__}, ensure_ascii=False) + "\n")
    return path


def play(lesson_path: Path, model: str | None, part: str = "all") -> int:
    """A typed lesson in the terminal: the teacher's lines in plain spelling, the task card, your answer."""
    try:
        import readline  # noqa: F401  enables line editing for input() (uv's Linux Python links libedit)
    except ImportError:
        pass
    from .judge import LLMJudge
    from .session import Session
    lesson = load_lesson(lesson_path)
    session = Session(lesson, LLMJudge(lesson, model=model), part=part)
    print(f"Lesson {lesson.part}: {lesson.title}. Model: {session.judge.model}. Type your answers; Ctrl+D stops.\n")
    says, card = session.start(), None
    while True:
        for say in says:
            print(f"  Teacher: {plain(say.text)}")
        if session.done:
            break
        if session.card and session.card != card:
            print(f"  [{session.card}]")
        card = session.card
        try:
            text = input("  You: ").strip()
        except EOFError:
            print()
            break
        if text:
            says = session.hear(text)
    path = save_session(session, lesson.part if part == "all" else f"{lesson.part}-p{part}")
    judged = [e for e in session.log if e["event"] == "judge"]
    seconds = sorted(e["seconds"] for e in judged)
    cost = sum((e["usage"].get("cost_usd") or 0) for e in judged)
    counts: dict[str, int] = {}
    for e in session.evidence:
        if e.phase == "guided" and e.round > 0 or e.phase == "recall":
            counts[e.label] = counts.get(e.label, 0) + 1
    print(f"\nEvidence (rounds 1–2 and recall): {counts}")
    if seconds:
        print(f"Model calls: {len(seconds)}, median {seconds[len(seconds) // 2]} s, cost ${cost:.4f}")
    print(f"Session log: {path}")
    return 0


def secret_token() -> str:
    """The secret URL prefix: fixtures/token (git-ignored), created on the first run."""
    import secrets
    path = HERE / "fixtures" / "token"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(24), encoding="utf-8")
        path.chmod(0o600)
    return path.read_text(encoding="utf-8").strip()


def serve(lesson_path: Path, port: int, model: str | None, keep_recordings: bool = True,
          part: str = "all") -> int:
    """The voice lesson as a web app on 127.0.0.1; the tunnel (run.sh) makes it reachable from the phone."""
    import uvicorn
    from .judge import LLMJudge
    from .server import create_app
    from .voice import ElevenLabs
    lesson = load_lesson(lesson_path)
    try:
        voice = ElevenLabs()
        LLMJudge(lesson, model=model)  # fail now, not at the first turn, when a key is missing
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    token = secret_token()
    app = create_app(lesson, token, voice.transcribe, voice.synthesise,
                     lambda lesson: LLMJudge(lesson, model=model), HERE / "fixtures" / "tts-cache",
                     save=lambda session, part: save_session(session, part),
                     recordings=HERE / "fixtures" / "recordings" if keep_recordings else None, part=part)
    print(f"Lesson {lesson.part}, part {part}. Local address: http://127.0.0.1:{port}/{token}/", file=sys.stderr)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


def simulate(lesson_path: Path, models: list[str], seed: int, tag: str = "") -> int:
    """The same simulated lesson for each teacher model; writes fixtures/simulations/<part>.md."""
    from .judge import LLMJudge
    from .simulate import report, run, write_script
    lesson = load_lesson(lesson_path)
    script_path = lesson_path.with_name(f"{lesson.part}-learner.json")
    if script_path.exists():
        answers = json.loads(script_path.read_text(encoding="utf-8"))["answers"]
    else:
        answers, usage = write_script(lesson)
        script_path.write_text(json.dumps({"written_by": usage["model"], "usage": usage, "answers": answers},
                                          ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Learner script written by {usage['model']} (${usage.get('cost_usd') or 0:.4f})", file=sys.stderr)
    from .simulate import Result
    out = HERE / "fixtures" / "simulations" / f"{lesson.part}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = out.with_suffix(".json")
    saved = json.loads(raw.read_text(encoding="utf-8")) if raw.exists() else {}
    results = []
    for model in models:
        key = f"{model} seed {seed}" + (f" {tag}" if tag else "")
        if key in saved:
            print(f"{model}: reusing the saved run", file=sys.stderr)
            results.append(Result(**saved[key]))
            continue
        print(f"{model}: simulating…", file=sys.stderr)
        results.append(run(lesson, answers, LLMJudge(lesson, model=model), seed))
        if tag:
            results[-1].model += f" ({tag})"
        saved[key] = results[-1].to_dict()
        raw.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
    text = report([Result(**r) for r in saved.values()], lesson)  # every run so far, in the order made
    out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


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
    pp = sub.add_parser("play", help="a typed lesson in the terminal")
    pp.add_argument("lesson", type=Path)
    pp.add_argument("--model", help="teacher model (default: TEACHER_MODEL)")
    pp.add_argument("--part", choices=("all", "1", "2"), default="all")
    vp = sub.add_parser("serve", help="the voice lesson as a web app (see run.sh for the phone)")
    vp.add_argument("lesson", type=Path)
    vp.add_argument("--port", type=int, default=8765)
    vp.add_argument("--model", help="teacher model (default: TEACHER_MODEL)")
    vp.add_argument("--part", choices=("all", "1", "2"), default="all",
                    help="1: opening, round 0 and round 1; 2: round 2 and recall; all: one sitting")
    vp.add_argument("--no-recordings", action="store_true",
                    help="do not keep the learner's turns (kept by default in fixtures/recordings/, git-ignored)")
    sp = sub.add_parser("simulate", help="compare teacher models on the same simulated lesson")
    sp.add_argument("lesson", type=Path)
    sp.add_argument("--model", action="append", required=True, help="teacher model (repeatable)")
    sp.add_argument("--seed", type=int, default=1)
    sp.add_argument("--tag", default="", help="label a re-run, e.g. after a prompt change; earlier runs stay saved")
    args = parser.parse_args()

    if args.command == "simulate":
        return simulate(args.lesson, args.model, args.seed, args.tag)
    if args.command == "serve":
        return serve(args.lesson, args.port, args.model, not args.no_recordings, args.part)
    if args.command == "play":
        return play(args.lesson, args.model, args.part)

    if args.command == "review":
        print(review(json.loads(args.lesson.read_text(encoding="utf-8"))), end="")
        return 0

    folder = args.learnukrainian / "pimsleur-review" / "voice-sessions" / args.folder
    lesson = parse_package(folder)
    out = {"created": date.today().isoformat(), "lesson": None, "derived_by": None,
           "usage": None, "unverified_stress": []}
    if not args.no_derive:
        from .derive import derive, unverified_stress  # needs a key only here
        import openai
        try:
            lesson, usage = derive(lesson)
        except openai.APIStatusError as exc:
            detail = exc.body.get("message") if isinstance(exc.body, dict) else exc.message
            print(f"The model request failed (HTTP {exc.status_code}): {detail}", file=sys.stderr)
            return 1
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
