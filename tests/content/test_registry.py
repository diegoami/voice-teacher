from dataclasses import replace
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess

import pytest

from schemas.validate import validate_session
from voice_teacher.content.registry import SourceRegistry, SourceSpec, SourceError
from voice_teacher.practice.coordinator import Coordinator
from voice_teacher.providers import Verdict, Judgement
from voice_teacher.storage import Store
from voice_teacher.storage.migrations import APPLICATION_ID, V1, V2, V3, VERSION
from test_legacy_adapter import fixture as legacy_fixture


def git(root, *args):
    env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
    return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args], env=env, stderr=subprocess.PIPE).decode().strip()


def catalogue(source_id, speech="Приві́т"):
    value = json.loads((Path(__file__).resolve().parents[1] / "contracts/fixtures/guided.json").read_text())
    value["source_id"] = source_id
    course = value["courses"][0]
    course["items"][0]["text"] = {"display": speech.replace("́", ""), "speech": speech}
    lesson = course["lessons"][0]
    lesson["lesson_id"] = "4B"
    lesson["modes"] = ["repetition", "guided_conversation"]
    lesson["repetition_item_ids"] = ["hello"]
    return value


def source(tmp_path, source_id="alpha", speech="Приві́т", *, committed=True):
    root = tmp_path / source_id; root.mkdir(parents=True)
    (root / "content").mkdir()
    value = catalogue(source_id, speech)
    (root / "content/voice-teacher.json").write_text(json.dumps(value, ensure_ascii=False))
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "synthetic@example.invalid")
    git(root, "config", "user.name", "Synthetic fixture")
    git(root, "config", "core.autocrlf", "false")
    if committed:
        git(root, "add", "content/voice-teacher.json")
        git(root, "commit", "-qm", "Synthetic source")
    return root, value, SourceSpec(source_id, source_id.title(), str(root), subdirectory="content")


def registry(tmp_path):
    store = Store(tmp_path / "runtime")
    return store, SourceRegistry(store)


def test_two_sources_with_4b_keep_distinct_namespace_and_evidence(tmp_path):
    store, reg = registry(tmp_path)
    snapshots = []
    for name, phrase in [("alpha", "Приві́т"), ("beta", "Дя́кую")]:
        root, _, spec = source(tmp_path, name, phrase)
        reg.register(spec)
        snap = reg.refresh(name); snapshots.append(snap)
        assert snap.provenance["commit"] == git(root, "rev-parse", "HEAD")
        assert snap.provenance["dirty"] is False
        assert snap.lesson("basics", "4B")["lesson_id"] == "4B"
        c = Coordinator(store, lambda *args: Judgement(Verdict("accept", True, "", "", 0, ""), 0, {}), clock=lambda: 0)
        store.save_learner("learner", {})
        template = dict(schema_version=1, kind="session_snapshot", learner_id="learner", session_id=name, revision=0,
                        event_sequence=0, mode="guided_conversation", status="created", source=snap.source_ref("basics", "4B"),
                        curriculum_snapshot=snap.curriculum, topic=None, language="uk", instruction_language="en", learner_profile={},
                        engine_state={"format_version": 1, "data": {}})
        c.create(template, snap.prepared_lesson("basics", "4B"), part="2")
        c.submit("learner", name, "r1", expected_revision=0, text=phrase)
    assert snapshots[0].version_id != snapshots[1].version_id
    refs = [store.projection("learner", name)["evidence"][0]["provenance"]["original_item"] for name in ["alpha", "beta"]]
    assert [r["source_id"] for r in refs] == ["alpha", "beta"]
    assert refs[0]["item_id"] == refs[1]["item_id"] == "hello"
    assert str(tmp_path) not in str(reg.list_sources())


