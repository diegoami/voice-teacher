"""Only synthetic retained history; no learner repositories or provider calls."""
import hashlib
import json

from fastapi.testclient import TestClient
from test_api import system, bearer, OPERATOR, ORIGIN
from voice_teacher.api import create_app
from voice_teacher.progress.legacy import LegacyLedger
from voice_teacher.progress.preview import plan_preview, _json


def archived(s, tmp_path):
    root = tmp_path / "originals"
    root.mkdir()
    content = {
        "2026-01-02-session-A.md": ("session", "# Transcript — Synthetic A\n\nLearner: <script>synthetic</script>\nTeacher: Sample reply\n"),
        "notes.md": ("session", "# Summary — Synthetic B\n\nOnly a summary exists.\n"),
        "tracker.md": ("tracker", "# Synthetic tracker\n\nSample coverage declaration\n"),
    }
    inputs = []
    for name, (kind, raw) in content.items():
        (root / name).write_text(raw)
        inputs.append(dict(path=name, kind=kind, sha256=hashlib.sha256(raw.encode()).hexdigest()))
    manifest = dict(format_version=1, namespace="synthetic-archive", learner_id="alice", inputs=inputs, mappings=[])
    report = plan_preview(root, manifest)
    manifest['mappings'] = [dict(record_id=report['records'][0]['record_id'], observation_key='synthetic-group',
        original_source=dict(source_id='source',course_id='course',lesson_id='A'),
        practice_source=dict(source_id='source',course_id='course',lesson_id='A'),
        assistance=None, correction=None, repetition_of=None)]
    report = plan_preview(root, manifest)
    approval = dict(format_version=1, reviewed=True, approved_by="synthetic-owner",
        preview_sha256=hashlib.sha256(_json(report).encode()).hexdigest(),
        selected_observation_ids=[o['proposed_id'] for o in report['observations']],course_positions=[],
        destination_remote="https://example.invalid/private.git")
    ledger = LegacyLedger(s['store'].path.parent, destination_remote=approval['destination_remote'], private_verified=True, owner_verified=True)
    ledger.apply(root, manifest, approval)
    app = create_app(s['store'], s['coordinator'], operator_token=OPERATOR, origin=ORIGIN,
        clock=lambda:s['now'][0],legacy=ledger)
    return TestClient(app, base_url=ORIGIN), ledger, root, content


def test_retained_archive_is_owner_only_and_survives_missing_originals(system, tmp_path):
    s = system
    client, ledger, root, content = archived(s, tmp_path)
    headers = bearer(s['alice']['token'])
    before = ledger.batches()
    response = client.get('/api/v1/legacy-history',headers=headers)
    assert response.status_code == 200
    rows = response.json()['records']
    assert len(rows) == 3
    session = next(r for r in rows if r['record_kind']=='transcript')
    summary = next(r for r in rows if r['record_kind']=='summary')
    assert session['source_date'] == '2026-01-02'
    assert summary['source_date'] is None
    assert 'text' not in session and str(root) not in response.text
    assert any(r['record_kind']=='tracker' for r in rows)
    assert sum(r['counts']['unresolved'] for r in rows)==2
    for name in content:
        (root/name).unlink()
    detail = client.get('/api/v1/legacy-history/'+session['archive_id'],headers=headers)
    assert detail.status_code==200
    assert detail.json()['text']==content['2026-01-02-session-A.md'][1]
    assert '<script>' in detail.json()['text']
    assert detail.json()['source_sha256']==hashlib.sha256(detail.json()['text'].encode()).hexdigest()
    assert detail.json()['supporting_groups']
    assert ledger.batches()==before
    with s['store']._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0]==0
    assert client.get('/api/v1/legacy-history').status_code==401
    bob=bearer(s['bob']['token'])
    assert client.get('/api/v1/legacy-history',headers=bob).json()['records']==[]
    assert client.get('/api/v1/legacy-history/'+session['archive_id'],headers=bob).status_code==404
    assert client.get('/api/v1/legacy-history/'+'0'*64,headers=headers).status_code==404
    assert client.get('/api/v1/legacy-history/not-a-path',headers=headers).status_code==404


def test_unconfigured_and_corrupt_archive_are_truthful_and_sanitized(system,tmp_path):
    s=system;headers=bearer(s['alice']['token'])
    empty=s['client'].get('/api/v1/legacy-history',headers=headers)
    assert empty.status_code==200 and empty.json()==dict(configured=False,records=[])
    assert s['client'].get('/api/v1/legacy-history/'+'0'*64,headers=headers).status_code==404
    client, ledger, root, content=archived(s,tmp_path)
    with ledger._transaction() as db:
        batch=ledger.batches()[0]
        batch['report']['inputs'][0]['raw']='PRIVATE CORRUPT CONTENT'
        db.execute('UPDATE imports SET body_json=?', (json.dumps(batch),))
    response=client.get('/api/v1/legacy-history',headers=headers)
    assert response.status_code==503
    assert 'PRIVATE CORRUPT CONTENT' not in response.text and str(root) not in response.text


def test_missing_ledger_is_unavailable_without_recreating_database(system,tmp_path):
    client, ledger, _, _ = archived(system,tmp_path)
    ledger.path.unlink()
    result = client.get('/api/v1/legacy-history',headers=bearer(system['alice']['token']))
    assert result.status_code == 503
    assert not ledger.path.exists()
