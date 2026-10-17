"""Original synthetic audio only; no external service or learner history."""
import json

import pytest
from voice_teacher.storage import Store
from voice_teacher.storage.recordings import Recordings


def test_explicit_retention_setting_is_durable_and_defaults_off(tmp_path):
    store = Store(tmp_path / 'runtime'); store.save_learner('synthetic', {})
    recording = Recordings(store)
    assert recording.policy('synthetic') == dict(retention_days=0)
    assert recording.set_policy('synthetic', 1) == dict(retention_days=1)
    assert Recordings(Store(store.path.parent)).policy('synthetic') == dict(retention_days=1)

from test_voice_pipeline import voice, submit, LEARNER, SESSION
from voice_teacher.providers.speech import SpeechError
from voice_teacher.storage import StorageError
from voice_teacher.progress.archive import Archive


def retained(tmp_path, *, days=1, answers=()):
    store, coordinator, judge, recognizer, synthesizer, pipeline = voice(tmp_path, answers=answers)
    now = [1000.0]
    recordings = Recordings(store, clock=lambda: now[0])
    pipeline.recordings = recordings
    if days: recordings.set_policy(LEARNER, days)
    return store, pipeline, recordings, now


def test_default_disabled_keeps_only_metadata_and_does_not_enable_old_retry(tmp_path):
    store, pipeline, recordings, now = retained(tmp_path, days=0)
    first = submit(pipeline)
    assert list(recordings.root.iterdir()) == []
    row = recordings.list(LEARNER, SESSION)[0]
    assert row['state'] == 'not_retained' and row['expires_at'] is None
    recordings.set_policy(LEARNER, 7)
    assert submit(pipeline) == first
    assert list(recordings.root.iterdir()) == []
    assert recordings.list(LEARNER, SESSION)[0]['state'] == 'not_retained'


def test_enabled_recording_private_retry_does_not_extend_and_expiry_preserves_history(tmp_path):
    store, pipeline, recordings, now = retained(tmp_path)
    first = submit(pipeline)
    row = recordings.list(LEARNER, SESSION)[0]
    assert row['state'] == 'retained'
    path = recordings.root / (row['recording_id']+'.bin')
    assert path.read_bytes() == b'synthetic recording'
    assert path.stat().st_mode & 0o777 == 0o600
    assert recordings.root.stat().st_mode & 0o777 == 0o700
    events = store.events(LEARNER, SESSION)
    now[0] += 600
    assert submit(pipeline) == first
    assert recordings.list(LEARNER, SESSION)[0]['expires_at'] == row['expires_at']
    now[0] = row['expires_at']
    metadata, data = recordings.read(LEARNER, SESSION, row['recording_id'])
    assert metadata['state'] == 'expired' and data is None and not path.exists()
    assert store.events(LEARNER, SESSION) == events
    assert submit(pipeline) == first  # expired audio cannot resurrect through retry
    assert not path.exists()


def test_disable_purges_now_and_reenabling_never_resurrects_old_audio(tmp_path):
    store, pipeline, recordings, now = retained(tmp_path)
    submit(pipeline)
    row = recordings.list(LEARNER, SESSION)[0]
    events = store.events(LEARNER, SESSION)
    assert recordings.set_policy(LEARNER, 0) == dict(retention_days=0)
    assert list(recordings.root.iterdir()) == []
    assert recordings.read(LEARNER, SESSION, row['recording_id'])[0]['state'] == 'deleted'
    recordings.set_policy(LEARNER, 30); submit(pipeline)
    assert list(recordings.root.iterdir()) == []
    assert store.events(LEARNER, SESSION) == events


def test_shorter_policy_bounds_old_expiry_and_longer_policy_does_not_extend_it(tmp_path):
    store, pipeline, recordings, now = retained(tmp_path, days=30)
    submit(pipeline)
    row = recordings.list(LEARNER, SESSION)[0]
    now[0] = row['created_at'] + 2*86400
    recordings.set_policy(LEARNER, 1)
    assert recordings.list(LEARNER, SESSION)[0]['state'] == 'expired'
    recordings.set_policy(LEARNER, 30)
    assert recordings.list(LEARNER, SESSION)[0]['state'] == 'expired'


def test_failed_recognition_retention_still_obeys_choice_and_expiry(tmp_path):
    store, pipeline, recordings, now = retained(tmp_path, answers=[SpeechError('SYNTHETIC_PRIVATE_PROVIDER_DETAIL')])
    events = store.events(LEARNER, SESSION)
    with pytest.raises(SpeechError): submit(pipeline)
    row = recordings.list(LEARNER, SESSION)[0]
    assert row['state'] == 'retained'
    now[0] = row['expires_at']+1
    assert recordings.cleanup(LEARNER) == dict(expired=1)
    assert not list(recordings.root.iterdir())
    assert store.events(LEARNER, SESSION) == events


