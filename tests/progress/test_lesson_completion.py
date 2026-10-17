"""Original synthetic choices; no learner data or provider calls."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from schemas.validate import canonical_json
from voice_teacher.content.registry import SourceSnapshot
from voice_teacher.storage import Store
from voice_teacher.progress.lesson_completion import record


LEARNER = "completion-learner"


def source(name="synthetic", revision=1):
    raw = json.loads((Path(__file__).parents[1] / "contracts/fixtures/repetition.json").read_text())
    raw["source_id"] = name
    raw["courses"][0]["items"][0]["item_revision"] = revision
    first = raw["courses"][0]["lessons"][0]
    second = deepcopy(first)
    second.update(lesson_id="lesson-2", title="Second lesson")
    raw["courses"][0]["lessons"].append(second)
    return SourceSnapshot("version-"+str(revision), canonical_json(dict(curriculum=raw, provenance=dict(commit=None, dirty=True))))


def request(snap, *, identity="complete-1", lesson="lesson-1", completed=True, revision=0):
    return dict(request_id=identity, source_id=snap.curriculum["source_id"], course_id="basics",
                lesson_id=lesson, version_id=snap.version_id, expected_revision=revision, completed=completed)


def test_can_complete_unpractised_lesson_without_fake_session_or_evidence(tmp_path):
    store = Store(tmp_path / "runtime")
    store.save_learner(LEARNER, {"level": "A2"})
    result = record(store, LEARNER, request(source()), source())
    assert result["completed"] is True and result["revision"] == 1
    with store._connection() as c:
        assert c.execute("SELECT count(*) FROM events").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0

from voice_teacher.storage import EventConflict, RevisionConflict
from voice_teacher.progress.lesson_completion import all_decisions, find_request
from voice_teacher.progress.views import summary
from voice_teacher.progress.archive import Archive, ArchiveError
from voice_teacher.content.registry import SourceRegistry, SourceSpec
from voice_teacher.practice.coordinator import Coordinator
from fastapi.testclient import TestClient
from voice_teacher.api import create_app


def setup_store(tmp_path):
    store = Store(tmp_path / 'runtime')
    store.save_learner(LEARNER, {'level': 'A2'})
    store.save_learner('other', {'level': 'B1'})
    root = tmp_path / 'content'; root.mkdir()
    (root / 'voice-teacher.json').write_text(canonical_json(source().curriculum))
    registry = SourceRegistry(store)
    registry.register(SourceSpec('synthetic', 'Synthetic', str(root), allow_dirty=True))
    registry.refresh('synthetic')
    return store, registry.active('synthetic')


def test_lost_response_replay_restart_and_reopen_preserve_item_coverage(tmp_path):
    store, snap = setup_store(tmp_path)
    original = summary(store, LEARNER)
    intent = request(snap)
    first = record(store, LEARNER, intent, snap)
    reopened_store = Store(store.path.parent)
    assert find_request(reopened_store, LEARNER, intent) == first
    assert record(reopened_store, LEARNER, intent, source(revision=2)) == first
    course = summary(store, LEARNER)['courses'][0]
    assert course['next_lesson_id'] == 'lesson-2' and course['covered_items'] == 0
    assert original['courses'][0]['next_lesson_id'] == 'lesson-1'
    record(store, LEARNER, request(snap, identity='reopen', completed=False, revision=1), snap)
    course = summary(store, LEARNER)['courses'][0]
    assert course['next_lesson_id'] == 'lesson-1' and course['covered_items'] == 0
    assert course['lessons'][0]['learner_completed'] is False
    assert len(all_decisions(store)) == 2


def test_conflicting_retry_and_stale_revision_do_not_write(tmp_path):
    store, snap = setup_store(tmp_path)
    record(store, LEARNER, request(snap), snap)
    with pytest.raises(EventConflict): record(store, LEARNER, request(snap, completed=False), snap)
    with pytest.raises(RevisionConflict): record(store, LEARNER, request(snap, identity='stale'), snap)
    with pytest.raises(RevisionConflict): record(store, LEARNER, request(source(revision=2), identity='changed'), snap)
    assert len(all_decisions(store)) == 1


def test_learner_source_course_and_content_revision_are_separate(tmp_path):
    store, snap = setup_store(tmp_path)
    record(store, LEARNER, request(snap), snap)
    assert summary(store, 'other')['courses'][0]['next_lesson_id'] == 'lesson-1'
    record(store, 'other', request(snap), snap)
    changed = source(revision=2)
    record(store, LEARNER, request(changed, identity='changed'), changed)
    other_source = source('different')
    record(store, LEARNER, request(other_source, identity='different'), other_source)
    raw = deepcopy(snap.curriculum)
    raw['courses'][0]['course_id'] = 'advanced'
    second_course = SourceSnapshot('advanced-version', canonical_json(dict(curriculum=raw, provenance=dict(commit=None, dirty=True))))
    intent = request(second_course, identity='advanced'); intent['course_id'] = 'advanced'
    record(store, LEARNER, intent, second_course)
    assert len(all_decisions(store, LEARNER)) == 4
    assert len(all_decisions(store, 'other')) == 1


def test_archive_roundtrip_and_retry_restore_decisions_without_sessions(tmp_path):
    store, snap = setup_store(tmp_path)
    first = record(store, LEARNER, request(snap), snap)
    root = tmp_path / 'archive'; root.mkdir(); archive = Archive(root)
    archive.export(store)
    record(store, LEARNER, request(snap, identity='reopen', completed=False, revision=1), snap)
    archive.export(store)
    assert len(archive.read_decisions()) == 2
    restored = Store(tmp_path / 'restored')
    assert archive.restore(restored) == 2
    assert archive.restore(restored) == 0
    assert all_decisions(restored) == all_decisions(store)
    assert find_request(restored, LEARNER, request(snap)) == first
    assert summary(restored, LEARNER)['courses'][0]['next_lesson_id'] == 'lesson-1'
    with restored._connection() as c:
        assert c.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0


def test_authenticated_api_is_owner_bound_and_cached_before_source_lookup(tmp_path):
    store, snap = setup_store(tmp_path)
    def forbidden(*a): raise AssertionError('completion must not call providers')
    app = create_app(store, Coordinator(store, forbidden), operator_token='x'*48, origin='http://teacher.test')
    client = TestClient(app, base_url='http://teacher.test')
    def headers(learner):
        code = app.state.auth.issue_code(learner, 'synthetic')['code']
        token = client.post('/api/v1/pair', json={'code':code}).json()['token']
        return {'Authorization':'Bearer '+token}
    owner, other = headers(LEARNER), headers('other')
    intent = request(snap)
    assert client.post('/api/v1/lesson-completions', json=intent).status_code == 401
    response = client.post('/api/v1/lesson-completions', headers=owner, json=intent)
    assert response.status_code == 200, response.text
    assert client.get('/api/v1/progress', headers=owner).json()['courses'][0]['next_lesson_id'] == 'lesson-2'
    assert client.get('/api/v1/progress', headers=other).json()['courses'][0]['next_lesson_id'] == 'lesson-1'
    assert client.post('/api/v1/lesson-completions', headers=other, json=intent).status_code == 200
    with store._transaction() as c: c.execute('DELETE FROM source_active')
    assert client.post('/api/v1/lesson-completions', headers=owner, json=intent).json() == response.json()
    assert client.post('/api/v1/lesson-completions', headers=owner, json={**intent,'learner_id':'other'}).status_code == 422


def test_git_sync_restores_completion_and_reopen_then_keeps_retry_idempotent(tmp_path):
    from test_git_sync import remote, worker, git
    store, snap = setup_store(tmp_path)
    upstream = remote(tmp_path)
    w = worker(tmp_path, upstream, store=store)
    first = record(store, LEARNER, request(snap), snap)
    assert w.status()['lesson_decisions'][0]['state'] == 'locally_saved'
    status = w.run_once()
    assert status['lesson_decisions'][0]['state'] == 'pushed'
    commit = git(upstream, 'rev-parse', 'main')
    w.run_once()
    assert git(upstream, 'rev-parse', 'main') == commit
    restored = worker(tmp_path, upstream, name='restored')
    restored.run_once()
    assert find_request(restored.store, LEARNER, request(snap)) == first
    record(store, LEARNER, request(snap, identity='reopen', completed=False, revision=1), snap)
    w.run_once(); restored.run_once()
    assert all_decisions(restored.store) == all_decisions(store)
    assert summary(restored.store, LEARNER)['courses'][0]['next_lesson_id'] == 'lesson-1'


def test_v8_failure_rolls_back_and_preserves_previous_practice(tmp_path, monkeypatch):
    import sqlite3
    import voice_teacher.storage.sqlite as implementation
    from test_roundtrip import session, LEARNER as PRACTICE_LEARNER
    store = Store(tmp_path / 'runtime'); session(store)
    events = store.events(PRACTICE_LEARNER, 'alpha')
    with sqlite3.connect(store.path) as c:
        c.execute('DROP TABLE lesson_decisions'); c.execute('PRAGMA user_version=7')
    original = implementation.V8
    monkeypatch.setattr(implementation, 'V8', (*original, 'SELECT synthetic_failure()'))
    with pytest.raises(sqlite3.OperationalError): Store(store.path.parent)
    with sqlite3.connect(store.path) as c:
        assert c.execute('PRAGMA user_version').fetchone()[0] == 7
        assert c.execute("SELECT name FROM sqlite_master WHERE name='lesson_decisions'").fetchone() is None
    monkeypatch.setattr(implementation, 'V8', original)
    assert Store(store.path.parent).events(PRACTICE_LEARNER, 'alpha') == events


def test_manual_completion_preserves_practice_evidence_and_weak_queue(tmp_path):
    from test_views import repetition
    from test_roundtrip import LEARNER as PRACTICE_LEARNER, turn
    from voice_teacher.practice.repetition import weak_queue
    store = Store(tmp_path / 'runtime')
    coordinator, plan = repetition(store, 'practice', 'synthetic')
    for _ in range(2): turn(coordinator, 'practice', 'banana orange pear apple plum')
    snapshot = store.session(PRACTICE_LEARNER, 'practice')
    snap = SourceSnapshot('version-original', canonical_json(dict(curriculum=snapshot['curriculum_snapshot'], provenance=dict(commit=None, dirty=True))))
    before = store.events(PRACTICE_LEARNER, 'practice')
    queue = weak_queue(store, PRACTICE_LEARNER)
    assert queue, 'test must preserve an actual weak expression'
    coverage = summary(store, PRACTICE_LEARNER)['courses'][0]['covered_items']
    record(store, PRACTICE_LEARNER, request(snap), snap)
    assert store.events(PRACTICE_LEARNER, 'practice') == before
    assert weak_queue(store, PRACTICE_LEARNER) == queue
    assert summary(store, PRACTICE_LEARNER)['courses'][0]['covered_items'] == coverage


def test_concurrent_completion_accepts_one_revision_and_retry_returns_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store, snap = setup_store(tmp_path)
    def apply(identity):
        try: return record(store, LEARNER, request(snap, identity=identity), snap)
        except RevisionConflict: return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(apply, ['one', 'two']))
    assert sum(r is not None for r in results) == 1
    winner = next(r for r in results if r is not None)
    assert record(store, LEARNER, request(snap, identity=winner['request_id']), snap) == winner
    assert len(all_decisions(store)) == 1


@pytest.mark.parametrize('damage', ['missing_prefix', 'conflicting_id', 'owner', 'hash'])
def test_invalid_decision_archive_cannot_partially_restore(tmp_path, damage):
    import hashlib
    store, snap = setup_store(tmp_path)
    record(store, LEARNER, request(snap), snap)
    record(store, LEARNER, request(snap, identity='reopen', completed=False, revision=1), snap)
    root = tmp_path / 'archive'; root.mkdir(); archive = Archive(root); archive.export(store)
    path = next((root / archive.NAMESPACE).glob('*.json'))
    payload = json.loads(path.read_bytes())
    if damage == 'missing_prefix': payload['decisions'] = payload['decisions'][1:]
    elif damage == 'conflicting_id':
        altered = deepcopy(payload['decisions'][0]); altered['request']['completed'] = False
        payload['decisions'].append(altered)
    elif damage == 'owner': payload['learner_id'] = 'other'
    else: payload['decisions'][0]['source']['revision']['content_sha256'] = '0'*64
    path.unlink()
    data = canonical_json(payload).encode()
    (root / archive.NAMESPACE / (hashlib.sha256(data).hexdigest()+'.json')).write_bytes(data)
    target = Store(tmp_path / 'restored')
    with pytest.raises((ArchiveError, ValueError, EventConflict)): archive.restore(target)
    assert all_decisions(target) == []
    with target._connection() as c: assert c.execute('SELECT count(*) FROM learners').fetchone()[0] == 0


def test_imported_position_is_allowlisted_owner_bound_and_unchanged(tmp_path):
    import importlib.util
    path = Path(__file__).parents[1] / 'integration/completion_fixture.py'
    spec = importlib.util.spec_from_file_location('synthetic_completion_fixture', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    store, snap = setup_store(tmp_path)
    legacy = module.legacy_position(tmp_path, store, LEARNER)
    before = legacy.positions(LEARNER), legacy.history(LEARNER), legacy.batches()
    record(store, LEARNER, request(snap), snap)
    positions = summary(store, LEARNER, legacy=legacy)['legacy_positions']
    assert positions == [dict(source_id='historical-course', course_id='legacy', covered_lesson_ids=['lesson-1'], next_lesson_id='lesson-2')]
    assert summary(store, 'other', legacy=legacy)['legacy_positions'] == []
    assert (legacy.positions(LEARNER), legacy.history(LEARNER), legacy.batches()) == before
