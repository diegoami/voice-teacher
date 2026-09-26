"""Command line: providers, transcribe, report, run, openings."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .providers import PROVIDERS, ProviderError, transcribe
from .report import opening_report, recording_report
from .score import reading_list, score_recording

HERE = Path(__file__).resolve().parent.parent
TRANSCRIPTS = HERE / "fixtures" / "transcripts"


def load_env(path: Path) -> None:
    """KEY=value lines from a git-ignored .env next to this POC; the shell wins."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip().removeprefix("export ").strip(), value.strip().strip("'\""))


def out_dir(audio: Path, root: Path) -> Path:
    return root / audio.stem


def cmd_transcribe(audio: Path, names: list[str], force: bool, root: Path) -> list[str]:
    """Transcribe with each provider that has a key; return the reasons for any skipped."""
    target = out_dir(audio, root)
    target.mkdir(parents=True, exist_ok=True)
    missing = []
    for name in names:
        provider = PROVIDERS[name]
        path = target / f"{name}.json"
        if path.exists() and not force:
            print(f"{name}: cached ({path.relative_to(root.parent)})", file=sys.stderr)
            continue
        key = provider.key()
        if not key:
            missing.append(f"{name} (set {provider.key_env})")
            print(f"{name}: skipped, {provider.key_env} is not set", file=sys.stderr)
            continue
        print(f"{name}: sending {audio.name} to {provider.model}…", file=sys.stderr)
        try:
            record = transcribe(provider, audio, key)
        except (ProviderError, OSError, ValueError) as exc:
            missing.append(f"{name} ({exc})")
            print(f"{name}: failed: {exc}", file=sys.stderr)
            continue
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{name}: {record['seconds']} s, {len(record['text'].split())} words", file=sys.stderr)
    return missing


def cmd_report(audio: Path, names: list[str], reading: Path, root: Path, missing: list[str]) -> str:
    sentences = reading_list(reading)
    runs = []
    for name in names:
        path = out_dir(audio, root) / f"{name}.json"
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            runs.append((record, score_recording(sentences, record["text"])))
        elif not any(m.startswith(name + " ") for m in missing):
            missing.append(f"{name} (no transcript yet)")
    report = recording_report(audio.name, reading.name, sentences, runs, missing)
    target = out_dir(audio, root)
    target.mkdir(parents=True, exist_ok=True)
    (target / "report.md").write_text(report, encoding="utf-8")
    return report


def main() -> int:
    load_env(HERE / ".env")
    parser = argparse.ArgumentParser(prog="python -m stt")
    parser.add_argument("--reading-list", type=Path, default=HERE / "reading_list.md")
    parser.add_argument("--transcripts", type=Path, default=TRANSCRIPTS,
                        help="where raw responses and reports go (git-ignored)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("providers", help="list providers and whether their key is set")
    for name, text in [("transcribe", "send a recording to the providers"),
                       ("report", "score the saved transcripts of a recording"),
                       ("run", "transcribe, then report")]:
        p = sub.add_parser(name, help=text)
        p.add_argument("audio", type=Path)
        p.add_argument("--provider", action="append", choices=sorted(PROVIDERS),
                       help="only this provider (repeatable); default: all")
        if name != "report":
            p.add_argument("--force", action="store_true", help="ask again even if a transcript is saved")
    op = sub.add_parser("openings", help="score the opening repetitions in lesson transcripts")
    op.add_argument("transcript", type=Path, nargs="+")
    args = parser.parse_args()

    if args.command == "providers":
        for p in PROVIDERS.values():
            print(f"{p.name:11} {p.model:18} {p.key_env:19} {'set' if p.key() else 'not set'}")
        return 0
    if args.command == "openings":
        print(opening_report(args.transcript, reading_list(args.reading_list)), end="")
        return 0

    audio = args.audio.resolve()
    if not audio.is_file():
        parser.error(f"no such file: {args.audio}")
    names = args.provider or list(PROVIDERS)
    missing = []
    if args.command in ("transcribe", "run"):
        missing = cmd_transcribe(audio, names, args.force, args.transcripts)
    if args.command in ("report", "run"):
        print(cmd_report(audio, names, args.reading_list, args.transcripts, missing), end="")
        print(f"\nSaved to {out_dir(audio, args.transcripts) / 'report.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
