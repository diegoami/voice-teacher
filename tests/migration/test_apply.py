"""Only original synthetic history is imported by automated checks."""
import copy
import hashlib
import json

import pytest

from test_preview import mapped
from voice_teacher.progress.legacy import LegacyLedger, LegacyArchive, LegacyError, build_batch
from voice_teacher.progress.preview import _json, plan_preview


def fixture(tmp_path):
    root, manifest = mapped(tmp_path)
    report = plan_preview(root, manifest)
    approval = dict(format_version=1, reviewed=True, approved_by="synthetic-owner",
                    preview_sha256=hashlib.sha256(_json(report).encode()).hexdigest(),
                    selected_observation_ids=[o["proposed_id"] for o in report["observations"]],
                    course_positions=[], destination_remote="https://example.invalid/private-progress.git")
    return root, manifest, approval


def test_apply_preserves_selected_observations_and_retry_is_idempotent(tmp_path):
    root, manifest, approval = fixture(tmp_path)
    ledger = LegacyLedger(tmp_path / "runtime", destination_remote=approval["destination_remote"],
                          private_verified=True, owner_verified=True)
    assert ledger.apply(root, manifest, approval)["observations"] == 3
    assert ledger.apply(root, manifest, approval) == dict(imports=0, observations=0)
    history = ledger.history(manifest["learner_id"])
    assert len(history) == 3
    assert next(o for o in history if o["observation_key"] == "later")["practice_source"]["source_id"] == "course-b"
    assert next(o for o in history if o["observation_key"] == "correction")["correction"]["attempt"] == "Sample mistake"


def ledger(tmp_path, approval):
    return LegacyLedger(tmp_path / "runtime", destination_remote=approval["destination_remote"],
                        private_verified=True, owner_verified=True)


def test_mid_import_failure_rolls_back_receipt_observations_and_positions(tmp_path, monkeypatch):
    root, manifest, approval = fixture(tmp_path)
    db = ledger(tmp_path, approval)
    original = db._insert_observation
    calls = []
    def fail_second(c, learner, observation):
        calls.append(observation)
        if len(calls) == 2:
            raise RuntimeError("synthetic crash")
        return original(c, learner, observation)
    monkeypatch.setattr(db, "_insert_observation", fail_second)
    with pytest.raises(RuntimeError):
        db.apply(root, manifest, approval)
    assert db.history(manifest["learner_id"]) == []
    assert db.positions(manifest["learner_id"]) == []
    assert db.batches() == []
    monkeypatch.setattr(db, "_insert_observation", original)
    assert db.apply(root, manifest, approval)["observations"] == 3


@pytest.mark.parametrize("change", ["unreviewed", "hash", "unknown", "wrong_destination", "missing_original"])
def test_rejects_unreviewed_changed_or_broken_selection_without_activating_history(tmp_path, change):
    root, manifest, approval = fixture(tmp_path)
    db = ledger(tmp_path, approval)
    if change == "unreviewed":
        approval["reviewed"] = False
    elif change == "hash":
        approval["preview_sha256"] = "0" * 64
    elif change == "unknown":
        approval["selected_observation_ids"].append("missing")
    elif change == "wrong_destination":
        approval["destination_remote"] = "https://example.invalid/other.git"
    else:
        report = plan_preview(root, manifest)
        original = next(o for o in report["observations"] if o["observation_key"] == "opening")
        approval["selected_observation_ids"].remove(original["proposed_id"])
    with pytest.raises((ValueError, LegacyError)):
        db.apply(root, manifest, approval)
    assert db.batches() == [] and db.history(manifest["learner_id"]) == []


def test_preserves_explicit_covered_and_next_position_with_evidence_and_owner_separation(tmp_path):
    root, manifest, approval = fixture(tmp_path)
    report = plan_preview(root, manifest)
    mapped_record = next(r["record_id"] for r in report["records"] if r["status"] == "proposed")
    approval["course_positions"] = [dict(source_id="course-a", course_id="a", covered_lesson_ids=["unit-0", "unit-1"],
        next_lesson_id="unit-2", evidence_record_ids=[mapped_record])]
    db = ledger(tmp_path, approval)
    db.apply(root, manifest, approval)
    assert db.positions(manifest["learner_id"])[0]["next_lesson_id"] == "unit-2"
    assert db.positions("other-learner") == [] and db.history("other-learner") == []
    assert all(o["assistance"] != "mastery" for o in db.history(manifest["learner_id"]))


