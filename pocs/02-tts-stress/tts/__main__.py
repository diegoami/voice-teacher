"""Command line: render, listen, report."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .items import VARIANTS, load_items
from .providers import KEYS, ProviderError, key_for, synthesise
from .report import report

HERE = Path(__file__).resolve().parent.parent
FIXTURES = HERE / "fixtures"
PAGE = Path(__file__).resolve().parent / "listen.html"


def load_env(path: Path) -> None:
    """KEY=value lines from a git-ignored .env next to this POC; the shell wins."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip().removeprefix("export ").strip(), value.strip().strip("'\""))


def render(items_path: Path, out: Path, variants: list[str] | None, numbers: list[int] | None,
           force: bool) -> int:
    """Synthesise every (item, variant) not yet on disk; keep a manifest of all clips."""
    items = [i for i in load_items(items_path) if not numbers or i.number in numbers]
    chosen = [v for v in VARIANTS if not variants or v.name in variants]
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"clips": {}}
    failures = 0
    for variant in chosen:
        key = key_for(variant.provider)
        if not key:
            print(f"{variant.name}: skipped, {KEYS[variant.provider]} is not set", file=sys.stderr)
            continue
        for item in items:
            rel = f"audio/{variant.name}/{item.number:02d}.mp3"
            if (out / rel).exists() and not force:
                continue
            text = variant.text(item)
            try:
                audio, seconds = synthesise(variant, text, key)
            except ProviderError as exc:
                print(f"{variant.name} #{item.number}: failed: {exc}", file=sys.stderr)
                failures += 1
                if failures >= 3:
                    print("Stopping after three failures.", file=sys.stderr)
                    return 1
                continue
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            (out / rel).write_bytes(audio)
            manifest["clips"][f"{item.number}/{variant.name}"] = {
                "item": item.number, "variant": variant.name, "provider": variant.provider,
                "model": variant.model, "marks": variant.marks, "file": rel, "seconds": seconds,
                "characters": len(text), "bytes": len(audio)}
            print(f"{variant.name} #{item.number}: {seconds} s, {len(audio) // 1024} KB", file=sys.stderr)
    manifest["items"] = [{"number": i.number, "marked": i.marked, "plain": i.plain, "targets": list(i.targets)}
                         for i in load_items(items_path)]
    out.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


class Handler(SimpleHTTPRequestHandler):
    """Serves the fixtures directory and stores the listener's verdicts."""

    def do_POST(self):  # noqa: N802
        if self.path != "/verdicts":
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            verdicts = json.loads(body)
            assert isinstance(verdicts, dict)
        except (ValueError, AssertionError):
            self.send_error(400)
            return
        target = Path(self.directory) / "verdicts.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(verdicts, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


def serve(out: Path, port: int) -> ThreadingHTTPServer:
    (out / "listen.html").write_text(PAGE.read_text(encoding="utf-8"), encoding="utf-8")
    return ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(out)))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    load_env(HERE / ".env")
    parser = argparse.ArgumentParser(prog="python -m tts")
    parser.add_argument("--items", type=Path, default=HERE / "stress_items.md")
    parser.add_argument("--out", type=Path, default=FIXTURES, help="audio, manifest and verdicts (git-ignored)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("variants", help="list the variants and whether their key is set")
    r = sub.add_parser("render", help="synthesise the clips not yet on disk")
    r.add_argument("--variant", action="append", choices=[v.name for v in VARIANTS])
    r.add_argument("--item", action="append", type=int)
    r.add_argument("--force", action="store_true")
    ls = sub.add_parser("listen", help="serve the blind listening page")
    ls.add_argument("--port", type=int, default=0)
    sub.add_parser("report", help="summarise the verdicts")
    args = parser.parse_args()

    if args.command == "variants":
        for v in VARIANTS:
            print(f"{v.name:15} {v.model:24} {'set' if key_for(v.provider) else 'not set'}")
        return 0
    if args.command == "render":
        return render(args.items, args.out, args.variant, args.item, args.force)
    if args.command == "listen":
        if not (args.out / "manifest.json").exists():
            parser.error("nothing rendered yet: run `python -m tts render` first")
        server = serve(args.out, args.port or free_port())
        print(f"Listening page: http://localhost:{server.server_address[1]}/listen.html  (Ctrl+C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    text = report(args.out)
    (args.out / "report.md").write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