def test_invalid_refresh_preserves_last_active_across_restart(tmp_path):
    store, reg = registry(tmp_path)
    root, _, spec = source(tmp_path)
    reg.register(spec)
    before = reg.refresh("alpha")
    (root / "content/voice-teacher.json").write_text('{"broken":true}')
    with pytest.raises(SourceError): reg.refresh("alpha")
    assert reg.active("alpha").version_id == before.version_id
    restarted = SourceRegistry(Store(store.path.parent))
    assert restarted.active("alpha").curriculum == before.curriculum
    assert restarted.list_sources()[0]["error"]
    with store._connection() as c:
        assert c.execute("SELECT COUNT(*) FROM source_versions").fetchone()[0] == 1


def test_active_session_resumes_original_snapshot_after_valid_update(tmp_path):
    store, reg = registry(tmp_path)
    root, value, spec = source(tmp_path)
    reg.register(spec); old = reg.refresh("alpha")
    store.save_learner("learner", {})
    c = Coordinator(store, lambda *args: Judgement(Verdict("accept", True, "", "", 0, ""), 0, {}), clock=lambda: 0)
    template = dict(schema_version=1, kind="session_snapshot", learner_id="learner", session_id="pinned", revision=0,
                    event_sequence=0, mode="guided_conversation", status="created", source=old.source_ref("basics", "4B"),
                    curriculum_snapshot=old.curriculum, topic=None, language="uk", instruction_language="en", learner_profile={},
                    engine_state={"format_version": 1, "data": {}})
    c.create(template, old.prepared_lesson("basics", "4B"), part="2")
    item = value["courses"][0]["items"][0]
    item["text"] = {"display": "Дякую", "speech": "Дя́кую"}; item["item_revision"] = 2
    (root / "content/voice-teacher.json").write_text(json.dumps(value, ensure_ascii=False))
    git(root, "add", "content/voice-teacher.json"); git(root, "commit", "-qm", "Reviewed revision 2")
    new = reg.refresh("alpha")
    assert new.version_id != old.version_id
    assert new.prepared_lesson("basics", "4B").steps[0].targets == ["Дя́кую"]
    assert old.prepared_lesson("basics", "4B").steps[0].targets == ["Приві́т"]
    restarted = Coordinator(Store(store.path.parent), c.judge, clock=lambda: 0)
    assert restarted._engine(store.session("learner", "pinned"), c.judge).lesson.steps[0].targets == ["Приві́т"]
    restarted.submit("learner", "pinned", "r1", expected_revision=0, text="Привіт")
    saved = store.session("learner", "pinned")
    validate_session(saved)
    assert saved["source"] == old.source_ref("basics", "4B")


def test_dirty_and_untracked_content_require_explicit_snapshot_policy(tmp_path):
    _, reg = registry(tmp_path)
    root, value, spec = source(tmp_path, committed=False)
    reg.register(spec)
    with pytest.raises(SourceError, match="explicitly enable dirty"): reg.refresh("alpha")
    reg.register(replace(spec, allow_dirty=True))
    uncommitted = reg.refresh("alpha")
    assert uncommitted.provenance["commit"] is None and uncommitted.provenance["dirty"]
    git(root, "add", "content/voice-teacher.json"); git(root, "commit", "-qm", "Commit reviewed source")
    clean = reg.refresh("alpha")
    assert clean.provenance["commit"] and not clean.provenance["dirty"]
    value["title"] = "Dirty source title"
    (root / "content/voice-teacher.json").write_text(json.dumps(value, ensure_ascii=False))
    dirty = reg.refresh("alpha")
    assert dirty.provenance["dirty"] and dirty.provenance["commit"] == clean.provenance["commit"]
    assert dirty.source_ref("basics", "4B")["revision"]["content_sha256"] != clean.source_ref("basics", "4B")["revision"]["content_sha256"]


def test_non_git_source_is_only_an_explicit_dirty_snapshot(tmp_path):
    _, reg = registry(tmp_path)
    root = tmp_path / "plain"; root.mkdir()
    (root / "voice-teacher.json").write_text(json.dumps(catalogue("plain")))
    reg.register(SourceSpec("plain", "Plain", str(root), allow_dirty=True))
    snap = reg.refresh("plain")
    assert snap.provenance["commit"] is None and snap.provenance["dirty"]


