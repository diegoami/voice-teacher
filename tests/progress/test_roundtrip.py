from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from schemas.validate import canonical_json, content_hash
from voice_teacher.practice import Lesson
from voice_teacher.practice.coordinator import Coordinator
from voice_teacher.progress import Archive, ArchiveError, readable_history
from voice_teacher.providers import Judgement, Verdict
from voice_teacher.storage import Store

LEARNER = "synthetic-learner"


class Judge:
    def __init__(self, *answers): self.answers = list(answers)
    def __call__(self, item, heard):
        answer = self.answers.pop(0) if self.answers else "accept"
        return Judgement(Verdict(answer, True, "вітаю" if answer == "error" else "", "", 0, ""), 0, {})


def session(store, name="alpha", judge=None):
    template = json.loads((Path(__file__).resolve().parents[1] / "contracts/fixtures/session.json").read_text())
    template["session_id"] = name
    template["source"]["source_id"] = name
    template["curriculum_snapshot"]["source_id"] = name
    template["source"]["revision"]["content_sha256"] = content_hash(template["curriculum_snapshot"])
    lesson = Lesson.from_dict(dict(source_id=name, course_id="basics", lesson_id="lesson-1", title="Synthetic",
        introduction="", opening=["Приві́т"], opening_item_ids=["hello"],
        steps=[dict(number=1, step_id="greet", teacher_line="Say hello", expected="greet", targets=["Приві́т"], target_item_ids=["hello"])],
        recall=[dict(number=1, goal_id="recall-hello", prompt="Greet again", targets=["Приві́т"], target_item_ids=["hello"])]))
    store.save_learner(LEARNER, template["learner_profile"])
    c = Coordinator(store, judge or Judge(), clock=lambda: 0)
    c.create(template, lesson, part="2")
    return c


def turn(c, name="alpha", text="Привіт"):
    rev = c.store.session(LEARNER, name)["revision"]
    return c.submit(LEARNER, name, f"r{rev}", expected_revision=rev, text=text)


def archive(tmp_path, **options):
    root = tmp_path / "progress"; root.mkdir(parents=True, exist_ok=True)
    return Archive(root, **options)


def write_payload(a, value):
    data = canonical_json(value).encode()
    path = a.root / a.NAMESPACE / (hashlib.sha256(data).hexdigest() + ".json")
    path.write_bytes(data)
    return path


def first_payload(a):
    return json.loads(next((a.root / a.NAMESPACE).glob("*.json")).read_bytes())


def test_complete_and_interrupted_sessions_roundtrip_and_continue(tmp_path):
    source = Store(tmp_path / "source-data")
    complete = session(source, "complete")
    turn(complete, "complete"); turn(complete, "complete")
    assert source.session(LEARNER, "complete")["status"] == "finished"
    interrupted = session(source, "interrupted", Judge("error"))
    turn(interrupted, "interrupted", "Incorrect synthetic attempt")
    interrupted.control(LEARNER, "interrupted", "pause", expected_revision=1, operation="pause")
    a = archive(tmp_path)
    assert len(a.export(source)) == 2
    assert source.pending_exports() == []
    target = Store(tmp_path / "restored")
    assert a.restore(target) == len(a.read())
    for name in ["complete", "interrupted"]:
        assert target.events(LEARNER, name) == source.events(LEARNER, name)
        assert target.session(LEARNER, name) == source.session(LEARNER, name)
        assert target.projection(LEARNER, name) == source.projection(LEARNER, name)
        assert target.rebuild(LEARNER, name) == source.session(LEARNER, name)
    assert target.pending_exports() == []
    assert a.restore(target) == 0
    assert a.export(source) == []
    resumed = Coordinator(Store(target.path.parent), Judge(), clock=lambda: 0)
    resumed.control(LEARNER, "interrupted", "resume", expected_revision=2, operation="resume")
    turn(resumed, "interrupted")
    evidence = target.projection(LEARNER, "interrupted")["evidence"]
    assert evidence[0]["assistance"]["kind"] == "correction"
    assert evidence[0]["evidence"]["outcome"] != "independent"
    assert "assistance=correction" in readable_history(target.events(LEARNER, "interrupted"))


def test_overlapping_prefixes_and_old_archive_do_not_erase_newer_history(tmp_path):
    source = Store(tmp_path / "source-data"); c = session(source)
    a = archive(tmp_path); a.export(source)
    old = first_payload(a)
    turn(c); a.export(source)
    assert len(list((a.root / a.NAMESPACE).glob("*.json"))) == 2
    assert len(a.read()) == len(source.events(LEARNER, "alpha"))
    target = Store(tmp_path / "restore"); a.restore(target)
    before = target.events(LEARNER, "alpha")
    older = archive(tmp_path / "older-parent")
    older._publish(old)
    assert older.restore(target) == 0
    assert target.events(LEARNER, "alpha") == before


