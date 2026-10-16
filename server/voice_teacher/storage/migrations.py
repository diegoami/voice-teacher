"""Internal SQLite schema versions; independent of interchange schema versions."""
APPLICATION_ID = 0x56544348  # VTCH
VERSION = 2

V1 = (
    "CREATE TABLE learners (learner_id TEXT PRIMARY KEY, profile_json TEXT NOT NULL)",
    """CREATE TABLE sessions (
        learner_id TEXT NOT NULL REFERENCES learners(learner_id), session_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision >= 0), event_sequence INTEGER NOT NULL CHECK(event_sequence >= 1),
        snapshot_json TEXT NOT NULL, PRIMARY KEY(learner_id, session_id))""",
    """CREATE TABLE events (
        event_id TEXT PRIMARY KEY, learner_id TEXT NOT NULL, session_id TEXT NOT NULL,
        sequence INTEGER NOT NULL CHECK(sequence >= 1), body_json TEXT NOT NULL,
        UNIQUE(learner_id, session_id, sequence),
        FOREIGN KEY(learner_id, session_id) REFERENCES sessions(learner_id, session_id))""",
)
V2 = (
    """CREATE TABLE activities (
        learner_id TEXT NOT NULL, session_id TEXT NOT NULL, activity_id TEXT NOT NULL,
        position INTEGER NOT NULL CHECK(position >= 0), data_json TEXT NOT NULL,
        PRIMARY KEY(learner_id, session_id, activity_id), UNIQUE(learner_id, session_id, position),
        FOREIGN KEY(learner_id, session_id) REFERENCES sessions(learner_id, session_id))""",
    """CREATE TABLE turns (
        learner_id TEXT NOT NULL, session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
        turn_index INTEGER NOT NULL CHECK(turn_index >= 0), body_json TEXT NOT NULL,
        PRIMARY KEY(learner_id, session_id, turn_id),
        FOREIGN KEY(learner_id, session_id) REFERENCES sessions(learner_id, session_id))""",
    """CREATE TABLE observations (
        event_id TEXT PRIMARY KEY REFERENCES events(event_id),
        supersedes_event_id TEXT REFERENCES events(event_id), body_json TEXT NOT NULL)""",
    "CREATE TABLE evidence (event_id TEXT PRIMARY KEY REFERENCES events(event_id), body_json TEXT NOT NULL)",
    """CREATE TABLE outbox (
        job_id TEXT PRIMARY KEY REFERENCES events(event_id), status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','done')), attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0))""",
    "CREATE TRIGGER immutable_events_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END",
    "CREATE TRIGGER immutable_events_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END",
)
