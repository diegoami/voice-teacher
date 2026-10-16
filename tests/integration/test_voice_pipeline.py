from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from voice_teacher.api import create_app
from voice_teacher.content.registry import SourceRegistry, SourceSpec
from voice_teacher.practice.coordinator import Coordinator
from voice_teacher.providers.pipeline import VoicePipeline
from voice_teacher.providers.speech import SpeechConfig, Recognition, SpeechError
from voice_teacher.storage import Store
from voice_teacher.storage.work import RequestConflict
from voice_teacher.storage.migrations import APPLICATION_ID, V1, V2, V3, V4, V5, VERSION
from test_turn_recovery import setup, Judge, LEARNER, SESSION


class Recognizer:
    def __init__(self, store, *answers): self.store = store; self.answers = list(answers); self.calls = 0
    def transcribe(self, audio, *, language, media_type):
        assert language == "uk"
        self.store.save_learner("recognition-lock-probe", {})
        self.calls += 1
        result = self.answers.pop(0) if self.answers else "привіт"
        if isinstance(result, Exception): raise result
        return Recognition(result, 1)


class Synthesizer:
    config = SpeechConfig()
    def __init__(self, store, fail=None): self.store = store; self.fail = fail; self.calls = 0; self.texts = []
    def synthesize(self, text, *, language):
        self.store.save_learner("synthesis-lock-probe", {})
        self.calls += 1; self.texts.append(text)
        if self.calls == self.fail: raise SpeechError("injected synthesis failure")
        return b"synthetic mp3:" + text.encode()


def voice(tmp_path, *, answers=(), fail=None, judge=None):
    store, coordinator, judge = setup(tmp_path, judge=judge)
    recognition, synthesis = Recognizer(store, *answers), Synthesizer(store, fail)
    return store, coordinator, judge, recognition, synthesis, VoicePipeline(store, coordinator, recognition, synthesis)


def submit(pipeline, *, request="voice-one", data=b"synthetic recording", revision=0):
    return pipeline.submit(LEARNER, SESSION, request, expected_revision=revision, data=data, media_type="audio/webm")


@pytest.mark.parametrize("answer,status", [("", "empty"), (SpeechError("SYNTHETIC_SECRET"), "failed")])
def test_empty_and_failed_recognition_never_advance_or_create_learner_corrections(tmp_path, answer, status):
    store, _, judge, recognizer, _, pipeline = voice(tmp_path, answers=[answer])
    before = store.events(LEARNER, SESSION)
    with pytest.raises(SpeechError): submit(pipeline)
    assert store.events(LEARNER, SESSION) == before
    assert judge.calls == 0
    assert pipeline.recognition(LEARNER, SESSION, "voice-one")["status"] == status
    assert pipeline.report_problem(LEARNER, SESSION, "voice-one") is True
    assert pipeline.recognition(LEARNER, SESSION, "voice-one")["reported_problem"] is True
    assert store.projection(LEARNER, SESSION)["evidence"] == []
    # Same recording can be retried after a transient failure; no raw audio persisted.
    result = submit(pipeline, request="voice-two", revision=1)
    assert result["revision"] == 2 and recognizer.calls == 2 and judge.calls == 1
    assert not list(store.path.parent.glob("*.webm"))