def test_export_restore_preserves_approved_manifest_raw_unresolved_and_unrelated_history(tmp_path):
    root, manifest, approval = fixture(tmp_path)
    source_before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    db = ledger(tmp_path, approval)
    db.apply(root, manifest, approval)
    destination = tmp_path / "private-progress"
    destination.mkdir(mode=0o700)
    unrelated = destination / "old-review.json"
    unrelated.write_bytes(b"UNRELATED HISTORY")
    archive = LegacyArchive(destination, forbidden_roots=[root])
    first = archive.export(db)
    assert first == archive.export(db)
    batches = archive.read()
    assert batches[0]["approval"] == approval
    assert batches[0]["report"]["counts"]["unresolved"] == 1
    assert "Sample ambiguous" in json.dumps(batches)
    restored = LegacyLedger(tmp_path / "restored", destination_remote=approval["destination_remote"], private_verified=True, owner_verified=True)
    assert archive.restore(restored)["observations"] == 3
    assert archive.restore(restored) == dict(imports=0, observations=0)
    assert restored.history(manifest["learner_id"]) == db.history(manifest["learner_id"])
    assert restored.batches() == db.batches()
    assert unrelated.read_bytes() == b"UNRELATED HISTORY"
    assert source_before == {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert next((destination / archive.NAMESPACE).glob("*.json")).stat().st_mode & 0o777 == 0o600


def test_forged_or_corrupt_archived_evidence_cannot_activate_any_import(tmp_path):
    root, manifest, approval = fixture(tmp_path)
    batch = build_batch(root, manifest, approval)
    forged = copy.deepcopy(batch)
    forged["report"]["observations"][0]["assistance"] = "independent"
    forged["approval"]["preview_sha256"] = hashlib.sha256(_json(forged["report"]).encode()).hexdigest()
    db = ledger(tmp_path, approval)
    with pytest.raises(LegacyError):
        db.restore([batch, forged])
    assert db.batches() == [] and db.history(manifest["learner_id"]) == []


def test_conflicting_reimport_keeps_prior_history_and_requires_review(tmp_path):
    root, manifest, approval = fixture(tmp_path)
    db = ledger(tmp_path, approval)
    db.apply(root, manifest, approval)
    before = db.history(manifest["learner_id"])
    for m in manifest["mappings"]:
        if m["observation_key"] == "opening":
            m["assistance"] = None
    approval["preview_sha256"] = hashlib.sha256(_json(plan_preview(root, manifest)).encode()).hexdigest()
    with pytest.raises(LegacyError):
        db.apply(root, manifest, approval)
    assert db.history(manifest["learner_id"]) == before
    assert len(db.batches()) == 1


def test_private_owner_and_foreign_database_gates(tmp_path):
    import sqlite3
    with pytest.raises(LegacyError):
        LegacyLedger(tmp_path / "refused", destination_remote="https://example.invalid/private.git")
    assert not (tmp_path / "refused").exists()
    directory = tmp_path / "foreign"
    directory.mkdir(mode=0o700)
    database = directory / "legacy-import.sqlite"
    with sqlite3.connect(database) as c:
        c.execute("CREATE TABLE unrelated (value TEXT)")
    before = database.read_bytes()
    with pytest.raises(LegacyError):
        LegacyLedger(directory, destination_remote="https://example.invalid/private.git", private_verified=True, owner_verified=True)
    assert database.read_bytes() == before


def test_single_writer_sync_pushes_legacy_only_archive_and_restores_retry_safely(tmp_path):
    import subprocess
    from voice_teacher.storage import Store
    from voice_teacher.progress.git_sync import GitSync
    root, manifest, approval = fixture(tmp_path)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(remote)], check=True)
    approval["destination_remote"] = str(remote)
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    store = Store(runtime)
    db = ledger(tmp_path, approval)
    db.apply(root, manifest, approval)
    sync = GitSync(store, tmp_path / "checkout", str(remote), private_verified=True, owner_verified=True, legacy=db)
    state = sync.run_once()
    assert state["events"] == []
    assert len(state["legacy_imports"]) == 1 and state["legacy_imports"][0]["state"] == "pushed"
    state = sync.run_once()
    assert len(db.history(manifest["learner_id"])) == 3
    runtime2 = tmp_path / "runtime2"
    runtime2.mkdir(mode=0o700)
    store2 = Store(runtime2)
    db2 = LegacyLedger(runtime2, destination_remote=str(remote), private_verified=True, owner_verified=True)
    sync2 = GitSync(store2, tmp_path / "checkout2", str(remote), private_verified=True, owner_verified=True, legacy=db2)
    assert sync2.run_once()["legacy_imports"][0]["state"] == "pushed"
    assert db2.history(manifest["learner_id"]) == db.history(manifest["learner_id"])