def test_conflicting_item_revision_does_not_replace_active_catalogue(tmp_path):
    store, reg = registry(tmp_path)
    root, value, spec = source(tmp_path)
    reg.register(replace(spec, allow_dirty=True)); old = reg.refresh("alpha")
    value["courses"][0]["items"][0]["meaning"] = "Changed without revision bump"
    (root / "content/voice-teacher.json").write_text(json.dumps(value))
    with pytest.raises(SourceError, match="increase its revision"): reg.refresh("alpha")
    assert reg.active("alpha").version_id == old.version_id
    with store._connection() as c:
        assert c.execute("SELECT COUNT(*) FROM source_versions").fetchone()[0] == 1


def test_paths_symlinks_and_namespace_mismatch_are_refused(tmp_path):
    _, reg = registry(tmp_path)
    root, value, spec = source(tmp_path)
    for subdir in ["../outside", str(tmp_path), "content\\escape"]:
        with pytest.raises(SourceError): reg.register(replace(spec, subdirectory=subdir))
    (root / "escape").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(SourceError, match="symlinks"): reg.register(replace(spec, subdirectory="escape"))
    reg.register(spec)
    outside = tmp_path / "outside.json"; outside.write_text(json.dumps(value))
    (root / "content/voice-teacher.json").unlink()
    (root / "content/voice-teacher.json").symlink_to(outside)
    with pytest.raises(SourceError, match="symlinks"): reg.refresh("alpha")
    (root / "content/voice-teacher.json").unlink()
    value["source_id"] = "different"
    (root / "content/voice-teacher.json").write_text(json.dumps(value))
    with pytest.raises(SourceError, match="namespace"): reg.refresh("alpha")


def test_repository_scripts_hooks_and_configured_filters_never_execute(tmp_path):
    _, reg = registry(tmp_path)
    root, _, spec = source(tmp_path)
    marker = tmp_path / "executed"
    evil = root / "evil.sh"; evil.write_text("#!/bin/sh\nprintf executed > " + shlex.quote(str(marker)) + "\n"); evil.chmod(0o755)
    (root / ".gitattributes").write_text("* filter=evil\n")
    git(root, "config", "core.fsmonitor", str(evil))
    git(root, "config", "filter.evil.clean", str(evil))
    git(root, "config", "alias.cat-file", "!" + str(evil))
    (root / ".git/hooks/post-checkout").write_text(evil.read_text()); (root / ".git/hooks/post-checkout").chmod(0o755)
    before = (root / "content/voice-teacher.json").read_bytes()
    os.utime(root / "content/voice-teacher.json", None)
    reg.register(spec)
    snapshot = reg.refresh("alpha")
    assert not marker.exists()
    assert not snapshot.provenance["dirty"]
    assert (root / "content/voice-teacher.json").read_bytes() == before


def test_config_or_head_change_during_compile_cannot_activate(tmp_path, monkeypatch):
    import voice_teacher.content.registry as implementation
    _, reg = registry(tmp_path)
    root, _, spec = source(tmp_path)
    reg.register(spec); old = reg.refresh("alpha")
    original = implementation._canonical
    def changed_config(*args):
        result = original(*args); reg.register(replace(spec, name="Renamed")); return result
    monkeypatch.setattr(implementation, "_canonical", changed_config)
    with pytest.raises(SourceError, match="configuration changed"): reg.refresh("alpha")
    assert reg.active("alpha").version_id == old.version_id
    def changed_head(*args):
        result = original(*args); git(root, "commit", "--allow-empty", "-qm", "Concurrent ref change"); return result
    monkeypatch.setattr(implementation, "_canonical", changed_head)
    with pytest.raises(SourceError, match="revision changed"): reg.refresh("alpha")
    assert reg.active("alpha").version_id == old.version_id


