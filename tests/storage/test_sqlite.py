from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import sqlite3
import subprocess
import sys
import threading

import pytest

from voice_teacher.storage import Store, StorageError, RevisionConflict, EventConflict, SchemaVersionError
from voice_teacher.storage.migrations import APPLICATION_ID, V1


def snapshot(revision=0, sequence=1):
    return dict(schema_version=1, kind="session_snapshot", learner_id="learner", session_id="session",
                revision=revision, event_sequence=sequence, mode="free_conversation", status="active", source=None,
                curriculum_snapshot=None, topic="Synthetic topic", language="uk", instruction_language="en",
                learner_profile={"level": "beginner"}, engine_state={"format_version": 1, "data": {"turn": revision}})


def event(identity, sequence, kind, *, state=None, turn=None, supersedes=None):
    return dict(schema_version=1, kind="progress_event", event_id=identity, learner_id="learner", session_id="session",
                sequence=sequence, occurred_at="2026-10-16T12:00:00Z", event_type=kind,
                mode="free_conversation", source=None, turn=deepcopy(turn),
                assistance={"kind": "none", "help_level": 0, "target_exposed": False} if kind in {"turn.accepted", "evidence.recorded"} else None,
                provenance={"original_source": None, "original_item": None, "practice_source": None,
                            "origin_session_id": "session", "origin_turn_id": turn["turn_id"] if turn else "initial"},
                evidence={"outcome": "independent", "attempt": "Привіт", "preferred": None, "reason": None, "recognition_uncertain": False}
                if kind == "evidence.recorded" else None, snapshot=state, supersedes_event_id=supersedes)


def initial():
    return [event("state-0", 1, "state.saved", state=snapshot())]


def transition():
    t = {"turn_id": "turn-1", "index": 0, "role": "learner", "text": "Привіт"}
    teacher = {"turn_id": "teacher-1", "index": 1, "role": "teacher", "text": "До́бре."}
    return [event("accepted-1", 2, "turn.accepted", turn=t), event("evidence-1", 3, "evidence.recorded", turn=t),
            event("reply-1", 4, "teacher.reply_planned", turn=teacher), event("state-1", 5, "state.saved", state=snapshot(1, 5))]


def ready(tmp_path):
    store = Store(tmp_path / "private")
    store.save_learner("learner", {"level": "beginner"})
    store.commit("learner", "session", initial(), expected_revision=None,
                 activities=[{"activity_id": "activity-1", "position": 0, "data": {"part": "all"}}])
    return store


def counts(store):
    with sqlite3.connect(store.path) as c:
        return {table: c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ["sessions", "events", "activities", "turns", "observations", "evidence", "outbox"]}


def test_restart_rebuild_and_outbox_preserve_underlying_evidence(tmp_path):
    store = ready(tmp_path)
    store.commit("learner", "session", transition(), expected_revision=0)
    before, projection = store.events("learner", "session"), store.projection("learner", "session")
    assert [e["event_id"] for e in before] == ["state-0", "accepted-1", "evidence-1", "reply-1", "state-1"]
    assert [e["sequence"] for e in before] == [1, 2, 3, 4, 5]
    assert projection["evidence"][0]["event_id"] == "evidence-1"
    assert [t["turn_id"] for t in projection["turns"]] == ["turn-1", "teacher-1"]
    store.record_export_attempt("state-0", succeeded=True)
    store.record_export_attempt("evidence-1", succeeded=False)
    pending = store.pending_exports()
    assert next(j for j in pending if j["job_id"] == "evidence-1")["attempts"] == 1
    assert len(pending) == 4
    restarted = Store(tmp_path / "private")
    assert restarted.learner("learner") == {"level": "beginner"}
    assert restarted.session("learner", "session") == snapshot(1, 5)
    assert restarted.projection("learner", "session") == projection
    with sqlite3.connect(store.path) as c:
        c.execute("DELETE FROM evidence")
        c.execute("DELETE FROM observations")
        c.execute("DELETE FROM turns")
        c.execute("UPDATE sessions SET snapshot_json='{}', revision=99")
    assert restarted.rebuild("learner", "session") == snapshot(1, 5)
    assert restarted.events("learner", "session") == before
    assert restarted.projection("learner", "session") == projection
    assert restarted.pending_exports() == pending  # completed/retried work is not reset


