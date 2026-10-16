"""Internal SQLite schema versions; independent of interchange schema versions."""
APPLICATION_ID = 0x56544348  # VTCH
VERSION = 7

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

V3 = (
    """CREATE TABLE requests (
        learner_id TEXT NOT NULL, session_id TEXT NOT NULL, request_id TEXT NOT NULL,
        expected_revision INTEGER NOT NULL CHECK(expected_revision >= 0), input_json TEXT NOT NULL,
        stage TEXT NOT NULL CHECK(stage IN ('accepted','judged','committed','delivered','cancelled')),
        judgment_json TEXT, result_json TEXT, delivery_json TEXT,
        PRIMARY KEY(learner_id, session_id, request_id),
        FOREIGN KEY(learner_id, session_id) REFERENCES sessions(learner_id, session_id))""",
    "CREATE UNIQUE INDEX requests_active ON requests(learner_id, session_id) WHERE stage IN ('accepted','judged')",
)

V4 = (
    "CREATE TABLE sources (source_id TEXT PRIMARY KEY, config_json TEXT NOT NULL, last_error TEXT)",
    """CREATE TABLE source_versions (
        version_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(source_id),
        payload_json TEXT NOT NULL, UNIQUE(source_id, version_id))""",
    """CREATE TABLE source_active (
        source_id TEXT PRIMARY KEY REFERENCES sources(source_id), version_id TEXT NOT NULL,
        FOREIGN KEY(source_id, version_id) REFERENCES source_versions(source_id, version_id))""",
    """CREATE TABLE source_items (
        source_id TEXT NOT NULL REFERENCES sources(source_id), course_id TEXT NOT NULL, item_id TEXT NOT NULL,
        item_revision INTEGER NOT NULL CHECK(item_revision >= 1), definition_hash TEXT NOT NULL,
        PRIMARY KEY(source_id, course_id, item_id, item_revision))""",
)

V5 = (
    """CREATE TABLE pairing_codes (
        code_hash TEXT PRIMARY KEY, learner_id TEXT NOT NULL REFERENCES learners(learner_id),
        label TEXT NOT NULL, expires REAL NOT NULL)""",
    """CREATE TABLE clients (
        token_hash TEXT PRIMARY KEY, client_id TEXT NOT NULL UNIQUE,
        learner_id TEXT NOT NULL REFERENCES learners(learner_id), label TEXT NOT NULL,
        expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1)))""",
)

V6 = (
    """CREATE TABLE speech_requests (
        learner_id TEXT NOT NULL, session_id TEXT NOT NULL, request_id TEXT NOT NULL,
        input_json TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('accepted','recognized','empty','failed')),
        transcript_json TEXT, reported_problem INTEGER NOT NULL DEFAULT 0 CHECK(reported_problem IN (0,1)),
        PRIMARY KEY(learner_id,session_id,request_id),
        FOREIGN KEY(learner_id,session_id) REFERENCES sessions(learner_id,session_id))""",
    """CREATE TABLE speech_cache (
        audio_id TEXT PRIMARY KEY, text TEXT NOT NULL, language TEXT NOT NULL, config_json TEXT NOT NULL,
        sha256 TEXT NOT NULL, size INTEGER NOT NULL CHECK(size>0))""",
    """CREATE TABLE speech_attachments (
        learner_id TEXT NOT NULL, session_id TEXT NOT NULL, plan_id TEXT NOT NULL,
        position INTEGER NOT NULL CHECK(position>=0), audio_id TEXT NOT NULL REFERENCES speech_cache(audio_id),
        PRIMARY KEY(learner_id,session_id,plan_id,position),
        FOREIGN KEY(learner_id,session_id) REFERENCES sessions(learner_id,session_id))""",
)

V7 = (
    """CREATE TABLE feedback_decisions (
        learner_id TEXT NOT NULL, session_id TEXT NOT NULL, request_id TEXT NOT NULL,
        context_json TEXT NOT NULL, decision_json TEXT NOT NULL,
        PRIMARY KEY(learner_id,session_id,request_id),
        FOREIGN KEY(learner_id,session_id,request_id) REFERENCES requests(learner_id,session_id,request_id))""",
)