def test_real_apply_cli_exports_only_after_exact_review_and_preserves_sources(tmp_path, capsys):
    from voice_teacher.progress.legacy import main
    root, manifest, approval = fixture(tmp_path)
    private = tmp_path / "operator"
    private.mkdir(mode=0o700)
    manifest_file, approval_file = private / "manifest.json", private / "approval.json"
    manifest_file.write_text(json.dumps(manifest))
    approval_file.write_text(json.dumps({**approval, "reviewed": False}))
    destination = tmp_path / "progress"
    destination.mkdir(mode=0o700)
    runtime = tmp_path / "runtime"
    args = ["--root", str(root), "--manifest", str(manifest_file), "--approval", str(approval_file),
            "--runtime", str(runtime), "--destination", str(destination), "--remote", approval["destination_remote"],
            "--private-verified", "--owner-verified"]
    with pytest.raises(SystemExit) as failure:
        main(args)
    assert failure.value.code == 2 and not runtime.exists()
    assert "Sample" not in capsys.readouterr().err
    approval_file.write_text(json.dumps(approval))
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    main(args)
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result == dict(imports=1, observations=3, locally_exported=True, remote_push="not performed")
    assert "Sample" not in output.out + output.err
    assert before == {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert len(LegacyArchive(destination).read()) == 1
    main(args)
    assert json.loads(capsys.readouterr().out)["imports"] == 0


def test_concurrent_apply_creates_one_receipt_without_duplicate_history(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    root, manifest, approval = fixture(tmp_path)
    db = ledger(tmp_path, approval)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: db.apply(root, manifest, approval), range(2)))
    assert sum(r["imports"] for r in results) == 1
    assert sum(r["observations"] for r in results) == 3
    assert len(db.batches()) == 1 and len(db.history(manifest["learner_id"])) == 3


def test_position_cannot_credit_another_course_and_corrupt_archive_cannot_restore(tmp_path):
    root, manifest, approval = fixture(tmp_path)
    report = plan_preview(root, manifest)
    record = next(r["record_id"] for r in report["records"] if r["status"] == "proposed")
    approval["course_positions"] = [dict(source_id="wrong-course", course_id="wrong", covered_lesson_ids=["unit-0"], next_lesson_id="unit-1", evidence_record_ids=[record])]
    db = ledger(tmp_path, approval)
    with pytest.raises(LegacyError):
        db.apply(root, manifest, approval)
    approval["course_positions"] = []
    db.apply(root, manifest, approval)
    destination = tmp_path / "archive"
    destination.mkdir(mode=0o700)
    archive = LegacyArchive(destination)
    archive.export(db)
    next((destination / archive.NAMESPACE).glob("*.json")).write_bytes(b"corrupt")
    restored = LegacyLedger(tmp_path / "restored", destination_remote=approval["destination_remote"], private_verified=True, owner_verified=True)
    with pytest.raises(ValueError):
        archive.restore(restored)
    assert restored.batches() == []


def test_legacy_opt_in_does_not_change_existing_sync_binding_silently(tmp_path):
    import subprocess
    from voice_teacher.storage import Store
    from voice_teacher.progress.git_sync import GitSync, SyncError
    root, manifest, approval = fixture(tmp_path)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(remote)], check=True)
    approval["destination_remote"] = str(remote)
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    store = Store(runtime)
    GitSync(store, tmp_path / "checkout", str(remote), private_verified=True, owner_verified=True)
    db = ledger(tmp_path, approval)
    with pytest.raises(SyncError):
        GitSync(store, tmp_path / "checkout", str(remote), private_verified=True, owner_verified=True, legacy=db)
