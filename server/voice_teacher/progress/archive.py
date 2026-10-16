"""Immutable per-session event prefixes and atomic, idempotent replay."""
from collections import defaultdict
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from schemas.validate import canonical_json, validate_event_stream
from ..storage import Store
from ..storage.sqlite import _id


class ArchiveError(ValueError):
    pass


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _bytes(value):
    return canonical_json(value).encode("utf-8")


def _directory(root, relative, *, create=False):
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink(): raise ArchiveError("archive symlinks are refused")
        if create:
            try:
                path.mkdir(mode=0o700)
                _sync(path.parent)
            except FileExistsError:
                pass
        if not path.is_dir(): raise ArchiveError("archive directory missing")
    return path


def _sync(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


class _ReplayStore(Store):
    """Reuse Store's transition invariants inside the import's one transaction."""
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def _transaction(self):
        yield self.connection

    @contextmanager
    def _connection(self):
        yield self.connection


def _resolve(events):
    """Resolve historical references against the complete available archive."""
    sources, turns, observations = {}, set(), {}
    for e in events:
        if e["event_type"] == "state.saved" and e["source"] is not None:
            sources[canonical_json(e["source"])] = e["snapshot"]["curriculum_snapshot"]
        if e["event_type"] in {"turn.accepted", "teacher.reply_planned"}:
            turns.add((e["learner_id"], e["session_id"], e["turn"]["turn_id"]))
        if e["event_type"] in {"evidence.recorded", "observation.superseded"}:
            observations[e["event_id"]] = e
    for e in events:
        p = e["provenance"]
        if (e["learner_id"], p["origin_session_id"], p["origin_turn_id"]) not in turns:
            raise ArchiveError("unresolved learner/session/turn provenance")
        original, item = p["original_source"], p["original_item"]
        if original is not None:
            curriculum = sources.get(canonical_json(original))
            if curriculum is None: raise ArchiveError("unresolved historical source snapshot")
            if item is not None and not any(c["course_id"] == item["course_id"] and any(
                    i["item_id"] == item["item_id"] and i["item_revision"] == item["item_revision"] for i in c["items"])
                    for c in curriculum["courses"]):
                raise ArchiveError("unresolved historical item revision")
        if e["supersedes_event_id"] is not None:
            previous = observations.get(e["supersedes_event_id"])
            if previous is None or previous["learner_id"] != e["learner_id"]:
                raise ArchiveError("unresolved superseded observation")


def _chunks(events):
    result, chunk = [], []
    for event in events:
        chunk.append(event)
        if event["event_type"] == "state.saved":
            result.append(chunk); chunk = []
    if chunk: raise ArchiveError("history ends before a durable checkpoint")
    return result


def readable_history(events):
    """Derived view only. Canonical events, including supersessions, stay intact."""
    lines = []
    for e in events:
        prefix = f'{e["learner_id"]}/{e["session_id"]} #{e["sequence"]}'
        if e["event_type"] == "evidence.recorded":
            p, a = e["provenance"], e["assistance"]
            lines.append(f'{prefix}: {e["evidence"]["outcome"]}; assistance={a["kind"]}; original={canonical_json(p["original_item"])}; attempt={e["evidence"]["attempt"]}; preferred={e["evidence"]["preferred"]}')
        elif e["event_type"] == "observation.superseded":
            lines.append(f'{prefix}: supersedes {e["supersedes_event_id"]}')
        elif e["event_type"] in {"turn.accepted", "teacher.reply_planned"}:
            lines.append(f'{prefix}: {e["turn"]["role"]}: {e["turn"]["text"]}')
        elif e["event_type"] == "state.saved":
            lines.append(f'{prefix}: saved {e["snapshot"]["status"]} revision {e["snapshot"]["revision"]}')
    return "\n".join(lines) + ("\n" if lines else "")


class Archive:
    NAMESPACE = Path("voice-teacher/v1/batches")

    def __init__(self, destination, *, forbidden_roots=(), max_batch_bytes=16 * 1024 * 1024,
                 max_archive_bytes=256 * 1024 * 1024, max_batches=10000):
        self.root = Path(destination).expanduser().resolve()
        protected = [Path(__file__).resolve().parents[3], *(Path(p).resolve() for p in forbidden_roots)]
        if any(self.root.is_relative_to(p) or p.is_relative_to(self.root) for p in protected):
            raise ArchiveError("progress destination overlaps code/content/runtime storage")
        if not self.root.is_dir(): raise ArchiveError("configured private destination must already exist")
        if any(type(v) is not int or v <= 0 for v in (max_batch_bytes, max_archive_bytes, max_batches)):
            raise ArchiveError("archive limits must be positive integers")
        self.max_batch_bytes, self.max_archive_bytes, self.max_batches = max_batch_bytes, max_archive_bytes, max_batches

    def _publish(self, value):
        data = _bytes(value)
        if len(data) > self.max_batch_bytes: raise ArchiveError("batch exceeds configured byte limit")
        directory = _directory(self.root, self.NAMESPACE, create=True)
        name = _digest(data) + ".json"
        final = directory / name
        if final.is_symlink(): raise ArchiveError("archive symlinks are refused")
        fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
            try:
                # Exclusive publication: never overwrite an immutable existing batch.
                os.link(temporary, final)
            except FileExistsError:
                if final.is_symlink(): raise ArchiveError("archive symlinks are refused")
                with final.open("rb") as f: existing = f.read(self.max_batch_bytes + 1)
                if existing != data:
                    raise ArchiveError("immutable batch collision") from None
            _sync(directory)
        finally:
            os.unlink(temporary)
        return name

    def export(self, store):
        if store.path.is_relative_to(self.root) or self.root.is_relative_to(store.path.parent):
            raise ArchiveError("progress destination overlaps runtime storage")
        with store._connection() as c:
            c.execute("BEGIN")
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='sources'").fetchone():
                for row in c.execute("SELECT config_json FROM sources"):
                    checkout = Path(json.loads(row[0])["checkout"]).resolve()
                    if self.root.is_relative_to(checkout) or checkout.is_relative_to(self.root):
                        raise ArchiveError("progress destination overlaps a registered content checkout")
            sessions = c.execute("SELECT DISTINCT e.learner_id,e.session_id FROM outbox o JOIN events e ON e.event_id=o.job_id WHERE o.status='pending' ORDER BY e.learner_id,e.session_id").fetchall()
            available = [json.loads(r[0]) for r in c.execute("SELECT body_json FROM events ORDER BY learner_id,session_id,sequence")]
            payloads = []
            for row in sessions:
                learner, session = row
                events = store._events(c, learner, session)
                activities = [{"activity_id": a[0], "position": a[1], "data": json.loads(a[2])} for a in c.execute(
                    "SELECT activity_id,position,data_json FROM activities WHERE learner_id=? AND session_id=? ORDER BY position", (learner, session))]
                payloads.append({"schema_version": 1, "kind": "private_progress_batch", "learner_id": learner,
                                 "session_id": session, "events": events, "activities": activities})
        validate_event_stream(available)
        _resolve(available)
        written = []
        for payload in payloads:
            try:
                name = self._publish(payload)
                # Crash before this acknowledgement simply republishes identical bytes.
                with store._transaction() as c:
                    c.executemany("UPDATE outbox SET status='done',attempts=attempts+1 WHERE job_id=? AND status='pending'",
                                  [(e["event_id"],) for e in payload["events"]])
                written.append(name)
            except Exception:
                with store._transaction() as c:
                    c.executemany("UPDATE outbox SET attempts=attempts+1 WHERE job_id=? AND status='pending'",
                                  [(e["event_id"],) for e in payload["events"]])
                raise
        return written

    def _read(self):
        namespace = self.root / "voice-teacher"
        if namespace.is_symlink(): raise ArchiveError("archive symlinks are refused")
        if not namespace.exists(): return [], {}
        directory = _directory(self.root, self.NAMESPACE)
        events, activities, consumed = {}, defaultdict(dict), 0
        paths = sorted(directory.iterdir())
        if len(paths) > self.max_batches: raise ArchiveError("archive exceeds configured batch count")
        for path in paths:
            if path.is_symlink(): raise ArchiveError("archive symlinks are refused")
            if path.name.startswith(".pending-"): continue
            if not re.fullmatch(r"[a-f0-9]{64}\.json", path.name) or not path.is_file():
                raise ArchiveError("unexpected file in app batch namespace")
            with path.open("rb") as f: data = f.read(self.max_batch_bytes + 1)
            consumed += len(data)
            if len(data) > self.max_batch_bytes or consumed > self.max_archive_bytes:
                raise ArchiveError("archive exceeds configured byte limit")
            if path.stem != _digest(data): raise ArchiveError("batch checksum mismatch or incomplete write")
            try: value = json.loads(data)
            except ValueError: raise ArchiveError("batch is not valid JSON") from None
            if not isinstance(value, dict) or set(value) != {"schema_version", "kind", "learner_id", "session_id", "events", "activities"} or value["schema_version"] != 1 or value["kind"] != "private_progress_batch":
                raise ArchiveError("unsupported batch format")
            if _bytes(value) != data: raise ArchiveError("batch is not canonical JSON")
            key = (_id(value["learner_id"]), _id(value["session_id"]))
            if not isinstance(value["events"], list) or not value["events"] or not isinstance(value["activities"], list):
                raise ArchiveError("nonempty session events and activity list required")
            for e in value["events"]:
                if not isinstance(e, dict) or (e.get("learner_id"), e.get("session_id")) != key:
                    raise ArchiveError("batch event ownership mismatch")
            validate_event_stream(value["events"])
            _chunks(value["events"])
            for e in value["events"]:
                old = events.setdefault(e["event_id"], e)
                if old != e: raise ArchiveError("event ID has different contents")
            for a in value["activities"]:
                if not isinstance(a, dict) or set(a) != {"activity_id", "position", "data"} or type(a["position"]) is not int or a["position"] < 0 or not isinstance(a["data"], dict):
                    raise ArchiveError("invalid activity descriptor")
                identity = _id(a["activity_id"])
                old = activities[key].setdefault(identity, a)
                if old != a: raise ArchiveError("activity ID has different contents")
        ordered = sorted(events.values(), key=lambda e: (e["learner_id"], e["session_id"], e["sequence"]))
        validate_event_stream(ordered)
        return ordered, activities

    def read(self):
        events, _ = self._read()
        _resolve(events)
        return events

    def restore(self, store):
        if store.path.is_relative_to(self.root) or self.root.is_relative_to(store.path.parent):
            raise ArchiveError("progress archive and runtime database must be separate")
        incoming, activities = self._read()
        grouped = defaultdict(list)
        for e in incoming: grouped[(e["learner_id"], e["session_id"])].append(e)
        imported = 0
        # No filesystem/provider/Git work while holding this transaction.
        with store._transaction() as c:
            replay = _ReplayStore(c)
            existing = [json.loads(r[0]) for r in c.execute("SELECT body_json FROM events ORDER BY learner_id,session_id,sequence")]
            combined = {e["event_id"]: e for e in existing}
            for e in incoming:
                if combined.setdefault(e["event_id"], e) != e: raise ArchiveError("event ID has different contents")
            all_events = sorted(combined.values(), key=lambda e: (e["learner_id"], e["session_id"], e["sequence"]))
            validate_event_stream(all_events)
            _resolve(all_events)
            pending = []
            for (learner, session), events in grouped.items():
                old = replay.events(learner, session)
                if events[:min(len(old), len(events))] != old[:min(len(old), len(events))]:
                    raise ArchiveError("session archive differs from existing history")
                chunks = _chunks(events[len(old):])
                if chunks and c.execute("SELECT 1 FROM requests WHERE learner_id=? AND session_id=? AND stage IN ('accepted','judged')", (learner, session)).fetchone():
                    raise ArchiveError("session has unfinished provider work; stop it before restore")
                for chunk in chunks: pending.append((learner, session, chunk))
            present = {e["event_id"] for e in existing}
            while pending:
                advanced = False
                for row in list(pending):
                    learner, session, chunk = row
                    # Preserve each session order and cross-session supersession dependencies.
                    if chunk[0]["sequence"] != len(replay.events(learner, session)) + 1: continue
                    if any(e["supersedes_event_id"] is not None and e["supersedes_event_id"] not in present and
                           e["supersedes_event_id"] not in {x["event_id"] for x in chunk[:i]} for i, e in enumerate(chunk)): continue
                    snapshot = chunk[-1]["snapshot"]
                    if not c.execute("SELECT 1 FROM learners WHERE learner_id=?", (learner,)).fetchone():
                        replay.save_learner(learner, snapshot["learner_profile"])
                    revision = None if chunk[0]["sequence"] == 1 else replay.session(learner, session)["revision"]
                    replay.commit(learner, session, chunk, expected_revision=revision)
                    imported += len(chunk); present.update(e["event_id"] for e in chunk)
                    pending.remove(row); advanced = True
                if not advanced: raise ArchiveError("cyclic or unresolved checkpoint dependencies")
            for (learner, session), rows in activities.items():
                for a in rows.values():
                    old = c.execute("SELECT position,data_json FROM activities WHERE learner_id=? AND session_id=? AND activity_id=?", (learner, session, a["activity_id"])).fetchone()
                    if old is not None:
                        if (old[0], json.loads(old[1])) != (a["position"], a["data"]): raise ArchiveError("activity ID has different contents")
                    else:
                        c.execute("INSERT INTO activities VALUES (?,?,?,?,?)", (learner, session, a["activity_id"], a["position"], canonical_json(a["data"])))
            # Imported events are already exported locally. No remote-push claim.
            c.executemany("UPDATE outbox SET status='done' WHERE job_id=?", [(e["event_id"],) for e in incoming])
        return imported
