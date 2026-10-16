from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading

import pytest

from voice_teacher.practice import Lesson
from voice_teacher.practice.coordinator import Coordinator
from voice_teacher.providers import Judgement, Verdict
from voice_teacher.storage import Store, RevisionConflict
from voice_teacher.storage.work import RequestConflict, WorkBusy
from voice_teacher.storage.migrations import APPLICATION_ID, V1, V2

LEARNER, SESSION = "synthetic-learner", "synthetic-session"


class Judge:
    def __init__(self, *answers):
        self.calls = 0
        self.answers = list(answers)
    def __call__(self, item, text):
        self.calls += 1
        answer = self.answers.pop(0) if self.answers else "accept"
        if isinstance(answer, Exception): raise answer
        return Judgement(Verdict(answer, True, "вітаю" if answer == "error" else "", "", 0, ""), .1, {"tokens": 1})


def setup(tmp_path, judge=None, delivery=None, part="2"):
    template = json.loads((Path(__file__).resolve().parents[1] / "contracts/fixtures/session.json").read_text())
    lesson = Lesson.from_dict(dict(source_id="synthetic-alpha", course_id="basics", lesson_id="lesson-1",
        title="Synthetic greeting", introduction="Introduction", opening=["Приві́т"], opening_item_ids=["hello"],
        steps=[dict(number=1, step_id="greet", teacher_line="Say hello", expected="greet", targets=["Приві́т"], target_item_ids=["hello"])],
        recall=[dict(number=1, goal_id="recall-hello", prompt="Greet again", targets=["Приві́т"], target_item_ids=["hello"])]))
    store = Store(tmp_path / "data", timeout=.2)
    store.save_learner(LEARNER, template["learner_profile"])
    judge = judge or Judge()
    coordinator = Coordinator(store, judge, delivery=delivery, clock=lambda: 0)
    initial = coordinator.create(template, lesson, part=part)
    assert initial["revision"] == 0 and initial["request_id"] is None
    return store, coordinator, judge


def submit(c, request="r1", revision=0, text="привіт"):
    return c.submit(LEARNER, SESSION, request, expected_revision=revision, text=text)


def event_counts(store):
    events = store.events(LEARNER, SESSION)
    return {kind: sum(e["event_type"] == kind for e in events) for kind in ["turn.accepted", "evidence.recorded", "state.saved"]}


def test_request_replay_and_response_loss_after_restart(tmp_path):
    store, c, judge = setup(tmp_path)
    result = submit(c, request="start")  # ordinary client IDs cannot collide with creation
    events = store.events(LEARNER, SESSION)
    restarted = Coordinator(Store(store.path.parent), Judge(RuntimeError("must not judge again")), clock=lambda: 0)
    assert submit(restarted, request="start") == result
    script = """import sys,json
from voice_teacher.storage import Store
from voice_teacher.practice.coordinator import Coordinator
def forbidden(*args):raise RuntimeError('must not judge after restart')
c=Coordinator(Store(sys.argv[1]),forbidden)
print(json.dumps(c.submit('synthetic-learner','synthetic-session','start',expected_revision=0,text='привіт')))
"""
    restored = subprocess.check_output([sys.executable, "-c", script, str(store.path.parent)], text=True)
    assert json.loads(restored) == result
    assert store.events(LEARNER, SESSION) == events
    assert judge.calls == 1
    assert event_counts(store) == {"turn.accepted": 1, "evidence.recorded": 1, "state.saved": 2}


def test_request_identity_revision_and_owner_are_bound(tmp_path):
    store, c, _ = setup(tmp_path)
    submit(c)
    for options in [dict(text="different"), dict(revision=1)]:
        with pytest.raises(RequestConflict): submit(c, **options)
    with pytest.raises(RevisionConflict): submit(c, request="new", revision=0)
    with pytest.raises(RevisionConflict):
        c.submit("other", SESSION, "r1", expected_revision=0, text="привіт")
    assert event_counts(store)["turn.accepted"] == 1


@pytest.mark.parametrize("same_id", [True, False])
def test_concurrent_submissions_record_one_attempt(tmp_path, same_id):
    store, c, judge = setup(tmp_path)
    other = Coordinator(store, judge, clock=lambda: 0)
    barrier = threading.Barrier(2)
    def attempt(pair):
        coordinator, request = pair
        barrier.wait()
        try: return submit(coordinator, request=request)
        except RevisionConflict: return "stale"
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(attempt, [(c, "r1"), (other, "r1" if same_id else "r2")]))
    if same_id: assert results[0] == results[1]
    else: assert results.count("stale") == 1
    assert judge.calls == 1
    assert store.session(LEARNER, SESSION)["revision"] == 1
    assert event_counts(store)["evidence.recorded"] == 1


