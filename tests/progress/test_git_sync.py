from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from voice_teacher.progress import Archive
from voice_teacher.progress.git_sync import GitSync, SyncError
from voice_teacher.storage import Store
from test_roundtrip import session, turn, LEARNER


def git(root, *args):
    return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
        env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
        stderr=subprocess.PIPE).decode().strip()


def remote(tmp_path):
    root = tmp_path / "remote.git"; root.mkdir()
    git(root, "init", "--bare", "--template=", "-q", "-b", "main")
    return root


def worker(tmp_path, upstream, *, name="one", store=None):
    store = store or Store(tmp_path / (name + "-data"))
    return GitSync(store, tmp_path / (name + "-checkout"), str(upstream), private_verified=True, owner_verified=True)


def test_disconnected_practice_push_failure_restart_and_retry(tmp_path, monkeypatch):
    upstream = remote(tmp_path)
    w = worker(tmp_path, upstream)
    c = session(w.store)
    assert {e["state"] for e in w.status()["events"]} == {"locally_saved"}
    # A real absent remote exercises disconnected practice; DB remains usable.
    original_remote = upstream.with_name("offline.git")
    upstream.rename(original_remote)
    with pytest.raises(SyncError): w.run_once()
    assert w.store.pending_exports()
    turn(c)
    original_remote.rename(upstream)
    original = w._git
    def fail_push(*args, **kwargs):
        if args[0] == "push": raise SyncError("injected disconnected push")
        return original(*args, **kwargs)
    monkeypatch.setattr(w, "_git", fail_push)
    with pytest.raises(SyncError): w.run_once()
    state = w.status()
    assert {e["state"] for e in state["events"]} == {"exported"}
    assert state["last_push_at"] is None and state["error"]
    assert w.store.pending_exports() == []  # local export succeeded; remote job remains pending
    before = w.store.events(LEARNER, "alpha")
    script = """import json,sys
from voice_teacher.storage import Store
from voice_teacher.progress.git_sync import GitSync
w=GitSync(Store(sys.argv[1]),sys.argv[2],sys.argv[3],private_verified=True,owner_verified=True)
print(json.dumps(w.run_once()))
"""
    status = json.loads(subprocess.check_output([sys.executable, "-c", script, str(w.store.path.parent), str(w.checkout), str(upstream)], text=True))
    restarted = worker(tmp_path, upstream, store=Store(w.store.path.parent))
    assert {e["state"] for e in status["events"]} == {"pushed"}
    assert status["last_push_at"] and status["error"] is None
    assert git(upstream, "rev-parse", "main") == status["last_push_commit"]
    assert restarted.store.events(LEARNER, "alpha") == before
    assert restarted.run_once()["last_push_commit"] == status["last_push_commit"]


def test_distinct_remote_batches_reconcile_and_restore_without_losing_history(tmp_path):
    upstream = remote(tmp_path)
    first = worker(tmp_path, upstream); c = session(first.store); first.run_once()
    second = worker(tmp_path, upstream, name="two")
    second.run_once()
    assert second.store.events(LEARNER, "alpha") == first.store.events(LEARNER, "alpha")
    turn(c)
    first.archive.export(first.store)
    first._commit()  # locally committed, not pushed: branches will diverge
    other = session(second.store, "beta"); turn(other, "beta")
    second.run_once()
    first.run_once()
    second.run_once()
    for name in ["alpha", "beta"]:
        assert first.store.events(LEARNER, name) == second.store.events(LEARNER, name)
    assert first.archive.read() == second.archive.read()
    assert {e["state"] for e in first.status()["events"]} == {"pushed"}
    assert len(git(upstream, "show", "-s", "--format=%P", "main").split()) == 2


@pytest.mark.parametrize("staged", [False, True])
def test_unrelated_dirty_files_are_never_committed_or_overwritten(tmp_path, staged):
    upstream = remote(tmp_path); w = worker(tmp_path, upstream)
    session(w.store); w.run_once()
    before = git(upstream, "rev-parse", "main")
    foreign = w.checkout / "card-review.jsonl"; foreign.write_text("unrelated sentinel")
    if staged: git(w.checkout, "add", "card-review.jsonl")
    with pytest.raises(SyncError, match="dirty"): w.run_once()
    assert foreign.read_text() == "unrelated sentinel"
    assert git(upstream, "rev-parse", "main") == before
    assert "card-review" not in git(upstream, "ls-tree", "--name-only", "-r", "main")


def test_remote_sentinel_is_preserved_and_hook_config_is_not_adopted(tmp_path):
    upstream = remote(tmp_path)
    seed = tmp_path / "seed"; seed.mkdir()
    git(seed, "init", "--template=", "-q", "-b", "main")
    git(seed, "config", "user.email", "synthetic@example.invalid"); git(seed, "config", "user.name", "Synthetic")
    (seed / "card-review.jsonl").write_text("unrelated card history")
    git(seed, "add", "card-review.jsonl"); git(seed, "commit", "-qm", "Seed unrelated format")
    git(seed, "remote", "add", "origin", str(upstream)); git(seed, "push", "-q", "origin", "main")
    w = worker(tmp_path, upstream); session(w.store); w.run_once()
    assert (w.checkout / "card-review.jsonl").read_text() == "unrelated card history"
    assert git(upstream, "show", "main:card-review.jsonl") == "unrelated card history"
    marker = tmp_path / "executed"
    executable = w.checkout / "malicious.sh"; executable.write_text("#!/bin/sh\ntouch " + str(marker) + "\n"); executable.chmod(0o755)
    git(w.checkout, "config", "core.fsmonitor", str(executable))
    with pytest.raises(SyncError, match="configuration changed"): w.run_once()
    assert not marker.exists()