@pytest.mark.parametrize("fail", [1, 2])
def test_synthesis_failure_after_commit_recovers_without_recognition_judge_or_new_evidence(tmp_path, fail):
    store, _, judge, recognizer, _, pipeline = voice(tmp_path, fail=fail)
    with pytest.raises(SpeechError): submit(pipeline)
    before = store.events(LEARNER, SESSION)
    assert store.session(LEARNER, SESSION)["revision"] == 1
    assert len(store.projection(LEARNER, SESSION)["evidence"]) == 1
    script = """import json,sys
sys.path.insert(0,sys.argv[2])
from test_voice_pipeline import Recognizer,Synthesizer
from test_turn_recovery import Judge,LEARNER,SESSION
from voice_teacher.storage import Store
from voice_teacher.practice.coordinator import Coordinator
from voice_teacher.providers.pipeline import VoicePipeline
s=Store(sys.argv[1]);j=Judge(RuntimeError('must not judge'));r=Recognizer(s,RuntimeError('must not recognize'))
p=VoicePipeline(s,Coordinator(s,j,clock=lambda:0),r,Synthesizer(s))
result=p.submit(LEARNER,SESSION,'voice-one',expected_revision=0,data=b'synthetic recording',media_type='audio/webm')
print(json.dumps({'result':result,'recognizer_calls':r.calls,'judge_calls':j.calls}))
"""
    process = json.loads(subprocess.check_output([sys.executable, "-c", script, str(store.path.parent), str(Path(__file__).parent)], text=True))
    assert process["recognizer_calls"] == process["judge_calls"] == 0
    restarted = Store(store.path.parent)
    no_judge = Judge(RuntimeError("must not judge twice"))
    c = Coordinator(restarted, no_judge, clock=lambda: 0)
    no_recognition = Recognizer(restarted, RuntimeError("must not recognize twice"))
    recovered = VoicePipeline(restarted, c, no_recognition, Synthesizer(restarted))
    result = submit(recovered)
    assert result["delivery"]["audio_ids"] and result == process["result"]
    assert no_judge.calls == 0 and no_recognition.calls == 0
    assert judge.calls == 1 and recognizer.calls == 1
    assert restarted.events(LEARNER, SESSION) == before
    assert submit(recovered) == result
    with pytest.raises(RequestConflict): submit(recovered, data=b"different bytes")


def test_recognition_saved_before_failed_judge_survives_restart(tmp_path):
    store, _, _, recognizer, _, pipeline = voice(tmp_path, judge=Judge(RuntimeError("judge failed")))
    with pytest.raises(RuntimeError): submit(pipeline)
    assert store.session(LEARNER, SESSION)["revision"] == 0
    c = Coordinator(store, Judge(), clock=lambda: 0)
    recovered_recognition = Recognizer(store, RuntimeError("must use saved transcription"))
    recovered = VoicePipeline(store, c, recovered_recognition, Synthesizer(store))
    assert submit(recovered)["revision"] == 1
    assert recognizer.calls == 1 and recovered_recognition.calls == 0


def test_cache_recovery_and_audio_identity_do_not_grant_cross_session_access(tmp_path):
    store, c, _, _, synth, pipeline = voice(tmp_path)
    result = submit(pipeline)
    aid = result["delivery"]["audio_ids"][0]
    assert pipeline.read("other-learner", SESSION, aid) is None
    template = store.session(LEARNER, SESSION); template["session_id"] = "other-session"
    lesson = c._engine(template, c.judge).lesson
    c.create(template, lesson, part="2")
    assert pipeline.read(LEARNER, "other-session", aid) is None
    original = pipeline.read(LEARNER, SESSION, aid)
    path = pipeline.cache / (aid + ".mp3"); path.unlink()
    before = store.events(LEARNER, SESSION)
    assert pipeline.read(LEARNER, SESSION, aid) == original
    assert store.events(LEARNER, SESSION) == before
    path.write_bytes(b"corrupt")
    assert pipeline.read(LEARNER, SESSION, aid) == original
    path.unlink(); path.symlink_to(tmp_path / "outside")
    with pytest.raises(SpeechError, match="symlinks"): pipeline.read(LEARNER, SESSION, aid)


