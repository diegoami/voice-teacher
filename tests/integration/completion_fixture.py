"""Original synthetic historical position for completion checks, never personal data."""
import hashlib
from voice_teacher.progress.preview import plan_preview, _json
from voice_teacher.progress.legacy import LegacyLedger


def legacy_position(root, store, learner):
    history = root / 'synthetic-history'; history.mkdir(exist_ok=True)
    text = '# Synthetic tracker\n\n## Sentence practice\n\n| Sentence or pattern | Sessions | Evidence |\n| --- | --- | --- |\n| Synthetic greeting | A | Repeated after a model |\n'
    (history / 'tracker.md').write_text(text)
    manifest = dict(format_version=1, namespace='synthetic-completion', learner_id=learner,
        inputs=[dict(path='tracker.md', kind='tracker', sha256=hashlib.sha256(text.encode()).hexdigest())], mappings=[])
    report = plan_preview(history, manifest)
    reference = dict(source_id='historical-course', course_id='legacy', lesson_id='lesson-1')
    for row in report['records']:
        manifest['mappings'].append(dict(record_id=row['record_id'], observation_key='greeting',
            original_source=reference, practice_source=reference, assistance='repeated', correction=None, repetition_of=None))
    report = plan_preview(history, manifest)
    remote = 'https://example.invalid/private-completion.git'
    approval = dict(format_version=1, reviewed=True, approved_by='synthetic-owner',
        preview_sha256=hashlib.sha256(_json(report).encode()).hexdigest(),
        selected_observation_ids=[o['proposed_id'] for o in report['observations']], destination_remote=remote,
        course_positions=[dict(source_id='historical-course', course_id='legacy', covered_lesson_ids=['lesson-1'],
            next_lesson_id='lesson-2', evidence_record_ids=[r['record_id'] for r in report['records']])])
    ledger = LegacyLedger(store.path.parent, destination_remote=remote, private_verified=True, owner_verified=True)
    ledger.apply(history, manifest, approval)
    return ledger
