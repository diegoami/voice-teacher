"""Original synthetic history only; never reads the learner repositories."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from voice_teacher.progress.preview import plan_preview
from voice_teacher.progress.preview import PreviewError, write_report


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fixture(tmp_path):
    root = tmp_path / "history"
    root.mkdir()
    content = {
        "tracker.md": ("tracker", "# Synthetic tracker\n\n## Sentence practice\n\n"
                       "| Sentence or pattern | Sessions | Evidence |\n| --- | --- | --- |\n"
                       "| Sample alpha | A | Repeated after a model |\n"
                       "| Sample ambiguous | A | Might have been cued |\n"),
        "queue.md": ("queue", "# Synthetic queue\n\n## Repetition history\n\n"
                     "| Target | Original source | Practice source | Evidence |\n| --- | --- | --- | --- |\n"
                     "| Sample alpha | Course A, unit A | Course B, unit B | Repeated |\n"),
        "session.md": ("session", "# Synthetic transcript\n\n## Record 1\n\n"
                       "Learner: Sample mistake\nTeacher: Sample preferred; synthetic reason\n\n"
                       "## Record 2\n\nLearner: Sample mistake\nTeacher: Sample preferred; synthetic reason\n"),
    }
    inputs = []
    for path, (kind, text) in content.items():
        (root / path).write_text(text)
        inputs.append(dict(path=path, kind=kind, sha256=digest(text)))
    return root, dict(format_version=1, namespace="synthetic-import", learner_id="synthetic-learner", inputs=inputs, mappings=[])


def mapped(tmp_path):
    root, manifest = fixture(tmp_path)
    discovered = plan_preview(root, manifest)
    original = dict(source_id="course-a", course_id="a", lesson_id="unit-a")
    other = dict(source_id="course-b", course_id="b", lesson_id="unit-b")
    for record in discovered["records"]:
        raw = record["raw"]
        if "Sample ambiguous" in raw:
            continue
        mapping = dict(record_id=record["record_id"], observation_key="opening",
                       original_source=original, practice_source=original,
                       assistance="repeated", correction=None, repetition_of=None)
        if record["kind"] == "queue":
            mapping.update(observation_key="later", practice_source=other, repetition_of="opening")
        elif record["kind"] == "session":
            mapping.update(observation_key="correction", assistance="corrected_repeated",
                           correction=dict(attempt="Sample mistake", preferred="Sample preferred", reason="Synthetic reason"))
        manifest["mappings"].append(mapping)
    return root, manifest


def test_reconciles_original_repetition_correction_and_ambiguous_without_double_counting(tmp_path):
    root, manifest = mapped(tmp_path)
    report = plan_preview(root, manifest)
    assert report["counts"] == dict(records=5, proposed=4, unresolved=1, conflict=0, observations=3)
    assert len(report["observations"]) == 3
    later = next(o for o in report["observations"] if o["observation_key"] == "later")
    opening = next(o for o in report["observations"] if o["observation_key"] == "opening")
    assert later["original_source"] == opening["original_source"]
    assert later["practice_source"]["source_id"] == "course-b"
    assert later["repetition_of"] == opening["proposed_id"]
    correction = next(o for o in report["observations"] if o["observation_key"] == "correction")
    assert len(correction["record_ids"]) == 2  # two explicit copies, one observation
    assert correction["correction"]["attempt"] == "Sample mistake"
    unresolved = [r for r in report["records"] if r["status"] == "unresolved"]
    assert "Sample ambiguous" in unresolved[0]["raw"]
    assert unresolved[0]["proposal"] is None


def test_repeat_planning_is_identical_and_does_not_write_input_or_other_state(tmp_path):
    root, manifest = mapped(tmp_path)
    database = tmp_path / "database.sqlite"
    database.write_bytes(b"UNCHANGED DATABASE")
    progress = tmp_path / "progress"
    progress.mkdir()
    (progress / "unrelated").write_text("UNCHANGED HISTORY")
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    first = plan_preview(root, manifest)
    assert first == plan_preview(root, copy.deepcopy(manifest))
    reverse = copy.deepcopy(manifest)
    reverse["inputs"].reverse()
    reverse["mappings"].reverse()
    assert first == plan_preview(root, reverse)
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_unknown_evidence_stays_null_and_raw_metadata_is_not_lost(tmp_path):
    root, manifest = fixture(tmp_path)
    report = plan_preview(root, manifest)
    assert report["counts"]["records"] == 5
    assert report["counts"]["unresolved"] == 5
    assert all(r["proposal"] is None for r in report["records"])
    assert report["inputs"][0]["raw"] == (root / report["inputs"][0]["path"]).read_text()


def test_explicit_mapping_with_unknown_assistance_does_not_invent_independent_use(tmp_path):
    root, manifest = mapped(tmp_path)
    for m in manifest["mappings"]:
        m["assistance"] = None
    report = plan_preview(root, manifest)
    assert all(o["assistance"] is None for o in report["observations"])


def test_disagreeing_explicit_duplicate_mappings_are_conflicts_not_last_writer_wins(tmp_path):
    root, manifest = mapped(tmp_path)
    copies = [m for m in manifest["mappings"] if m["observation_key"] == "correction"]
    copies[1]["correction"]["preferred"] = "Other preferred"
    report = plan_preview(root, manifest)
    assert report["counts"]["conflict"] == 2
    assert not any(o["observation_key"] == "correction" for o in report["observations"])
    assert len([r for r in report["records"] if r["status"] == "conflict"]) == 2


@pytest.mark.parametrize("change", ["hash", "stale_record", "duplicate_input", "duplicate_mapping", "extra", "mastery", "traversal"])
def test_refuses_stale_or_unsupported_operator_mapping(tmp_path, change):
    root, manifest = mapped(tmp_path)
    if change == "hash":
        (root / "tracker.md").write_text("Changed source")
    elif change == "stale_record":
        manifest["mappings"][0]["record_id"] = "missing-record"
    elif change == "duplicate_input":
        manifest["inputs"].append(manifest["inputs"][0])
    elif change == "duplicate_mapping":
        manifest["mappings"].append(manifest["mappings"][0])
    elif change == "extra":
        manifest["mappings"][0]["mastery"] = True
    elif change == "mastery":
        manifest["mappings"][0]["assistance"] = "mastered"
    elif change == "traversal":
        manifest["inputs"][0]["path"] = "../outside.md"
    with pytest.raises(PreviewError):
        plan_preview(root, manifest)


@pytest.mark.parametrize("nested", [False, True])
def test_source_symlinks_are_refused_even_when_hash_matches(tmp_path, nested):
    root, manifest = fixture(tmp_path)
    entry = manifest["inputs"][0]
    path = root / entry["path"]
    outside = tmp_path / "outside"
    outside.mkdir()
    text = path.read_text()
    (outside / "copy.md").write_text(text)
    path.unlink()
    if nested:
        (root / "linked").symlink_to(outside, target_is_directory=True)
        entry["path"] = "linked/copy.md"
    else:
        path.symlink_to(outside / "copy.md")
    with pytest.raises((OSError, PreviewError)):
        plan_preview(root, manifest)


@pytest.mark.parametrize("relationship", ["missing", "cycle", "different_origin"])
def test_broken_or_cyclic_repetition_references_do_not_create_proposals(tmp_path, relationship):
    root, manifest = mapped(tmp_path)
    opening = next(m for m in manifest["mappings"] if m["observation_key"] == "opening")
    later = next(m for m in manifest["mappings"] if m["observation_key"] == "later")
    if relationship == "missing":
        later["repetition_of"] = "nonexistent"
    elif relationship == "cycle":
        opening["repetition_of"] = "later"
    else:
        later["original_source"] = dict(source_id="other", course_id="other", lesson_id="other")
    report = plan_preview(root, manifest)
    assert not any(o["observation_key"] == "later" for o in report["observations"])
    assert report["counts"]["conflict"] >= 1
    assert report["counts"]["records"] == sum(report["counts"][s] for s in ("proposed", "unresolved", "conflict"))


def test_malformed_rows_and_unknown_prose_are_preserved_not_silently_dropped(tmp_path):
    root, manifest = fixture(tmp_path)
    path = root / "tracker.md"
    path.write_text(path.read_text() + "| broken | extra | columns | retained |\n\nOpaque summary without assistance.\n\n```text\nraw line\n\nraw continuation\n```\n")
    next(s for s in manifest["inputs"] if s["path"] == "tracker.md")["sha256"] = digest(path.read_text())
    report = plan_preview(root, manifest)
    assert report["counts"]["records"] == 8
    assert any(r["parse_issue"] for r in report["records"])
    assert any("raw line\n\nraw continuation" in r["raw"] for r in report["records"])
    assert report["counts"]["unresolved"] == 8


def test_equal_phrases_in_distinct_courses_never_merge_implicitly(tmp_path):
    root, manifest = mapped(tmp_path)
    copies = [m for m in manifest["mappings"] if m["observation_key"] == "correction"]
    copies[1]["observation_key"] = "other-course-correction"
    copies[1]["original_source"] = dict(source_id="course-c", course_id="c", lesson_id="c")
    report = plan_preview(root, manifest)
    assert report["counts"]["observations"] == 4
    assert len({o["proposed_id"] for o in report["observations"]}) == 4


def test_private_report_is_exclusive_and_cannot_write_protected_roots(tmp_path):
    root, manifest = fixture(tmp_path)
    report = plan_preview(root, manifest)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = private / "preview.json"
    write_report(report, output, forbidden_roots=[root])
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text()) == report
    with pytest.raises(FileExistsError):
        write_report(report, output, forbidden_roots=[root])
    with pytest.raises(PreviewError):
        write_report(report, root / "forbidden.json", forbidden_roots=[root])
    checkout = tmp_path / "other-checkout"
    checkout.mkdir(mode=0o700)
    (checkout / ".git").write_text("gitdir: irrelevant")
    with pytest.raises(PreviewError):
        write_report(report, checkout / "forbidden.json")
    assert not (root / "forbidden.json").exists()
    assert not (checkout / "forbidden.json").exists()


def test_real_cli_writes_only_private_report_and_prints_no_private_payload(tmp_path):
    root, manifest = mapped(tmp_path)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    mapping_file = private / "mapping.json"
    mapping_file.write_text(json.dumps(manifest))
    output = private / "preview.json"
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    command = [sys.executable, "-m", "voice_teacher.progress.preview", "--root", str(root),
               "--manifest", str(mapping_file), "--output", str(output)]
    result = subprocess.run(command, capture_output=True, text=True, check=False, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["counts"]["observations"] == 3
    assert "Sample" not in result.stdout + result.stderr
    after = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert set(after) - set(before) == {str(output)}
    assert all(after[p] == data for p, data in before.items())
    # Failure is also side-effect free and does not echo private input content.
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "Traceback" not in result.stderr and "Sample" not in result.stderr


def test_cli_rejects_duplicate_manifest_keys_and_public_report_parent(tmp_path):
    from voice_teacher.progress.preview import main
    root, manifest = fixture(tmp_path)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    mapping = private / "mapping.json"
    mapping.write_text('{"format_version":1,"format_version":2}')
    with pytest.raises(SystemExit) as error:
        main(["--root", str(root), "--manifest", str(mapping), "--output", str(private / "report.json")])
    assert error.value.code == 2
    assert not (private / "report.json").exists()
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    with pytest.raises(PreviewError):
        write_report(plan_preview(root, manifest), public / "report.json")


def test_input_byte_limit_and_nonregular_input_are_refused(tmp_path, monkeypatch):
    import voice_teacher.progress.preview as module
    root, manifest = fixture(tmp_path)
    monkeypatch.setattr(module, "MAX_TOTAL_BYTES", 1)
    with pytest.raises(PreviewError):
        plan_preview(root, manifest)
    monkeypatch.setattr(module, "MAX_TOTAL_BYTES", 16 * 1024 * 1024)
    path = root / manifest["inputs"][0]["path"]
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(PreviewError):
        plan_preview(root, manifest)