def test_first_reply_failure_recovers_by_owned_status_and_reports_recognition_separately(tmp_path):
    store, c, judge, recognizer, synth, pipeline = voice(tmp_path, fail=1)
    root = tmp_path / "content"; root.mkdir()
    value = store.session(LEARNER, SESSION)["curriculum_snapshot"]
    value["courses"][0]["lessons"][0]["repetition_item_ids"] = ["hello"]
    (root / "voice-teacher.json").write_text(json.dumps(value))
    registry = SourceRegistry(store); registry.register(SourceSpec("synthetic-alpha", "Synthetic", str(root), allow_dirty=True)); registry.refresh("synthetic-alpha")
    origin = "http://teacher.test"
    app = create_app(store, c, operator_token="operator-" + "x" * 40, origin=origin, audio=pipeline)
    client = TestClient(app, base_url=origin)
    code = app.state.auth.issue_code(LEARNER, "phone")["code"]
    token = client.post("/api/v1/pair", json={"code": code}).json()["token"]
    headers = {"Authorization": "Bearer " + token}
    body = dict(session_id="api-session", source_id="synthetic-alpha", course_id="basics", lesson_id="lesson-1", activity="second_sitting")
    assert client.post("/api/v1/sessions", headers=headers, json=body).status_code == 502
    before = store.events(LEARNER, "api-session")
    status = client.get("/api/v1/sessions/api-session", headers=headers)
    assert status.status_code == 200 and status.json()["audio_ids"]
    assert "\u0301" not in status.text and store.events(LEARNER, "api-session") == before
    audio_id = status.json()["audio_ids"][0]
    assert client.get(f"/api/v1/sessions/api-session/audio/{audio_id}?revision=0").status_code == 401
    assert client.get(f"/api/v1/sessions/api-session/audio/{audio_id}?revision=0", headers=headers).status_code == 200
    uploaded = client.post("/api/v1/sessions/api-session/audio?request_id=voice&expected_revision=0", headers={**headers, "Content-Type": "audio/webm"}, content=b"recording")
    assert uploaded.status_code == 200, uploaded.text
    events = store.events(LEARNER, "api-session")
    reported = client.post("/api/v1/sessions/api-session/recognition/voice/report", headers=headers, json={})
    assert reported.status_code == 200
    recognition = client.get("/api/v1/sessions/api-session/recognition/voice", headers=headers)
    assert recognition.json()["reported_problem"] is True and recognition.json()["text"] == "привіт"
    after_report = store.events(LEARNER, "api-session")
    assert after_report[:-1] == events and after_report[-1]["event_type"] == "state.saved"
    assert store.session(LEARNER, "api-session")["engine_state"]["data"]["engine"] == events[-1]["snapshot"]["engine_state"]["data"]["engine"]
    assert client.post("/api/v1/sessions/api-session/recognition/voice/report", headers=headers, json={}).json() == reported.json()
    assert store.events(LEARNER, "api-session") == after_report
    assert client.get("/api/v1/sessions/api-session/recognition/voice").status_code == 401
    assert client.post("/api/v1/sessions/api-session/recognition/missing/report", headers=headers, json={}).status_code == 404


def test_speech_and_cache_are_not_progress_export_authority(tmp_path):
    from voice_teacher.progress import Archive
    store, c, _, _, synth, pipeline = voice(tmp_path)
    # Opening deliberately models the stress-marked authored sentence.
    template = store.session(LEARNER, SESSION); template["session_id"] = "opening"
    lesson = c._engine(template, c.judge).lesson
    c.create(template, lesson)
    result = c.presentation(LEARNER, "opening")
    assert "Приві́т" in synth.texts
    assert all("\u0301" not in t["display"] for t in result["teacher"])
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in pipeline.cache.glob("*.mp3"))
    destination = tmp_path / "progress"; destination.mkdir()
    archive = Archive(destination); archive.export(store)
    assert not list(destination.rglob("*.mp3"))
    assert b"speech_requests" not in b"".join(p.read_bytes() for p in destination.rglob("*.json"))


def test_recognition_report_survives_later_turns_export_and_restore_without_rewriting_evidence(tmp_path):
    from voice_teacher.progress import Archive
    store, c, _, _, _, pipeline = voice(tmp_path)
    submit(pipeline)
    evidence = store.projection(LEARNER, SESSION)["evidence"]
    before = store.session(LEARNER, SESSION)["engine_state"]["data"]["engine"]
    assert pipeline.report_problem(LEARNER, SESSION, "voice-one")
    assert store.session(LEARNER, SESSION)["engine_state"]["data"]["engine"] == before
    assert store.projection(LEARNER, SESSION)["evidence"] == evidence
    c.control(LEARNER, SESSION, "stop", expected_revision=2, operation="stop")
    destination = tmp_path / "progress"; destination.mkdir()
    archive = Archive(destination); archive.export(store)
    restored = Store(tmp_path / "restored"); archive.restore(restored)
    recovered = VoicePipeline(restored, Coordinator(restored, Judge()), Recognizer(restored), Synthesizer(restored))
    report = recovered.recognition(LEARNER, SESSION, "voice-one")
    assert report == pipeline.recognition(LEARNER, SESSION, "voice-one")
    assert report["reported_problem"] is True
    assert restored.projection(LEARNER, SESSION)["evidence"] == evidence
    assert recovered.report_problem(LEARNER, SESSION, "voice-one")
    assert restored.events(LEARNER, SESSION) == store.events(LEARNER, SESSION)