def test_write_survives_actual_writer_process_exit(tmp_path):
    state_file = tmp_path / "synthetic-events.json"
    state_file.write_text(json.dumps(initial() + transition()))
    script = """import json,sys
from voice_teacher.storage import Store
s=Store(sys.argv[1]);s.save_learner('learner',{'level':'beginner'})
e=json.load(open(sys.argv[2]));s.commit('learner','session',e[:1],expected_revision=None)
s.commit('learner','session',e[1:],expected_revision=0)
"""
    subprocess.run([sys.executable, "-c", script, str(tmp_path / "private"), str(state_file)], check=True)
    store = Store(tmp_path / "private")
    assert store.events("learner", "session") == initial() + transition()
    assert store.session("learner", "session") == snapshot(1, 5)


@pytest.mark.parametrize("table", ["events", "evidence", "outbox"])
def test_injected_failure_rolls_back_state_evidence_activities_and_jobs(tmp_path, table):
    store = ready(tmp_path)
    before = counts(store)
    with sqlite3.connect(store.path) as c:
        c.execute(f"CREATE TRIGGER injected_failure BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected transaction failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        store.commit("learner", "session", transition(), expected_revision=0,
                     activities=[{"activity_id": "activity-2", "position": 1, "data": {"part": "2"}}])
    assert counts(store) == before
    assert store.session("learner", "session") == snapshot()
    assert store.events("learner", "session") == initial()
    with sqlite3.connect(store.path) as c:
        c.execute("DROP TRIGGER injected_failure")
    store.commit("learner", "session", transition(), expected_revision=0)
    assert counts(store)["evidence"] == 1


def test_failed_creation_leaves_no_session_or_orphan_job(tmp_path):
    store = Store(tmp_path / "private")
    store.save_learner("learner", {})
    with sqlite3.connect(store.path) as c:
        c.execute("CREATE TRIGGER injected_failure BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.commit("learner", "session", initial(), expected_revision=None)
    assert all(n == 0 for n in counts(store).values())


def test_duplicate_ids_and_conflicting_contents_cannot_overwrite_history(tmp_path):
    store = ready(tmp_path)
    store.commit("learner", "session", transition(), expected_revision=0)
    with pytest.raises(RevisionConflict):
        store.commit("learner", "session", transition(), expected_revision=0)
    for changed in [False, True]:
        e = event("state-0", 6, "state.saved", state=snapshot(2, 6))
        if changed:
            e["snapshot"]["engine_state"]["data"] = {"corrupted": True}
        with pytest.raises(EventConflict):
            store.commit("learner", "session", [e], expected_revision=1)
    assert len(store.events("learner", "session")) == 5
    assert len(store.pending_exports()) == 5
    for sql in ["UPDATE events SET body_json='{}'", "DELETE FROM events"]:
        with sqlite3.connect(store.path) as c, pytest.raises(sqlite3.IntegrityError, match="append-only"):
            c.execute(sql)


def test_revision_ownership_and_parallel_updates(tmp_path):
    store = ready(tmp_path)
    barrier = threading.Barrier(2)
    def attempt():
        barrier.wait()
        try:
            store.commit("learner", "session", transition(), expected_revision=0)
            return "committed"
        except RevisionConflict:
            return "stale"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results) == ["committed", "stale"]
    assert len(store.events("learner", "session")) == 5
    with pytest.raises(KeyError):
        store.session("other-learner", "session")
    with pytest.raises(StorageError, match="ownership"):
        store.commit("other-learner", "session", transition(), expected_revision=1)