@pytest.mark.parametrize('days', [True, -1, 31, 1.5, '7'])
def test_policy_rejects_invalid_duration(tmp_path, days):
    store, pipeline, recordings, now = retained(tmp_path, days=0)
    with pytest.raises(StorageError): recordings.set_policy(LEARNER, days)
    assert recordings.policy(LEARNER) == dict(retention_days=0)


def test_owner_isolation_unknown_requests_and_traversal_do_not_read_files(tmp_path):
    store, pipeline, recordings, now = retained(tmp_path)
    submit(pipeline)
    row = recordings.list(LEARNER, SESSION)[0]
    store.save_learner('other', {})
    with pytest.raises(KeyError): recordings.read('other', SESSION, row['recording_id'])
    with pytest.raises(KeyError): recordings.list('other', SESSION)
    for path in ['../outside', '/etc/passwd', 'a'*64+'/../secret']:
        assert recordings.read(LEARNER, SESSION, path) is None
    with pytest.raises(StorageError): recordings.keep(LEARNER, SESSION, 'unknown-request', b'x', 'audio/webm')
    with pytest.raises(StorageError): recordings.keep(LEARNER, SESSION, 'voice-one', b'different', 'audio/webm')


def test_orphan_and_interrupted_publication_are_cleaned_without_touching_unknown_files(tmp_path):
    store, pipeline, recordings, now = retained(tmp_path, days=0)
    orphan = recordings.root / ('a'*64+'.bin'); orphan.write_bytes(b'private orphan')
    pending = recordings.root / '.pending-synthetic'; pending.write_bytes(b'private pending')
    unknown = recordings.root / 'operator-note'; unknown.write_text('keep')
    recordings.cleanup()
    assert not orphan.exists() and not pending.exists()
    assert unknown.read_text() == 'keep'


def test_missing_or_corrupt_assets_are_unavailable_and_retry_cannot_restore_them(tmp_path):
    store, pipeline, recordings, now = retained(tmp_path)
    submit(pipeline)
    row = recordings.list(LEARNER, SESSION)[0]
    path = recordings.root / (row['recording_id']+'.bin')
    path.write_bytes(b'corrupt')
    assert recordings.read(LEARNER, SESSION, row['recording_id'])[0]['state'] == 'unavailable'
    assert not path.exists()
    submit(pipeline)
    assert not path.exists()


def test_cleanup_refuses_symlinks_without_touching_the_target(tmp_path):
    store, pipeline, recordings, now = retained(tmp_path)
    submit(pipeline)
    row = recordings.list(LEARNER, SESSION)[0]
    path = recordings.root / (row['recording_id']+'.bin')
    path.unlink()
    sentinel = tmp_path / 'sentinel'; sentinel.write_bytes(b'outside')
    path.symlink_to(sentinel)
    with pytest.raises(StorageError): recordings.read(LEARNER, SESSION, row['recording_id'])
    assert sentinel.read_bytes() == b'outside'


def test_failed_purge_keeps_disable_committed_and_retries_without_losing_history(tmp_path):
    import sqlite3
    store, pipeline, recordings, now = retained(tmp_path)
    submit(pipeline)
    events = store.events(LEARNER, SESSION)
    sentinel = tmp_path / 'sentinel'; sentinel.write_bytes(b'outside')
    stray = recordings.root / 'stray'; stray.symlink_to(sentinel)
    with pytest.raises(StorageError): recordings.set_policy(LEARNER, 0)
    assert recordings.policy(LEARNER) == dict(retention_days=0)
    with sqlite3.connect(store.path) as c:
        assert c.execute('SELECT state FROM learner_recordings').fetchall() == [('deleted',)]
    assert sentinel.read_bytes() == b'outside'
    stray.unlink(); recordings.cleanup()
    assert list(recordings.root.iterdir()) == []
    assert recordings.list(LEARNER, SESSION)[0]['state'] == 'deleted'
    assert store.events(LEARNER, SESSION) == events


