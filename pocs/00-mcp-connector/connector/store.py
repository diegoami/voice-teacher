"""Append-only session log (one JSON Lines file per connector session)."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Store:
    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def new_session(self, folder: str) -> str:
        session_id = f"{folder}-{secrets.token_hex(3)}"
        return session_id

    def path(self, session_id: str) -> Path:
        if not session_id or "/" in session_id or ".." in session_id:
            raise ValueError("invalid session id")
        return self.root / f"{session_id}.jsonl"

    def append(self, session_id: str, event: str, **data: object) -> None:
        record = {"at": now(), "event": event, **data}
        with self.path(session_id).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read(self, session_id: str) -> list[dict]:
        path = self.path(session_id)
        if not path.exists():
            raise KeyError(session_id)
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def sessions(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.jsonl"))