@pytest.mark.parametrize("failure", ["before-judge", "after-provider", "after-saved-judge", "before-commit", "after-commit", "after-delivery"])
def test_failure_stages_resume_without_a_second_transition(tmp_path, monkeypatch, failure):
    store, c, judge = setup(tmp_path)
    if failure == "before-judge": judge.answers = [RuntimeError("injected"), "accept"]
    if failure in {"after-provider", "after-saved-judge"}:
        original = c.work.judgment
        def broken(*args):
            if failure == "after-saved-judge": original(*args)
            raise RuntimeError("injected")
        monkeypatch.setattr(c.work, "judgment", broken)
    if failure == "before-commit":
        with sqlite3.connect(store.path) as db:
            db.execute("CREATE TRIGGER injected BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'injected'); END")
    if failure == "after-commit":
        monkeypatch.setattr(c, "_deliver", lambda *args: (_ for _ in ()).throw(RuntimeError("injected")))
    if failure == "after-delivery":
        original = c.work.delivered
        def broken(*args):
            original(*args)
            raise RuntimeError("injected")
        monkeypatch.setattr(c.work, "delivered", broken)
    with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="injected"):
        submit(c)
    record = c.work.get(LEARNER, SESSION, "r1")
    expected = {"before-judge": "accepted", "after-provider": "accepted", "after-saved-judge": "judged",
                "before-commit": "judged", "after-commit": "committed", "after-delivery": "delivered"}
    assert record["stage"] == expected[failure]
    if failure == "before-commit":
        assert store.session(LEARNER, SESSION)["revision"] == 0
        assert event_counts(store)["turn.accepted"] == 0
        with sqlite3.connect(store.path) as db: db.execute("DROP TRIGGER injected")
    restarted = Coordinator(Store(store.path.parent), judge, clock=lambda: 0)
    result = submit(restarted)
    assert result["revision"] == 1
    assert submit(restarted) == result
    assert judge.calls == (2 if failure in {"before-judge", "after-provider"} else 1)
    assert event_counts(store) == {"turn.accepted": 1, "evidence.recorded": 1, "state.saved": 2}


def test_request_completion_and_progress_commit_are_atomic(tmp_path):
    store, c, judge = setup(tmp_path)
    before = store.events(LEARNER, SESSION)
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TRIGGER injected BEFORE UPDATE ON requests WHEN NEW.stage='committed' BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError): submit(c)
    assert store.events(LEARNER, SESSION) == before
    assert store.session(LEARNER, SESSION)["revision"] == 0
    assert c.work.get(LEARNER, SESSION, "r1")["stage"] == "judged"
    with sqlite3.connect(store.path) as db: db.execute("DROP TRIGGER injected")
    submit(Coordinator(store, judge, clock=lambda: 0))
    assert judge.calls == 1 and event_counts(store)["evidence.recorded"] == 1


def test_synthesis_and_playback_retry_use_saved_teacher_plan(tmp_path):
    deliveries = []
    def speech(says):
        deliveries.append(deepcopy(says))
        if len(deliveries) == 1: raise RuntimeError("synthesis failed")
        return {"audio_ref": "synthetic-audio"}
    store, c, judge = setup(tmp_path, delivery=speech)
    with pytest.raises(RuntimeError, match="synthesis failed"): submit(c)
    assert c.work.get(LEARNER, SESSION, "r1")["stage"] == "committed"
    result = submit(Coordinator(store, judge, delivery=speech, clock=lambda: 0))
    assert deliveries[0] == deliveries[1] == result["teacher"]
    # A failed client playback/HTTP response just retries this same durable request.
    assert submit(c) == result
    assert len(deliveries) == 2 and judge.calls == 1
    assert event_counts(store)["turn.accepted"] == 1


def test_provider_and_delivery_calls_do_not_hold_a_database_transaction(tmp_path):
    store, c, _ = setup(tmp_path)
    def judge(item, text):
        store.save_learner("provider-probe", {})
        return Judge()(item, text)
    def speech(says):
        store.save_learner("delivery-probe", {})
        return {}
    c.judge, c.delivery = judge, speech
    submit(c)
    assert store.learner("provider-probe") == store.learner("delivery-probe") == {}