@pytest.mark.parametrize("change", ["gap", "orphan", "changed-turn", "pinned", "revision"])
def test_invalid_transition_cannot_partially_update_snapshot(tmp_path, change):
    store = ready(tmp_path)
    batch = transition()
    if change == "gap": batch[0]["sequence"] = 9
    if change == "orphan": batch.pop(0)
    if change == "changed-turn": batch[1]["turn"]["text"] = "different"
    if change == "pinned": batch[-1]["snapshot"]["language"] = "fr"
    if change == "revision": batch[-1]["snapshot"]["revision"] = 7
    with pytest.raises(ValueError):
        store.commit("learner", "session", batch, expected_revision=0)
    assert store.events("learner", "session") == initial()
    assert store.session("learner", "session") == snapshot()


def test_supersession_preserves_original_observation(tmp_path):
    store = ready(tmp_path)
    store.commit("learner", "session", transition(), expected_revision=0)
    t = transition()[0]["turn"]
    update = [event("supersede-1", 6, "observation.superseded", turn=t, supersedes="evidence-1"),
              event("state-2", 7, "state.saved", state=snapshot(2, 7))]
    store.commit("learner", "session", update, expected_revision=1)
    before = store.events("learner", "session")
    assert len(store.projection("learner", "session")["observations"]) == 2
    assert len(store.projection("learner", "session")["evidence"]) == 1
    store.rebuild("learner", "session")
    assert store.events("learner", "session") == before


@pytest.mark.parametrize("reference", ["missing-observation", "state-0"])
def test_invalid_supersession_rolls_back_its_state_and_export(tmp_path, reference):
    store = ready(tmp_path)
    store.commit("learner", "session", transition(), expected_revision=0)
    update = [event("supersede-1", 6, "observation.superseded", turn=transition()[0]["turn"], supersedes=reference),
              event("state-2", 7, "state.saved", state=snapshot(2, 7))]
    with pytest.raises(StorageError, match="earlier observation"):
        store.commit("learner", "session", update, expected_revision=1)
    assert store.events("learner", "session") == initial() + transition()
    assert len(store.pending_exports()) == 5


def test_supersession_cannot_reference_another_learners_observation(tmp_path):
    store = ready(tmp_path)
    store.commit("learner", "session", transition(), expected_revision=0)
    store.save_learner("other", {})
    seed = initial()
    seed[0]["event_id"] = "other-state-0"
    seed[0]["learner_id"] = seed[0]["snapshot"]["learner_id"] = "other"
    store.commit("other", "session", seed, expected_revision=None)
    t = transition()[0]["turn"]
    batch = [event("other-accept", 2, "turn.accepted", turn=t),
             event("other-supersede", 3, "observation.superseded", turn=t, supersedes="evidence-1"),
             event("other-state-1", 4, "state.saved", state=snapshot(1, 4))]
    for e in batch:
        e["learner_id"] = "other"
        if e["snapshot"]: e["snapshot"]["learner_id"] = "other"
    with pytest.raises(StorageError, match="this learner"):
        store.commit("other", "session", batch, expected_revision=0)
    assert store.events("other", "session") == seed
    assert len(store.events("learner", "session")) == 5