def test_database_rollback_does_not_delete_retained_files(tmp_path, monkeypatch):
    from contextlib import contextmanager
    import sqlite3
    store, pipeline, recordings, now = retained(tmp_path)
    submit(pipeline)
    row = recordings.list(LEARNER, SESSION)[0]
    transaction = store._transaction
    @contextmanager
    def failed_commit():
        with transaction() as c:
            yield c
            raise sqlite3.OperationalError('synthetic commit failure')
    with monkeypatch.context() as patch:
        patch.setattr(store, '_transaction', failed_commit)
        with pytest.raises(sqlite3.OperationalError): recordings.set_policy(LEARNER, 0)
    assert recordings.policy(LEARNER) == dict(retention_days=1)
    assert recordings.read(LEARNER, SESSION, row['recording_id'])[1] == b'synthetic recording'


def test_failed_expiry_purge_keeps_expired_state_and_retry_removes_bytes(tmp_path):
    import sqlite3
    store, pipeline, recordings, now = retained(tmp_path)
    submit(pipeline)
    row = recordings.list(LEARNER, SESSION)[0]
    sentinel = tmp_path / 'sentinel'; sentinel.write_bytes(b'outside')
    stray = recordings.root / 'stray'; stray.symlink_to(sentinel)
    now[0] = row['expires_at']
    with pytest.raises(StorageError): recordings.cleanup()
    with sqlite3.connect(store.path) as c:
        assert c.execute('SELECT state FROM learner_recordings').fetchall() == [('expired',)]
    stray.unlink(); recordings.cleanup()
    assert list(recordings.root.iterdir()) == []
    assert recordings.read(LEARNER, SESSION, row['recording_id'])[1] is None
    assert sentinel.read_bytes() == b'outside'


def recording_cli(runtime):
    import subprocess
    import sys
    return subprocess.run([sys.executable, '-m', 'voice_teacher.storage.recordings',
                           '--runtime', str(runtime)], capture_output=True, text=True, timeout=15)


def test_maintenance_cli_counts_startup_expiry_and_preserves_history(tmp_path):
    import sqlite3
    store, pipeline, recordings, now = retained(tmp_path)
    submit(pipeline)
    events = store.events(LEARNER, SESSION)
    with sqlite3.connect(store.path) as c: c.execute('UPDATE learner_recordings SET expires_at=1')
    result = recording_cli(store.path.parent)
    assert result.returncode == 0 and json.loads(result.stdout) == dict(expired=1)
    assert list(recordings.root.iterdir()) == []
    assert store.events(LEARNER, SESSION) == events
    assert json.loads(recording_cli(store.path.parent).stdout) == dict(expired=0)


def test_maintenance_cli_sanitizes_database_errors(tmp_path):
    import sqlite3
    store, pipeline, recordings, now = retained(tmp_path)
    with sqlite3.connect(store.path) as c:
        c.execute('BEGIN EXCLUSIVE')
        result = recording_cli(store.path.parent)
    assert result.returncode != 0 and result.stdout == ''
    assert 'recording cleanup failed' in result.stderr
    assert 'Traceback' not in result.stderr and 'sqlite3.' not in result.stderr
    assert str(store.path.parent) not in result.stderr


def test_maintenance_cli_refuses_missing_runtime_without_creating_it(tmp_path):
    runtime = tmp_path / 'missing'
    result = recording_cli(runtime)
    assert result.returncode != 0 and not runtime.exists()


def test_archive_and_clean_restore_exclude_raw_assets_and_retention_preference(tmp_path):
    store, pipeline, recordings, now = retained(tmp_path)
    submit(pipeline)
    destination = tmp_path / 'archive'; destination.mkdir(); archive = Archive(destination)
    archive.export(store)
    assert not any(b'synthetic recording' in p.read_bytes() for p in destination.rglob('*') if p.is_file())
    restored = Store(tmp_path / 'restored')
    archive.restore(restored)
    assert store.events(LEARNER, SESSION) == restored.events(LEARNER, SESSION)
    assert Recordings(restored).policy(LEARNER) == dict(retention_days=0)
    assert Recordings(restored).list(LEARNER, SESSION) == []


def test_startup_removes_interrupted_untracked_assets(tmp_path):
    store, pipeline, recordings, now = retained(tmp_path, days=0)
    orphan = recordings.root / ('c'*64+'.bin'); orphan.write_bytes(b'private orphan')
    pending = recordings.root / '.pending-crashed'; pending.write_bytes(b'private pending')
    Recordings(Store(store.path.parent), clock=lambda: now[0])
    assert not orphan.exists() and not pending.exists()


def test_expiry_is_rechecked_after_waiting_for_read_lock(tmp_path, monkeypatch):
    store, pipeline, recordings, now = retained(tmp_path)
    submit(pipeline)
    row = recordings.list(LEARNER, SESSION)[0]
    cleanup = recordings.cleanup
    def delayed_cleanup(learner=None):
        result = cleanup(learner)
        now[0] = row['expires_at']
        return result
    monkeypatch.setattr(recordings, 'cleanup', delayed_cleanup)
    metadata, data = recordings.read(LEARNER, SESSION, row['recording_id'])
    assert metadata['state'] == 'expired' and data is None