def test_legacy_source_keeps_private_context_out_of_safe_default_plan(tmp_path):
    _, reg = registry(tmp_path)
    root, mapping, _ = legacy_fixture(tmp_path)
    git(root, "init", "-q", "-b", "main"); git(root, "config", "user.email", "synthetic@example.invalid"); git(root, "config", "user.name", "Synthetic")
    git(root, "add", "."); git(root, "commit", "-qm", "Synthetic legacy content")
    spec = SourceSpec("synthetic-source", "Legacy", str(root), adapter="legacy", mapping=mapping)
    reg.register(spec); snap = reg.refresh("synthetic-source")
    assert "SYNTHETIC_PRIVATE" not in str(snap.curriculum)
    assert "SYNTHETIC_PRIVATE" in str(snap.private_session_inputs("basics", "4B"))
    safe = snap.prepared_lesson("basics", "4B")
    assert safe.introduction == "" and all(s.setting == "" for s in safe.steps)
    assert "SYNTHETIC_PRIVATE" not in str(safe.to_dict())


def test_partial_mode_catalogue_does_not_invent_missing_engine_phases(tmp_path):
    _, reg = registry(tmp_path)
    root, value, spec = source(tmp_path)
    lesson = value["courses"][0]["lessons"][0]
    lesson.update(modes=["repetition"], guided_steps=[], recall_goals=[])
    (root / "content/voice-teacher.json").write_text(json.dumps(value))
    reg.register(replace(spec, allow_dirty=True)); snap = reg.refresh("alpha")
    assert snap.lesson("basics", "4B")["modes"] == ["repetition"]
    with pytest.raises(SourceError, match="mode-specific planner"):
        snap.prepared_lesson("basics", "4B")


def test_safe_copies_and_repeated_refresh_are_stable(tmp_path):
    _, reg = registry(tmp_path)
    root, _, spec = source(tmp_path)
    reg.register(spec); one = reg.refresh("alpha")
    one.curriculum["courses"].clear()
    one.prepared_lesson("basics", "4B").opening.clear()
    two = reg.refresh("alpha")
    assert one.version_id == two.version_id
    assert two.prepared_lesson("basics", "4B").opening == ["Приві́т"]
    assert reg.list_sources()[0]["error"] is None


def test_database_inside_source_is_refused_but_managed_child_checkout_is_allowed(tmp_path):
    store, reg = registry(tmp_path)
    with pytest.raises(SourceError, match="outside"):
        reg.register(SourceSpec("bad", "Bad", str(store.path.parent)))
    _, _, spec = source(store.path.parent / "source-cache")
    reg.register(spec)
    assert reg.refresh("alpha").curriculum["source_id"] == "alpha"


def test_nested_git_directory_must_use_explicit_checkout_root(tmp_path):
    _, reg = registry(tmp_path)
    root, _, spec = source(tmp_path)
    reg.register(replace(spec, checkout=str(root / "content"), subdirectory=".", allow_dirty=True))
    with pytest.raises(SourceError, match="Git checkout root"): reg.refresh("alpha")


@pytest.mark.parametrize("failure", [False, True])
def test_v3_registry_migration_preserves_data_and_rolls_back_on_failure(tmp_path, monkeypatch, failure):
    import voice_teacher.storage.sqlite as implementation
    directory = tmp_path / "runtime"; directory.mkdir()
    path = directory / "voice-teacher.sqlite"
    with sqlite3.connect(path) as c:
        for sql in (*V1, *V2, *V3): c.execute(sql)
        c.execute(f"PRAGMA application_id={APPLICATION_ID}"); c.execute("PRAGMA user_version=3")
        c.execute("INSERT INTO learners VALUES ('preserve','{}')")
    if failure:
        monkeypatch.setattr(implementation, "V4", (*implementation.V4, "SELECT bad_registry_migration()"))
        with pytest.raises(sqlite3.OperationalError): Store(directory)
        with sqlite3.connect(path) as c:
            assert c.execute("PRAGMA user_version").fetchone()[0] == 3
            assert c.execute("SELECT name FROM sqlite_master WHERE name='sources'").fetchall() == []
    else:
        store = Store(directory)
        assert store.learner("preserve") == {}
        with store._connection() as c:
            assert c.execute("PRAGMA user_version").fetchone()[0] == VERSION