def test_cross_source_provenance_and_supersession_survive_replay(tmp_path):
    source = Store(tmp_path / "source-data")
    alpha = session(source); turn(alpha)
    beta = session(source, "beta"); turn(beta, "beta")
    original = source.projection(LEARNER, "alpha")["evidence"][0]
    previous = source.projection(LEARNER, "beta")["evidence"][0]
    saved = source.session(LEARNER, "beta")
    observed = deepcopy(previous)
    observed.update(event_id="cross-observation", sequence=saved["event_sequence"] + 1)
    observed["provenance"].update(original_source=original["source"], original_item=original["provenance"]["original_item"],
        origin_session_id="alpha", origin_turn_id=original["turn"]["turn_id"])
    superseded = deepcopy(observed)
    superseded.update(event_id="cross-superseded", sequence=observed["sequence"] + 1,
        event_type="observation.superseded", evidence=None, assistance=None, supersedes_event_id=observed["event_id"])
    state = deepcopy(source.events(LEARNER, "beta")[-1])
    state.update(event_id="cross-state", sequence=superseded["sequence"] + 1)
    saved.update(revision=saved["revision"] + 1, event_sequence=state["sequence"])
    state["snapshot"] = saved
    source.commit(LEARNER, "beta", [observed, superseded, state], expected_revision=1)
    a = archive(tmp_path); a.export(source)
    target = Store(tmp_path / "restore"); a.restore(target)
    assert target.events(LEARNER, "beta") == source.events(LEARNER, "beta")
    assert target.projection(LEARNER, "beta") == source.projection(LEARNER, "beta")
    assert "cross-observation" in readable_history(a.read())
    # A historical source cannot be resolved from another learner's turn.
    broken = first_payload(a)
    if broken["session_id"] != "beta":
        broken = next(json.loads(p.read_bytes()) for p in (a.root / a.NAMESPACE).glob("*.json") if json.loads(p.read_bytes())["session_id"] == "beta")
    next(e for e in broken["events"] if e["event_id"] == "cross-observation")["provenance"]["origin_turn_id"] = "missing-turn"
    separate = tmp_path / "bad"; separate.mkdir(); bad = Archive(separate); bad._publish(broken)
    with pytest.raises(ArchiveError, match="provenance|source snapshot"): bad.restore(Store(tmp_path / "bad-restore"))


@pytest.mark.parametrize("corruption", ["truncate", "conflict", "trailing", "foreign"])
def test_bad_batches_are_rejected_before_any_restore_writes(tmp_path, corruption):
    source = Store(tmp_path / "source-data"); session(source)
    a = archive(tmp_path); a.export(source)
    path = next((a.root / a.NAMESPACE).glob("*.json"))
    if corruption == "truncate": path.write_bytes(path.read_bytes()[:-10])
    elif corruption == "foreign": (path.parent / "audio.wav").write_bytes(b"not an event")
    else:
        value = first_payload(a)
        if corruption == "conflict": value["events"][0]["occurred_at"] = "2026-10-16T00:00:00Z"
        else: value["events"].pop()
        write_payload(a, value)
    target = Store(tmp_path / "restore")
    with pytest.raises(ValueError): a.restore(target)
    with target._connection() as c:
        assert c.execute("SELECT COUNT(*) FROM learners").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_activity_failure_rolls_back_whole_import(tmp_path):
    source = Store(tmp_path / "source-data"); session(source)
    a = archive(tmp_path); a.export(source)
    value = first_payload(a)
    value["activities"].append({"activity_id": "collision", "position": 0, "data": {}})
    write_payload(a, value)
    target = Store(tmp_path / "restore")
    with pytest.raises(sqlite3.IntegrityError): a.restore(target)
    with target._connection() as c:
        assert c.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM learners").fetchone()[0] == 0


def test_export_crash_after_publication_is_replayable_without_overwrite(tmp_path, monkeypatch):
    import voice_teacher.progress.archive as implementation
    source = Store(tmp_path / "source-data"); session(source)
    a = archive(tmp_path)
    (a.root / a.NAMESPACE).mkdir(parents=True)
    original = implementation._sync
    monkeypatch.setattr(implementation, "_sync", lambda path: (_ for _ in ()).throw(OSError("injected fsync failure")))
    with pytest.raises(OSError): a.export(source)
    assert source.pending_exports()
    files = list((a.root / a.NAMESPACE).glob("*.json"))
    assert len(files) == 1
    before = files[0].read_bytes()
    monkeypatch.setattr(implementation, "_sync", original)
    assert len(a.export(Store(source.path.parent))) == 1
    assert files[0].read_bytes() == before
    assert len(list(files[0].parent.glob("*.json"))) == 1
    assert source.pending_exports() == []