from fastapi.testclient import TestClient
from voice_teacher.api import create_app
from contextlib import contextmanager
import hashlib
import time


def client_for(store, pipeline, recordings, *, interval=60):
    app = create_app(store, pipeline.coordinator, operator_token='synthetic-operator-'+'x'*40,
                     origin='http://teacher.test', audio=pipeline, recordings=recordings,
                     recording_cleanup_interval=interval)
    client = TestClient(app, base_url='http://teacher.test')
    def grant(learner):
        code = app.state.auth.issue_code(learner, 'synthetic')['code']
        token = client.post('/api/v1/pair', json={'code':code}).json()['token']
        return {'Authorization':'Bearer '+token}
    return app, client, grant


def test_api_retention_owner_acl_expired_status_and_public_allowlists(tmp_path):
    store, pipeline, recordings, now = retained(tmp_path, days=0)
    store.save_learner('other', {})
    app, client, grant = client_for(store, pipeline, recordings)
    owner, other = grant(LEARNER), grant('other')
    assert client.get('/api/v1/recording-retention').status_code == 401
    assert client.post('/api/v1/recording-retention', headers=owner, json={'retention_days':1,'learner_id':'other'}).status_code == 422
    assert client.post('/api/v1/recording-retention', headers=owner, json={'retention_days':True}).status_code == 422
    assert client.post('/api/v1/recording-retention', headers=owner, json={'retention_days':1}).json() == dict(retention_days=1)
    assert client.get('/api/v1/recording-retention', headers=other).json() == dict(retention_days=0)
    response = client.post('/api/v1/sessions/'+SESSION+'/audio?request_id=voice-one&expected_revision=0', headers={**owner,'Content-Type':'audio/webm'}, content=b'synthetic recording')
    assert response.status_code == 200, response.text
    rows = client.get('/api/v1/sessions/'+SESSION+'/recordings', headers=owner).json()
    row = rows[0]
    assert set(row) == {'recording_id','request_id','media_type','created_at','expires_at','state'}
    path = '/api/v1/sessions/'+SESSION+'/recordings/'+row['recording_id']
    assert client.get(path).status_code == 401
    assert client.get(path, headers=other).status_code == 404
    assert client.get('/api/v1/sessions/'+SESSION+'/recordings', headers=other).status_code == 404
    response = client.get(path, headers=owner)
    assert response.status_code == 200 and response.content == b'synthetic recording'
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['content-type'].startswith('audio/webm')
    for suffix in ['unknown', '%2e%2e%2fsecret', 'a'*64]:
        assert client.get('/api/v1/sessions/'+SESSION+'/recordings/'+suffix, headers=owner).status_code == 404
    now[0] = row['expires_at']
    response = client.get(path, headers=owner)
    assert response.status_code == 410 and response.json()['error']['message'] == 'Recording expired'
    assert str(store.path.parent) not in response.text
    assert client.post('/api/v1/recording-retention/cleanup', headers=owner, json={'learner_id':'other'}).status_code == 422
    assert client.post('/api/v1/recording-retention/cleanup', headers=owner, json={}).status_code == 200


def test_provider_errors_and_routine_logs_exclude_recordings_credentials_and_profiles(tmp_path, caplog):
    import logging
    caplog.set_level(logging.INFO)
    store, pipeline, recordings, now = retained(tmp_path, answers=[SpeechError('SYNTHETIC_PRIVATE_API_KEY')])
    store.save_learner(LEARNER, {'private_note': 'SYNTHETIC_PRIVATE_PROFILE'})
    app, client, grant = client_for(store, pipeline, recordings)
    owner = grant(LEARNER)
    raw = b'SYNTHETIC_PRIVATE_AUDIO_BYTES'
    response = client.post('/api/v1/sessions/'+SESSION+'/audio?request_id=voice-one&expected_revision=0', headers={**owner,'Content-Type':'audio/webm'}, content=raw)
    assert response.status_code == 502
    combined = response.text + caplog.text
    for private in ['SYNTHETIC_PRIVATE_API_KEY',raw.decode(),str(store.path.parent),'SYNTHETIC_PRIVATE_PROFILE']:
        assert private not in combined