def test_reporting_uncommitted_recognition_cancels_only_its_pending_judge_and_allows_a_fresh_recording(tmp_path):
    store, c, _, recognizer, _, pipeline = voice(tmp_path, judge=Judge(RuntimeError("judge failed")))
    with pytest.raises(RuntimeError): submit(pipeline)
    assert pipeline.report_problem(LEARNER, SESSION, "voice-one")
    assert store.session(LEARNER, SESSION)["revision"] == 1
    assert store.projection(LEARNER, SESSION)["evidence"] == []
    assert submit(pipeline, request="voice-two", revision=1)["revision"] == 2
    assert recognizer.calls == 2


def test_v1_coordinator_capsule_resumes_and_upgrades_without_losing_engine_state(tmp_path):
    store, c, _, _, _, pipeline = voice(tmp_path)
    snapshot = store.session(LEARNER, SESSION)
    snapshot["engine_state"]["data"]["coordinator_version"] = 1
    # A genuine old capsule uses the same native engine data and profile hashes.
    engine = c._engine(snapshot, c.judge)
    assert engine.snapshot() == snapshot["engine_state"]["data"]["engine"]
    events = store.events(LEARNER, SESSION)
    events[-1]["snapshot"] = snapshot
    legacy = Store(tmp_path / "legacy-runtime")
    legacy.save_learner(LEARNER, snapshot["learner_profile"])
    legacy.commit(LEARNER, SESSION, events, expected_revision=None)
    old = VoicePipeline(legacy, Coordinator(legacy, Judge()), Recognizer(legacy), Synthesizer(legacy))
    submit(old)
    assert legacy.session(LEARNER, SESSION)["engine_state"]["data"]["coordinator_version"] == 2


def test_recognition_report_retries_after_checkpoint_failure_without_duplicate_annotation(tmp_path):
    store, _, _, _, _, pipeline = voice(tmp_path)
    submit(pipeline)
    before = store.events(LEARNER, SESSION)
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TRIGGER fail_report BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError): pipeline.report_problem(LEARNER, SESSION, "voice-one")
    assert store.events(LEARNER, SESSION) == before
    with sqlite3.connect(store.path) as db: db.execute("DROP TRIGGER fail_report")
    assert pipeline.report_problem(LEARNER, SESSION, "voice-one")
    assert pipeline.report_problem(LEARNER, SESSION, "voice-one")
    assert len(store.events(LEARNER, SESSION)) == len(before) + 1


def test_reporting_older_recognition_does_not_cancel_an_unrelated_pending_turn(tmp_path):
    from voice_teacher.storage.work import WorkBusy
    store, c, _, _, _, pipeline = voice(tmp_path)
    submit(pipeline)
    c.judge = Judge(RuntimeError("pending judge"))
    with pytest.raises(RuntimeError): submit(pipeline, request="voice-two", revision=1)
    before = store.events(LEARNER, SESSION)
    with pytest.raises(WorkBusy): pipeline.report_problem(LEARNER, SESSION, "voice-one")
    assert store.events(LEARNER, SESSION) == before
    with store._connection() as db:
        assert db.execute("SELECT stage FROM requests WHERE request_id='voice-two'").fetchone()[0] == "accepted"


@pytest.mark.parametrize("failure", [False, True])
def test_v5_speech_migration_preserves_state_and_rolls_back(tmp_path, monkeypatch, failure):
    import voice_teacher.storage.sqlite as implementation
    directory = tmp_path / "data"; directory.mkdir(); path = directory / "voice-teacher.sqlite"
    with sqlite3.connect(path) as db:
        for sql in (*V1, *V2, *V3, *V4, *V5): db.execute(sql)
        db.execute(f"PRAGMA application_id={APPLICATION_ID}"); db.execute("PRAGMA user_version=5")
        db.execute("INSERT INTO learners VALUES ('preserve','{}')")
    if failure:
        monkeypatch.setattr(implementation, "V6", (*implementation.V6, "SELECT bad_speech_migration()"))
        with pytest.raises(sqlite3.OperationalError): Store(directory)
        with sqlite3.connect(path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 5
            assert db.execute("SELECT name FROM sqlite_master WHERE name='speech_requests'").fetchall() == []
    else:
        store = Store(directory); assert store.learner("preserve") == {}
        with store._connection() as db: assert db.execute("PRAGMA user_version").fetchone()[0] == VERSION