def test_rebuild_failure_cannot_drop_existing_evidence(tmp_path):
    store = ready(tmp_path)
    store.commit("learner", "session", transition(), expected_revision=0)
    before = store.projection("learner", "session")
    with sqlite3.connect(store.path) as c:
        c.execute("CREATE TRIGGER injected_rebuild_failure BEFORE INSERT ON evidence BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.rebuild("learner", "session")
    assert store.projection("learner", "session") == before
    assert store.events("learner", "session") == initial() + transition()


def test_new_database_permissions_and_foreign_keys(tmp_path):
    store = ready(tmp_path)
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert store.path.parent.stat().st_mode & 0o777 == 0o700
    with store._connection() as c:
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert c.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
        assert c.execute("PRAGMA user_version").fetchone()[0] == 2
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []


def legacy(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir()
    path = directory / "voice-teacher.sqlite"
    with sqlite3.connect(path) as c:
        for sql in V1: c.execute(sql)
        c.execute(f"PRAGMA application_id={APPLICATION_ID}")
        c.execute("PRAGMA user_version=1")
        c.execute("INSERT INTO learners VALUES ('learner','{}')")
        c.execute("INSERT INTO sessions VALUES (?,?,?,?,?)", ("learner", "session", 1, 5, json.dumps(snapshot(1, 5))))
        for e in initial() + transition():
            c.execute("INSERT INTO events VALUES (?,?,?,?,?)", (e["event_id"], "learner", "session", e["sequence"], json.dumps(e)))
    return directory


def test_supported_v1_migration_backfills_projections_and_pending_exports(tmp_path):
    store = Store(legacy(tmp_path))
    assert store.session("learner", "session") == snapshot(1, 5)
    assert store.events("learner", "session") == initial() + transition()
    assert len(store.pending_exports()) == 5
    assert len(store.projection("learner", "session")["evidence"]) == 1
    assert len(store.projection("learner", "session")["turns"]) == 2
    with sqlite3.connect(store.path) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 2


def test_failed_migration_rolls_back_all_ddl_and_schema_version(tmp_path, monkeypatch):
    import voice_teacher.storage.sqlite as implementation
    directory = legacy(tmp_path)
    monkeypatch.setattr(implementation, "V2", (*implementation.V2, "SELECT nonexistent_migration_function()"))
    with pytest.raises(sqlite3.OperationalError):
        Store(directory)
    with sqlite3.connect(directory / "voice-teacher.sqlite") as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 1
        assert c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall() == [("events",), ("learners",), ("sessions",)]
        assert c.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 5


@pytest.mark.parametrize("version,brand", [(99, APPLICATION_ID), (1, 1234), (0, 0)])
def test_future_foreign_or_unversioned_database_refused_without_modification(tmp_path, version, brand):
    directory = tmp_path / "private"; directory.mkdir()
    path = directory / "voice-teacher.sqlite"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE unrelated (value TEXT)")
        c.execute("INSERT INTO unrelated VALUES ('preserve')")
        c.execute(f"PRAGMA user_version={version}"); c.execute(f"PRAGMA application_id={brand}")
    digest, modified = hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns
    class Guard(Store):
        def _connection(self):
            raise AssertionError("a writable connection must not be opened")
    with pytest.raises(SchemaVersionError): Guard(directory)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert path.stat().st_mtime_ns == modified
    assert list(directory.iterdir()) == [path]


def test_newer_schema_in_uncheckpointed_wal_is_seen_and_refused(tmp_path):
    directory = tmp_path / "private"; directory.mkdir()
    path = directory / "voice-teacher.sqlite"
    with sqlite3.connect(path) as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA wal_autocheckpoint=0")
        c.execute(f"PRAGMA application_id={APPLICATION_ID}")
        c.execute("CREATE TABLE future_data(value)")
        c.execute("PRAGMA user_version=99")
        c.execute("INSERT INTO future_data VALUES ('preserve')")
        c.commit()
        wal = directory / "voice-teacher.sqlite-wal"
        before = [p.read_bytes() for p in [path, wal]]
        with pytest.raises(SchemaVersionError, match="newer"):
            Store(directory)
        assert [p.read_bytes() for p in [path, wal]] == before
        assert c.execute("SELECT value FROM future_data").fetchone()[0] == "preserve"


def test_data_location_refuses_checkouts_declared_sources_and_database_symlinks(tmp_path):
    checkout = tmp_path / "checkout"; checkout.mkdir(); (checkout / ".git").write_text("gitdir: elsewhere")
    with pytest.raises(StorageError, match="outside"):
        Store(checkout / "data")
    source = tmp_path / "content"; source.mkdir()
    with pytest.raises(StorageError, match="outside"):
        Store(source / "data", forbidden_roots=[source])
    private = tmp_path / "private"; private.mkdir()
    (private / "voice-teacher.sqlite").symlink_to(tmp_path / "elsewhere.sqlite")
    with pytest.raises(StorageError, match="symlinks"):
        Store(private)