def test_namespace_exclusions_symlinks_and_abandoned_temporary_file(tmp_path):
    source = Store(tmp_path / "source-data"); session(source)
    content = tmp_path / "content"; content.mkdir()
    (content / "lesson.md").write_text("Do not change")
    with pytest.raises(ArchiveError): Archive(content, forbidden_roots=[content])
    with pytest.raises(ArchiveError): Archive(Path(__file__).resolve().parents[2])
    with pytest.raises(ArchiveError): Archive(source.path.parent).export(source)
    a = archive(tmp_path, forbidden_roots=[content, source.path.parent])
    sentinel = a.root / "card-reviews.jsonl"; sentinel.write_text("unrelated sentinel")
    source.path.with_name("provider.key").write_text("SYNTHETIC_SECRET")
    source.path.with_name("audio.wav").write_bytes(b"SYNTHETIC_RAW_AUDIO")
    a.export(source)
    directory = a.root / a.NAMESPACE
    (directory / ".pending-abandoned").write_text("incomplete")
    assert len(a.read()) == len(source.events(LEARNER, "alpha"))
    assert sentinel.read_text() == "unrelated sentinel"
    assert (content / "lesson.md").read_text() == "Do not change"
    exported = b"".join(p.read_bytes() for p in directory.glob("*.json"))
    assert b"SYNTHETIC_SECRET" not in exported and b"SYNTHETIC_RAW_AUDIO" not in exported
    assert not list(a.root.rglob("*.sqlite"))
    outside = tmp_path / "outside"; outside.mkdir()
    (directory / "link.json").symlink_to(outside / "unused")
    with pytest.raises(ArchiveError, match="symlinks"): a.read()


def test_symlink_namespace_and_bounded_archive_are_refused(tmp_path):
    source = Store(tmp_path / "source-data"); session(source)
    a = archive(tmp_path)
    outside = tmp_path / "outside"; outside.mkdir()
    (a.root / "voice-teacher").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArchiveError): a.export(source)
    with pytest.raises(ArchiveError): a.read()
    (a.root / "voice-teacher").unlink()
    a.export(source)
    with pytest.raises(ArchiveError, match="byte limit"): Archive(a.root, max_batch_bytes=20).read()
    with pytest.raises(ArchiveError, match="byte limit"): Archive(a.root, max_archive_bytes=20).read()


def test_unfinished_live_work_prevents_restore_advancing_session(tmp_path):
    from voice_teacher.storage.work import WorkStore
    source = Store(tmp_path / "source-data"); c = session(source)
    a = archive(tmp_path); a.export(source)
    target = Store(tmp_path / "restore"); a.restore(target)
    WorkStore(target).accept(LEARNER, "alpha", "unfinished", 0, {"text": "hi"}, statuses={"active"})
    turn(c); a.export(source)
    before = target.events(LEARNER, "alpha")
    with pytest.raises(ArchiveError, match="unfinished provider"): a.restore(target)
    assert target.events(LEARNER, "alpha") == before


def test_registered_content_checkout_is_not_a_progress_destination(tmp_path):
    from voice_teacher.content.registry import SourceRegistry, SourceSpec
    source = Store(tmp_path / "source-data"); session(source)
    content = tmp_path / "content"; content.mkdir()
    SourceRegistry(source).register(SourceSpec("content", "Content", str(content)))
    with pytest.raises(ArchiveError, match="registered content"):
        Archive(content).export(source)
    assert list(content.iterdir()) == []
    assert source.pending_exports()


def test_unresolved_committed_provenance_is_not_acknowledged_as_exported(tmp_path):
    source = Store(tmp_path / "source-data"); session(source)
    snapshot = source.session(LEARNER, "alpha")
    state = deepcopy(source.events(LEARNER, "alpha")[-1])
    state.update(event_id="unresolved-state", sequence=state["sequence"] + 1)
    snapshot.update(revision=1, event_sequence=state["sequence"])
    state["snapshot"] = snapshot
    state["provenance"]["origin_turn_id"] = "missing"
    source.commit(LEARNER, "alpha", [state], expected_revision=0)
    a = archive(tmp_path)
    with pytest.raises(ArchiveError, match="provenance"): a.export(source)
    assert source.pending_exports()
    assert not (a.root / a.NAMESPACE).exists()
