"""Transactional local event storage. Provider calls belong to the coordinator."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import sqlite3

from schemas.validate import canonical_json, validate_event_stream
from .migrations import APPLICATION_ID, VERSION, V1, V2, V3, V4, V5, V6, V7


class StorageError(ValueError):
    pass


class RevisionConflict(StorageError):
    pass


class EventConflict(StorageError):
    pass


class SchemaVersionError(StorageError):
    pass


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", value):
        raise StorageError("invalid identity")
    return value


def _object(value):
    if not isinstance(value, dict):
        raise StorageError("expected JSON object")
    return canonical_json(value)


def _project(c, e):
    body = canonical_json(e)
    if e["event_type"] in {"turn.accepted", "teacher.reply_planned"}:
        t = e["turn"]
        c.execute("INSERT INTO turns VALUES (?,?,?,?,?)",
                  (e["learner_id"], e["session_id"], t["turn_id"], t["index"], canonical_json(t)))
    if e["event_type"] in {"evidence.recorded", "observation.superseded"}:
        supersedes = e["supersedes_event_id"]
        if supersedes is not None:
            previous = c.execute("SELECT learner_id, session_id, sequence, body_json FROM events WHERE event_id=?", (supersedes,)).fetchone()
            if previous is None or previous["learner_id"] != e["learner_id"] or (
                previous["session_id"] == e["session_id"] and previous["sequence"] >= e["sequence"]
            ) or json.loads(previous["body_json"])["event_type"] not in {"evidence.recorded", "observation.superseded"}:
                raise StorageError("supersession must reference an earlier observation for this learner")
        c.execute("INSERT INTO observations VALUES (?,?,?)", (e["event_id"], supersedes, body))
    if e["event_type"] == "evidence.recorded":
        c.execute("INSERT INTO evidence VALUES (?,?)", (e["event_id"], body))


def _version(c):
    version = c.execute("PRAGMA user_version").fetchone()[0]
    brand = c.execute("PRAGMA application_id").fetchone()[0]
    if version > VERSION:
        raise SchemaVersionError("database schema is newer than this application; use a compatible server")
    if version < 0 or (version != 0 and brand != APPLICATION_ID):
        raise SchemaVersionError("database is not a supported voice-teacher schema")
    if version == 0 and (brand not in {0, APPLICATION_ID} or c.execute(
            "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1").fetchone()):
        raise SchemaVersionError("refusing an unversioned nonempty database")
    return version


class Store:
    def __init__(self, data_dir, *, forbidden_roots=(), timeout=5.0):
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise StorageError("database timeout must be positive and finite")
        self.timeout = timeout
        directory = Path(data_dir).expanduser().resolve()
        protected = [Path(__file__).resolve().parent.parent, *(Path(p).resolve() for p in forbidden_roots)]
        if any(directory == p or p in directory.parents for p in protected) or any(
                (p / ".git").exists() for p in [directory, *directory.parents]):
            raise StorageError("server data must be outside code/content/Git checkouts")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "voice-teacher.sqlite"
        if self.path.is_symlink():
            raise StorageError("database symlinks are not supported")
        if self.path.exists():
            # Refuse future/foreign schemas before any writable connection or PRAGMA.
            c = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=timeout)
            try:
                _version(c)
            finally:
                c.close()
        else:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass  # another initializer won; recheck under the write lock below
            else:
                os.close(fd)
        with self._transaction() as c:
            version = _version(c)
            if version == 0:
                for sql in V1:
                    c.execute(sql)
                c.execute(f"PRAGMA application_id={APPLICATION_ID}")
                c.execute("PRAGMA user_version=1")
                version = 1
            if version == 1:
                for sql in V2:
                    c.execute(sql)
                events = [json.loads(r[0]) for r in c.execute("SELECT body_json FROM events ORDER BY learner_id, session_id, sequence")]
                validate_event_stream(events)
                for e in events:
                    _project(c, e)
                    c.execute("INSERT INTO outbox(job_id) VALUES (?)", (e["event_id"],))
                c.execute("PRAGMA user_version=2")
                version = 2
            if version == 2:
                for sql in V3:
                    c.execute(sql)
                c.execute("PRAGMA user_version=3")
                version = 3
            if version == 3:
                for sql in V4:
                    c.execute(sql)
                c.execute("PRAGMA user_version=4")
                version = 4
            if version == 4:
                for sql in V5:
                    c.execute(sql)
                c.execute("PRAGMA user_version=5")
                version = 5
            if version == 5:
                for sql in V6:
                    c.execute(sql)
                c.execute("PRAGMA user_version=6")
                version = 6
            if version == 6:
                for sql in V7:
                    c.execute(sql)
                c.execute("PRAGMA user_version=7")

    @contextmanager
    def _connection(self):
        c = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA synchronous=FULL")
            yield c
        finally:
            c.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.commit()
            except BaseException:
                c.rollback()
                raise

    def save_learner(self, learner_id, profile):
        learner_id, body = _id(learner_id), _object(profile)
        with self._transaction() as c:
            c.execute("INSERT INTO learners VALUES (?,?) ON CONFLICT(learner_id) DO UPDATE SET profile_json=excluded.profile_json", (learner_id, body))

    def learner(self, learner_id):
        with self._connection() as c:
            row = c.execute("SELECT profile_json FROM learners WHERE learner_id=?", (_id(learner_id),)).fetchone()
            if row is None:
                raise KeyError("learner not found")
            return json.loads(row[0])

    def session(self, learner_id, session_id):
        with self._connection() as c:
            row = c.execute("SELECT snapshot_json FROM sessions WHERE learner_id=? AND session_id=?", (_id(learner_id), _id(session_id))).fetchone()
            if row is None:
                raise KeyError("session not found for this learner")
            return json.loads(row[0])

    def events(self, learner_id, session_id):
        with self._connection() as c:
            return self._events(c, _id(learner_id), _id(session_id))

    @staticmethod
    def _events(c, learner_id, session_id):
        return [json.loads(row[0]) for row in c.execute(
            "SELECT body_json FROM events WHERE learner_id=? AND session_id=? ORDER BY sequence", (learner_id, session_id))]

    def commit(self, learner_id, session_id, events, *, expected_revision, activities=(), _completion=None):
        """Append one transition ending in state.saved. Duplicate IDs are conflicts.

        None means create at revision zero; updates require current revision + 1.
        No provider callbacks run here. Inputs are copied before taking the lock.
        """
        learner_id, session_id = _id(learner_id), _id(session_id)
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise RevisionConflict("invalid expected revision")
        batch = json.loads(canonical_json(events))
        activity_rows = json.loads(canonical_json(list(activities)))
        if not isinstance(batch, list) or not batch or any(not isinstance(e, dict) for e in batch):
            raise StorageError("nonempty event batch required")
        if any((e.get("learner_id"), e.get("session_id")) != (learner_id, session_id) for e in batch):
            raise StorageError("event ownership does not match the requested learner/session")
        if [e.get("event_type") for e in batch].count("state.saved") != 1 or batch[-1].get("event_type") != "state.saved":
            raise StorageError("each transition must end with exactly one state.saved event")
        validate_event_stream(batch, partial=True)
        snapshot = batch[-1]["snapshot"]
        next_revision = 0 if expected_revision is None else expected_revision + 1
        if snapshot["revision"] != next_revision:
            raise RevisionConflict("snapshot must advance the expected revision by one")
        for a in activity_rows:
            if not isinstance(a, dict) or set(a) != {"activity_id", "position", "data"} or type(a["position"]) is not int or a["position"] < 0:
                raise StorageError("invalid activity descriptor")
            _id(a["activity_id"])
            _object(a["data"])
        with self._transaction() as c:
            if _completion is not None:
                request_id, result = _completion
                _id(request_id)
                result_body = _object(result)
                request = c.execute("SELECT stage, expected_revision FROM requests WHERE learner_id=? AND session_id=? AND request_id=?",
                                    (learner_id, session_id, request_id)).fetchone()
                if request is None or request["expected_revision"] != expected_revision:
                    raise RevisionConflict("request does not own this transition")
                if request["stage"] in {"committed", "delivered"}:
                    saved = c.execute("SELECT snapshot_json FROM sessions WHERE learner_id=? AND session_id=?", (learner_id, session_id)).fetchone()
                    return json.loads(saved[0])  # caller reloads original request result
                if request["stage"] not in {"accepted", "judged"}:
                    raise RevisionConflict("request has been cancelled")
            row = c.execute("SELECT revision FROM sessions WHERE learner_id=? AND session_id=?", (learner_id, session_id)).fetchone()
            if (row is None) != (expected_revision is None) or (row is not None and row[0] != expected_revision):
                raise RevisionConflict("session revision changed or does not exist for this learner")
            old = self._events(c, learner_id, session_id)
            for e in batch:
                if c.execute("SELECT 1 FROM events WHERE event_id=?", (e["event_id"],)).fetchone():
                    raise EventConflict("event ID already exists; no records were changed")
            validate_event_stream(old + batch)
            if old:
                prior = next(e["snapshot"] for e in reversed(old) if e["event_type"] == "state.saved")
                for key in ("mode", "source", "curriculum_snapshot", "language", "instruction_language", "topic"):
                    if prior[key] != snapshot[key]:
                        raise StorageError("session content and language must remain pinned")
            body = canonical_json(snapshot)
            if row is None:
                c.execute("INSERT INTO sessions VALUES (?,?,?,?,?)", (learner_id, session_id, next_revision, snapshot["event_sequence"], body))
            else:
                changed = c.execute("UPDATE sessions SET revision=?, event_sequence=?, snapshot_json=? WHERE learner_id=? AND session_id=? AND revision=?",
                                    (next_revision, snapshot["event_sequence"], body, learner_id, session_id, expected_revision)).rowcount
                if changed != 1:
                    raise RevisionConflict("session revision changed")
            for a in activity_rows:
                c.execute("INSERT INTO activities VALUES (?,?,?,?,?)", (learner_id, session_id, a["activity_id"], a["position"], canonical_json(a["data"])))
            for e in batch:
                c.execute("INSERT INTO events VALUES (?,?,?,?,?)", (e["event_id"], learner_id, session_id, e["sequence"], canonical_json(e)))
                _project(c, e)
                c.execute("INSERT INTO outbox(job_id) VALUES (?)", (e["event_id"],))
            if _completion is not None:
                c.execute("UPDATE requests SET stage='committed', result_json=? WHERE learner_id=? AND session_id=? AND request_id=?",
                          (result_body, learner_id, session_id, request_id))
        return snapshot

    def projection(self, learner_id, session_id):
        learner_id, session_id = _id(learner_id), _id(session_id)
        with self._connection() as c:
            # One read transaction gives a consistent view while another writer commits.
            c.execute("BEGIN")
            result = {"activities": [dict(r) for r in c.execute(
                "SELECT activity_id, position, data_json FROM activities WHERE learner_id=? AND session_id=? ORDER BY position", (learner_id, session_id))]}
            result["activities"] = [{"activity_id": a["activity_id"], "position": a["position"], "data": json.loads(a["data_json"])} for a in result["activities"]]
            result["turns"] = [json.loads(r[0]) for r in c.execute("SELECT body_json FROM turns WHERE learner_id=? AND session_id=? ORDER BY turn_index, turn_id", (learner_id, session_id))]
            for table in ("observations", "evidence"):
                result[table] = [json.loads(r[0]) for r in c.execute(f"SELECT p.body_json FROM {table} p JOIN events e USING(event_id) WHERE e.learner_id=? AND e.session_id=? ORDER BY e.sequence", (learner_id, session_id))]
            return result

    def rebuild(self, learner_id, session_id):
        learner_id, session_id = _id(learner_id), _id(session_id)
        with self._transaction() as c:
            events = self._events(c, learner_id, session_id)
            if not events:
                raise KeyError("session not found for this learner")
            validate_event_stream(events)
            c.execute("DELETE FROM turns WHERE learner_id=? AND session_id=?", (learner_id, session_id))
            for table in ("observations", "evidence"):
                c.execute(f"DELETE FROM {table} WHERE event_id IN (SELECT event_id FROM events WHERE learner_id=? AND session_id=?)", (learner_id, session_id))
            for e in events:
                _project(c, e)
            snapshot = next(e["snapshot"] for e in reversed(events) if e["event_type"] == "state.saved")
            c.execute("UPDATE sessions SET revision=?, event_sequence=?, snapshot_json=? WHERE learner_id=? AND session_id=?",
                      (snapshot["revision"], snapshot["event_sequence"], canonical_json(snapshot), learner_id, session_id))
        return snapshot

    def pending_exports(self, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise StorageError("invalid outbox limit")
        with self._connection() as c:
            return [dict(r) for r in c.execute("SELECT o.job_id, o.attempts, e.learner_id, e.session_id, e.sequence FROM outbox o JOIN events e ON e.event_id=o.job_id WHERE o.status='pending' ORDER BY e.learner_id, e.session_id, e.sequence LIMIT ?", (limit,))]

    def record_export_attempt(self, job_id, *, succeeded):
        if type(succeeded) is not bool:
            raise StorageError("succeeded must be boolean")
        with self._transaction() as c:
            count = c.execute("UPDATE outbox SET attempts=attempts+1, status=? WHERE job_id=? AND status='pending'", ("done" if succeeded else "pending", _id(job_id))).rowcount
            if count != 1 and c.execute("SELECT 1 FROM outbox WHERE job_id=?", (job_id,)).fetchone() is None:
                raise KeyError("outbox job not found")