def test_background_cleanup_expires_idle_assets_and_stops_with_app(tmp_path):
    store, pipeline, recordings, now = retained(tmp_path)
    submit(pipeline)
    row = recordings.list(LEARNER, SESSION)[0]
    path = recordings.root / (row['recording_id']+'.bin')
    before = store.events(LEARNER, SESSION)
    app, client, grant = client_for(store, pipeline, recordings, interval=.05)
    with client:
        now[0] = row['expires_at']+1
        deadline = time.monotonic()+3
        while path.exists() and time.monotonic() < deadline: time.sleep(.01)
        assert not path.exists()  # no API read/cleanup request triggered expiry
    assert store.events(LEARNER, SESSION) == before
    assert recordings.list(LEARNER, SESSION)[0]['state'] == 'expired'


def test_atomic_recording_publication_failure_leaves_no_asset_or_metadata(tmp_path, monkeypatch):
    store, pipeline, recordings, now = retained(tmp_path)
    data = b'original synthetic recording for publication rollback'
    body = dict(sha256=hashlib.sha256(data).hexdigest(),media_type='audio/webm',language='uk',expected_revision=0)
    with store._transaction() as c:
        c.execute("INSERT INTO speech_requests(learner_id,session_id,request_id,input_json,status) VALUES (?,?,?,?,'accepted')", (LEARNER,SESSION,'rollback',json.dumps(body)))
    original = store._transaction
    @contextmanager
    def fail_before_commit():
        with original() as c:
            yield c
            raise RuntimeError('synthetic failure before commit')
    monkeypatch.setattr(store, '_transaction', fail_before_commit)
    with pytest.raises(RuntimeError): recordings.keep(LEARNER,SESSION,'rollback',data,'audio/webm')
    assert not list(recordings.root.iterdir())
    with store._connection() as c: assert c.execute('SELECT count(*) FROM learner_recordings').fetchone()[0] == 0


def test_schema9_migration_rolls_back_without_losing_completion_or_practice(tmp_path, monkeypatch):
    import sqlite3
    import voice_teacher.storage.sqlite as implementation
    store, pipeline, recordings, now = retained(tmp_path)
    before = store.events(LEARNER, SESSION)
    from voice_teacher.content.registry import SourceSnapshot
    from voice_teacher.progress.lesson_completion import record, all_decisions
    from schemas.validate import canonical_json
    snapshot = store.session(LEARNER, SESSION)
    source = SourceSnapshot('privacy-version', canonical_json(dict(curriculum=snapshot['curriculum_snapshot'], provenance=dict(commit=None, dirty=True))))
    reference = snapshot['source']
    record(store, LEARNER, dict(request_id='complete-before-migration', source_id=reference['source_id'], course_id=reference['course_id'], lesson_id=reference['lesson_id'], version_id=source.version_id, expected_revision=0, completed=True), source)
    choices = all_decisions(store)
    with sqlite3.connect(store.path) as c:
        c.execute('DROP TABLE learner_recordings'); c.execute('DROP TABLE recording_preferences');c.execute('PRAGMA user_version=8')
    original = implementation.V9
    monkeypatch.setattr(implementation, 'V9', (*original,'SELECT synthetic_failed_migration()'))
    with pytest.raises(sqlite3.OperationalError): Store(store.path.parent)
    with sqlite3.connect(store.path) as c:
        assert c.execute('PRAGMA user_version').fetchone()[0] == 8
        assert c.execute("SELECT name FROM sqlite_master WHERE name='recording_preferences'").fetchone() is None
    monkeypatch.setattr(implementation, 'V9', original)
    restored = Store(store.path.parent)
    assert restored.events(LEARNER, SESSION) == before
    assert all_decisions(restored) == choices


def test_recording_cleanup_does_not_remove_teacher_audio(tmp_path):
    store, pipeline, recordings, now = retained(tmp_path)
    submit(pipeline)
    teacher = {p.name:p.read_bytes() for p in pipeline.cache.glob('*.mp3')}
    assert teacher
    recordings.set_policy(LEARNER, 0)
    recordings.cleanup()
    assert {p.name:p.read_bytes() for p in pipeline.cache.glob('*.mp3')} == teacher


def test_remote_sync_refuses_unverified_destination_before_any_initialization(tmp_path):
    from voice_teacher.progress.git_sync import GitSync, SyncError
    store = Store(tmp_path / 'runtime')
    for private, owner in [(False,True),(True,False),(False,False)]:
        checkout = tmp_path / ('unverified-'+str(private)+str(owner))
        with pytest.raises(SyncError, match='verify'):
            GitSync(store, checkout, 'https://example.invalid/private-progress.git', private_verified=private, owner_verified=owner)
        assert not checkout.exists()