def test_pending_request_blocks_a_different_turn_but_pause_can_cancel_it(tmp_path):
    store, c, _ = setup(tmp_path)
    c.work.accept(LEARNER, SESSION, "unfinished", 0, {"text": "discarded input"}, statuses={"active"})
    with pytest.raises(WorkBusy): submit(c, request="other")
    pause = c.control(LEARNER, SESSION, "pause-1", expected_revision=0, operation="pause")
    assert pause["status"] == "paused"
    with pytest.raises(RequestConflict): submit(c, request="unfinished", text="discarded input")
    with pytest.raises(RequestConflict): submit(c, request="paused-turn", revision=1)
    assert c.control(LEARNER, SESSION, "pause-1", expected_revision=0, operation="pause") == pause
    resumed = c.control(LEARNER, SESSION, "resume-1", expected_revision=1, operation="resume")
    assert resumed["status"] == "active"
    submit(c, request="new-turn", revision=2)
    assert event_counts(store)["turn.accepted"] == 1
    assert not any(e["turn"] and e["turn"]["text"] == "discarded input" for e in store.events(LEARNER, SESSION))


def test_stop_control_has_no_fabricated_learner_turn(tmp_path):
    store, c, judge = setup(tmp_path)
    result = c.control(LEARNER, SESSION, "stop-1", expected_revision=0, operation="stop")
    assert result["done"] and result["status"] == "finished"
    assert result["teacher"][0]["kind"] == "close"
    assert c.control(LEARNER, SESSION, "stop-1", expected_revision=0, operation="stop") == result
    assert judge.calls == 0 and event_counts(store)["turn.accepted"] == 0
    assert c._engine(store.session(LEARNER, SESSION), judge).done
    with pytest.raises(RequestConflict): submit(c, request="after-stop", revision=1)


@pytest.mark.parametrize("operation", ["stop", "pause"])
def test_control_racing_with_a_turn_leaves_valid_state(tmp_path, operation):
    entered, release = threading.Event(), threading.Event()
    def delayed(item, text):
        entered.set()
        assert release.wait(3)
        return Judge()(item, text)
    store, c, _ = setup(tmp_path, judge=delayed)
    with ThreadPoolExecutor(2) as pool:
        turn = pool.submit(submit, c)
        assert entered.wait(3)
        control = pool.submit(c.control, LEARNER, SESSION, "control", expected_revision=0, operation=operation)
        release.set()
        assert turn.result()["revision"] == 1
        with pytest.raises(RevisionConflict): control.result()
    final = c.control(LEARNER, SESSION, "retry-control", expected_revision=1, operation=operation)
    assert final["status"] == ("finished" if operation == "stop" else "paused")
    assert event_counts(store)["evidence.recorded"] == 1
    c._engine(store.session(LEARNER, SESSION), Judge())  # capsule remains restorable


def test_correction_assistance_is_preserved_and_not_upgraded_to_independent(tmp_path):
    store, c, _ = setup(tmp_path, judge=Judge("error", "accept"))
    first = submit(c)
    assert first["teacher"][0]["kind"] == "correction"
    submit(c, request="r2", revision=1)
    evidence = store.projection(LEARNER, SESSION)["evidence"]
    assert evidence[0]["evidence"]["outcome"] == "corrected_repeated"
    assert evidence[0]["assistance"]["kind"] == "correction"
    assert evidence[0]["assistance"]["target_exposed"]


