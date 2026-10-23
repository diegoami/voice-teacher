"""Owner-scoped views of immutable inputs already retained by reviewed imports.

No source files are opened and no records become new practice observations.
"""
from contextlib import closing
import datetime
import hashlib
import json
import re
import sqlite3

from .legacy import _validated


def _description(source):
    title = next((line.lstrip('#').strip() for line in source['raw'].splitlines()
                  if re.match(r'^#{1,6}\s+', line)), source['path'].rsplit('/', 1)[-1])
    kind = source['kind']
    if kind == 'session':
        if re.search(r'\btranscript\b', title, re.I):
            kind = 'transcript'
        elif re.search(r'\b(summary|notes)\b', title, re.I):
            kind = 'summary'
        else:
            kind = 'session_record'
    date = None
    match = re.search(r'(?:^|/)(\d{4}-\d{2}-\d{2})(?:-|/|\.)', source['path'])
    if match:
        try:
            date = datetime.date.fromisoformat(match[1]).isoformat()
        except ValueError:
            pass
    return title, kind, date


def records(ledger, learner, archive_id=None):
    """Project only the authenticated owner's retained batches, keyed by content.

    Detail IDs are opaque hashes, never filesystem lookup parameters. Each reviewed import snapshot remains distinct, including when
    an identical source receives different mappings in a later reviewed import. The whole source is retained, including unresolved context.
    """
    if ledger is None:
        return []
    if ledger.path.is_symlink():
        raise ValueError('legacy database symlinks refused')
    with closing(sqlite3.connect(ledger.path.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
        ledger._version(db)
        batches = [(r[0], json.loads(r[1])) for r in db.execute(
            'SELECT import_id, body_json FROM imports WHERE learner_id=? ORDER BY import_id', (learner,))]
    result = {}
    for import_id, batch in batches:
        identity, _, observations = _validated(batch)
        if identity != import_id or batch['report']['learner_id'] != learner:
            raise ValueError('retained import integrity mismatch')
        report = batch['report']
        for source in report['inputs']:
            key = hashlib.sha256(json.dumps([import_id, source['kind'], source['path'], source['sha256']],
                                           ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
            if archive_id is not None and archive_id != key:
                continue
            if key not in result:
                title, kind, date = _description(source)
                rows = [r for r in report['records'] if r['path'] == source['path']]
                result[key] = dict(archive_id=key, title=title, record_kind=kind,
                    source_label=source['path'], source_date=date, source_sha256=source['sha256'],
                    counts={status: sum(r['status'] == status for r in rows)
                            for status in ('proposed', 'unresolved', 'conflict')},
                    imports=[], supporting_groups=[], text=source['raw'])
            entry = result[key]
            entry['imports'].append(import_id)
            record_ids = {r['record_id'] for r in report['records'] if r['path'] == source['path']}
            for observation in observations:
                supporting = sorted(record_ids.intersection(observation['record_ids']))
                if supporting:
                    entry['supporting_groups'].append(dict(import_id=import_id,
                        observation_id=observation['proposed_id'], record_ids=supporting,
                        original_source=observation['original_source'],
                        practice_source=observation['practice_source']))
    values = sorted(result.values(), key=lambda row: (row['source_date'] or '', row['title'], row['archive_id']), reverse=True)
    if archive_id is None:
        return [{k: v for k, v in row.items() if k not in ('text', 'supporting_groups')} for row in values]
    return values