def test_differing_event_history_is_not_overwritten_or_pushed(tmp_path):
    upstream = remote(tmp_path); first = worker(tmp_path, upstream)
    session(first.store); first.run_once()
    second = worker(tmp_path, upstream, name="two"); second.run_once()
    original = second.store.events(LEARNER, "alpha")
    value = json.loads(next((first.checkout / Archive.NAMESPACE).glob("*.json")).read_bytes())
    value["events"][0]["occurred_at"] = "2026-10-16T00:00:00Z"
    name = first.archive._publish(value)
    # Simulate a foreign writer bypassing the app conflict gate.
    first._git("add", "--", str(Archive.NAMESPACE / name))
    first._git("commit", "-qm", "Inject conflicting remote history")
    first._git("push", "origin", "HEAD:refs/heads/main")
    remote_head = git(upstream, "rev-parse", "main")
    with pytest.raises(ValueError, match="different contents"): second.run_once()
    assert second.store.events(LEARNER, "alpha") == original
    assert git(upstream, "rev-parse", "main") == remote_head
    assert second.status()["error"]


def test_lost_push_response_retries_without_duplicate_events(tmp_path, monkeypatch):
    upstream = remote(tmp_path); w = worker(tmp_path, upstream); session(w.store)
    original = w._git
    def response_lost(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[0] == "push": raise SyncError("response lost after remote accepted push")
        return result
    monkeypatch.setattr(w, "_git", response_lost)
    with pytest.raises(SyncError): w.run_once()
    assert w.status()["last_push_at"] is None
    commit = git(upstream, "rev-parse", "main")
    restarted = worker(tmp_path, upstream, store=Store(w.store.path.parent))
    assert restarted.run_once()["last_push_commit"] == commit
    assert len(restarted.archive.read()) == len(restarted.store.events(LEARNER, "alpha"))


def test_destination_privacy_handoff_and_existing_checkout_gates(tmp_path):
    upstream = remote(tmp_path); store = Store(tmp_path / "data")
    with pytest.raises(SyncError, match="verify"): GitSync(store, tmp_path / "checkout", str(upstream))
    w = worker(tmp_path, upstream, store=store)
    other = tmp_path / "other-remote.git"
    with pytest.raises(SyncError, match="destination changed"):
        GitSync(store, tmp_path / "different", str(other), private_verified=True, owner_verified=True)
    fresh = Store(tmp_path / "fresh-data")
    with pytest.raises(SyncError, match="existing checkout"):
        GitSync(fresh, w.checkout, str(upstream), private_verified=True, owner_verified=True)
    with pytest.raises(SyncError, match="credential-free"):
        GitSync(fresh, tmp_path / "bad-checkout", "https://user:secret@example.invalid/repo", private_verified=True, owner_verified=True)


def test_single_writer_lock_and_background_worker(tmp_path, monkeypatch):
    upstream = remote(tmp_path); w = worker(tmp_path, upstream); session(w.store)
    with w._locked():
        with pytest.raises(SyncError, match="already running"): w.run_once()
    entered = threading.Event(); release = threading.Event(); thread_ids = []
    original = w.run_once
    def paused():
        thread_ids.append(threading.get_ident()); entered.set(); release.wait(2)
        return original()
    monkeypatch.setattr(w, "run_once", paused)
    w.start(interval=.01)
    assert entered.wait(2)
    assert thread_ids[0] != threading.get_ident()
    assert w.stop(timeout=.01) is False  # never falsely claim a busy writer stopped
    release.set()
    assert w.stop(timeout=5) is True
    assert w.status()["last_push_at"]


def test_content_and_runtime_overlaps_are_refused_before_git_writes(tmp_path):
    from voice_teacher.content.registry import SourceRegistry, SourceSpec
    upstream = remote(tmp_path); store = Store(tmp_path / "data")
    content = tmp_path / "content"; content.mkdir()
    SourceRegistry(store).register(SourceSpec("content", "Content", str(content)))
    for checkout in [store.path.parent / "checkout", content / "checkout"]:
        with pytest.raises(SyncError): GitSync(store, checkout, str(upstream), private_verified=True, owner_verified=True)
        assert not checkout.exists()


def test_failed_commit_recovers_only_app_staged_files(tmp_path, monkeypatch):
    upstream = remote(tmp_path); w = worker(tmp_path, upstream); session(w.store)
    original = w._git
    def failed_commit(*args, **kwargs):
        if args[0] == "commit": raise SyncError("injected commit failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(w, "_git", failed_commit)
    with pytest.raises(SyncError): w.run_once()
    assert git(w.checkout, "status", "--porcelain").startswith("A ")
    restarted = worker(tmp_path, upstream, store=Store(w.store.path.parent))
    assert {e["state"] for e in restarted.run_once()["events"]} == {"pushed"}


def test_last_success_receipt_survives_later_failure(tmp_path, monkeypatch):
    upstream = remote(tmp_path); w = worker(tmp_path, upstream); c = session(w.store)
    successful = w.run_once()
    turn(c)
    assert {e["state"] for e in w.status()["events"]} == {"pushed", "locally_saved"}
    original = w._git
    def fail_push(*args, **kwargs):
        if args[0] == "push": raise SyncError("failed push")
        return original(*args, **kwargs)
    monkeypatch.setattr(w, "_git", fail_push)
    with pytest.raises(SyncError): w.run_once()
    status = w.status()
    assert status["last_push_at"] == successful["last_push_at"]
    assert status["last_push_commit"] == successful["last_push_commit"]
    assert {e["state"] for e in status["events"]} == {"pushed", "exported"}


def test_unfinished_git_operation_is_retained_for_operator_inspection(tmp_path):
    upstream = remote(tmp_path); w = worker(tmp_path, upstream); session(w.store)
    marker = w.git_dir / "MERGE_HEAD"; marker.write_text("synthetic incomplete merge")
    with pytest.raises(SyncError, match="unfinished Git"): w.run_once()
    assert marker.read_text() == "synthetic incomplete merge"
    assert w.store.pending_exports()


def test_git_network_wait_does_not_hold_a_sqlite_write_transaction(tmp_path, monkeypatch):
    upstream = remote(tmp_path); w = worker(tmp_path, upstream); session(w.store)
    original = w._git; stages = []
    def probe(*args, **kwargs):
        if args[0] in {"ls-remote", "fetch", "push"}:
            # This independent writer would time out if Git ran inside BEGIN IMMEDIATE.
            Store(w.store.path.parent, timeout=.1).save_learner("write-probe", {})
            stages.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr(w, "_git", probe)
    w.run_once(); w.run_once()
    assert {"ls-remote", "fetch", "push"} <= set(stages)


def test_staged_temporary_file_cannot_enter_a_progress_commit(tmp_path):
    upstream = remote(tmp_path); w = worker(tmp_path, upstream); c = session(w.store); w.run_once()
    previous = git(upstream, "rev-parse", "main")
    temporary = w.checkout / Archive.NAMESPACE / ".pending-foreign"
    temporary.write_text("SYNTHETIC_SECRET")
    git(w.checkout, "add", "--", str(Archive.NAMESPACE / temporary.name))
    turn(c)
    with pytest.raises(SyncError, match="temporary"): w.run_once()
    assert temporary.read_text() == "SYNTHETIC_SECRET"
    assert git(upstream, "rev-parse", "main") == previous


def test_partial_cross_source_export_is_completed_before_push(tmp_path, monkeypatch):
    upstream = remote(tmp_path); w = worker(tmp_path, upstream)
    c = session(w.store); turn(c)
    other = session(w.store, "beta"); turn(other, "beta")
    alpha = w.store.projection(LEARNER, "alpha")["evidence"][0]
    beta = w.store.projection(LEARNER, "beta")["evidence"][0]
    observed = deepcopy(alpha)
    saved = w.store.session(LEARNER, "alpha")
    observed.update(event_id="cross-event", sequence=saved["event_sequence"] + 1)
    observed["provenance"].update(original_source=beta["source"], original_item=beta["provenance"]["original_item"],
        origin_session_id="beta", origin_turn_id=beta["turn"]["turn_id"])
    state = deepcopy(w.store.events(LEARNER, "alpha")[-1])
    state.update(event_id="cross-checkpoint", sequence=observed["sequence"] + 1)
    saved.update(revision=2, event_sequence=state["sequence"]); state["snapshot"] = saved
    w.store.commit(LEARNER, "alpha", [observed, state], expected_revision=1)
    original = w.archive._publish
    def partial(value):
        if value["session_id"] == "beta": raise OSError("injected export interruption")
        return original(value)
    monkeypatch.setattr(w.archive, "_publish", partial)
    with pytest.raises(OSError): w.archive.export(w.store)
    with pytest.raises(ValueError, match="provenance|historical source"): w.archive.read()
    monkeypatch.setattr(w.archive, "_publish", original)
    assert {e["state"] for e in w.run_once()["events"]} == {"pushed"}
    assert len(w.archive.read()) == len(w.store.events(LEARNER, "alpha")) + len(w.store.events(LEARNER, "beta"))


def test_changed_local_branch_is_not_pushed_to_the_bound_destination(tmp_path):
    upstream = remote(tmp_path); w = worker(tmp_path, upstream); session(w.store); w.run_once()
    before = git(upstream, "rev-parse", "main")
    git(w.checkout, "switch", "-qc", "foreign")
    with pytest.raises(SyncError, match="branch changed"): w.run_once()
    assert git(upstream, "rev-parse", "main") == before