def test_two_writer_processes_cannot_commit_the_same_attempt_twice(tmp_path):
    store, c, _ = setup(tmp_path)
    script = """import pathlib,sys,time,json
from voice_teacher.storage import Store
from voice_teacher.practice.coordinator import Coordinator
from voice_teacher.providers import Verdict,Judgement
root=pathlib.Path(sys.argv[1]); marker=root/('ready-'+sys.argv[2])
def judge(item,text):
 marker.touch();deadline=time.monotonic()+5
 while len(list(root.glob('ready-*')))<2:
  if time.monotonic()>deadline:raise RuntimeError('barrier deadline')
  time.sleep(.01)
 return Judgement(Verdict('accept',True,'','',0,''),.1,{})
c=Coordinator(Store(root/'data'),judge,clock=lambda:0)
print(json.dumps(c.submit('synthetic-learner','synthetic-session','r1',expected_revision=0,text='привіт')))
"""
    children = [subprocess.Popen([sys.executable, "-c", script, str(tmp_path), str(i)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(2)]
    try:
        results = []
        for child in children:
            out, err = child.communicate(timeout=10)
            assert child.returncode == 0, err
            results.append(json.loads(out))
        assert results[0] == results[1]
    finally:
        for child in children:
            if child.poll() is None: child.kill(); child.wait()
    assert event_counts(store)["turn.accepted"] == event_counts(store)["evidence.recorded"] == 1
    assert store.session(LEARNER, SESSION)["revision"] == 1


def legacy_v2_copy(store):
    """Build the actual frozen v2 schema, independent of newer feature tables."""
    directory = store.path.parent.parent / "legacy-v2"
    directory.mkdir(mode=0o700)
    with sqlite3.connect(store.path) as source, sqlite3.connect(directory / "voice-teacher.sqlite") as target:
        for sql in (*V1, *V2): target.execute(sql)
        target.execute(f"PRAGMA application_id={APPLICATION_ID}")
        target.execute("PRAGMA user_version=2")
        for table in ("learners", "sessions", "events", "activities", "turns", "observations", "evidence", "outbox"):
            rows = source.execute(f"SELECT * FROM {table}").fetchall()
            if rows:
                placeholders = ",".join("?" for _ in rows[0])
                target.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
    return directory


def test_v2_migration_adds_work_stages_without_changing_history(tmp_path):
    store, c, _ = setup(tmp_path)
    before = store.events(LEARNER, SESSION)
    restarted = Store(legacy_v2_copy(store))
    assert restarted.events(LEARNER, SESSION) == before
    submit(Coordinator(restarted, Judge(), clock=lambda: 0))
    assert event_counts(restarted)["evidence.recorded"] == 1


def test_failed_v3_migration_leaves_v2_database_unchanged(tmp_path, monkeypatch):
    import voice_teacher.storage.sqlite as implementation
    store, _, _ = setup(tmp_path)
    before = store.events(LEARNER, SESSION)
    directory = legacy_v2_copy(store)
    monkeypatch.setattr(implementation, "V3", (*implementation.V3, "SELECT invalid_migration_function()"))
    with pytest.raises(sqlite3.OperationalError): Store(directory)
    with sqlite3.connect(directory / "voice-teacher.sqlite") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("SELECT name FROM sqlite_master WHERE name='requests'").fetchall() == []
        assert [json.loads(r[0]) for r in db.execute("SELECT body_json FROM events ORDER BY sequence")] == before


def test_control_snapshots_preserve_resolvable_origin_turns(tmp_path):
    store, c, _ = setup(tmp_path)
    submit(c)
    c.control(LEARNER, SESSION, "pause", expected_revision=1, operation="pause")
    c.control(LEARNER, SESSION, "resume", expected_revision=2, operation="resume")
    c.control(LEARNER, SESSION, "stop", expected_revision=3, operation="stop")
    events = store.events(LEARNER, SESSION)
    turns = {e["turn"]["turn_id"] for e in events if e["turn"] is not None}
    assert all(e["provenance"]["origin_turn_id"] in turns for e in events)


def test_prepared_targets_cannot_disagree_with_the_pinned_curriculum(tmp_path):
    store, c, judge = setup(tmp_path)
    template = store.session(LEARNER, SESSION)
    template["session_id"] = "mismatched-session"
    lesson = c._engine(template, judge).lesson
    lesson.opening[0] = lesson.steps[0].targets[0] = lesson.recall[0].targets[0] = "Different rendering"
    with pytest.raises(ValueError, match="target rendering"):
        c.create(template, lesson)
    assert store.events(LEARNER, "mismatched-session") == []


def test_repetition_commits_without_judging_and_preserves_modelled_exposure(tmp_path):
    store, c, judge = setup(tmp_path, part="all")
    submit(c)
    submit(c, request="r2", revision=1)
    assert judge.calls == 0
    evidence = store.projection(LEARNER, SESSION)["evidence"]
    assert [e["evidence"]["outcome"] for e in evidence] == ["repeated", "repeated"]
    assert all(e["assistance"]["target_exposed"] and e["assistance"]["kind"] == "model" for e in evidence)
    engine = c._engine(store.session(LEARNER, SESSION), judge)
    assert (engine.phase, engine.round) == ("guided", 1)
