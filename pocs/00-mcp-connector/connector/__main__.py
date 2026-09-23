"""Command line: serve, sessions, report, export."""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DEFAULT_REPO = HERE.parents[2] / "learnukrainian"


def token(data: Path) -> str:
    if os.environ.get("CONNECTOR_TOKEN"):
        return os.environ["CONNECTOR_TOKEN"]
    path = data / "token"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(24), encoding="utf-8")
        path.chmod(0o600)
    return path.read_text(encoding="utf-8").strip()


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m connector")
    parser.add_argument("--learnukrainian", type=Path, default=Path(os.environ.get("LEARNUKRAINIAN", DEFAULT_REPO)))
    parser.add_argument("--data", type=Path, default=HERE / "data")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the MCP server")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--pin", help="serve this voice-sessions folder instead of the newest unused one")
    sub.add_parser("sessions", help="list recorded connector sessions")
    rep = sub.add_parser("report", help="POC metrics for a session")
    rep.add_argument("session_id")
    exp = sub.add_parser("export", help="print the transcript, or write it into learnukrainian")
    exp.add_argument("session_id")
    exp.add_argument("--write", action="store_true", help="write voice-sessions/<folder>/transcript.md")
    exp.add_argument("--force", action="store_true", help="overwrite a transcript that is not the template")
    args = parser.parse_args()

    from .export import report, transcript, write_transcript
    from .store import Store

    sessions_dir = args.learnukrainian / "pimsleur-review" / "voice-sessions"
    store = Store(args.data / "sessions")

    if args.command == "serve":
        import uvicorn

        from .server import Lessons, app

        secret = token(args.data)
        print(f"Local MCP endpoint: http://127.0.0.1:{args.port}/{secret}/mcp", file=sys.stderr)
        print(f"Connector URL:      https://<tunnel host>/{secret}/mcp", file=sys.stderr)
        lessons = Lessons(sessions_dir, store, args.pin)
        uvicorn.run(app(lessons, secret), host="127.0.0.1", port=args.port, log_level="info")
        return 0
    if args.command == "sessions":
        print("\n".join(store.sessions()) or "no sessions yet")
        return 0
    events = store.read(args.session_id)
    if args.command == "report":
        print(report(args.session_id, events))
        return 0
    if args.write:
        print(write_transcript(args.session_id, events, sessions_dir, args.force))
    else:
        template = (sessions_dir / events[0]["folder"] / "transcript.md").read_text(encoding="utf-8")
        print(transcript(args.session_id, events, template))
    return 0


if __name__ == "__main__":
    sys.exit(main())
