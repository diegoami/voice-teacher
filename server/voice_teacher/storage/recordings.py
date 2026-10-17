"""Optional private recordings. Cleanup never rewrites practice history."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
import time

from schemas.validate import canonical_json
from .sqlite import StorageError, _id

MEDIA = frozenset({'audio/webm', 'audio/ogg', 'audio/wav', 'audio/mp4'})


def identity(learner, session, request):
    return hashlib.sha256(canonical_json([learner, session, request]).encode()).hexdigest()


class Recordings:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock
        self.root = store.path.parent / 'learner-recordings'
        if self.root.is_symlink(): raise StorageError('recording directory symlink refused')
        self.root.mkdir(mode=0o700, exist_ok=True)
        if self.root.stat().st_mode & 0o077: raise StorageError('recording directory must be private')
        self.startup_cleanup = self.cleanup()

    @contextmanager
    def _locked(self):
        # Thread and OS locks coordinate the server and explicit cleanup command.
        from ..practice.coordinator import _lock
        with _lock(self.store, '@recordings', 'retention'):
            if self.root.is_symlink(): raise StorageError('recording directory symlink refused')
            lock = self.store.path.parent / 'recording-retention.lock'
            fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                os.close(fd)

    def _now(self):
        value = self.clock()
        if type(value) not in (int, float) or not math.isfinite(value): raise StorageError('invalid retention clock')
        return value

    def _path(self, recording):
        if not isinstance(recording, str) or not re.fullmatch('[a-f0-9]{64}', recording): raise StorageError('invalid recording identity')
        if self.root.is_symlink(): raise StorageError('recording directory symlink refused')
        path = self.root / (recording + '.bin')
        if path.is_symlink(): raise StorageError('recording file symlink refused')
        return path

    def _remove(self, recording):
        path = self._path(recording)
        try: path.unlink()
        except FileNotFoundError: pass

    def _fsync(self):
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(fd)
        finally: os.close(fd)

    def policy(self, learner):
        self.store.learner(_id(learner))
        with self.store._connection() as c:
            row = c.execute('SELECT retention_days FROM recording_preferences WHERE learner_id=?', (learner,)).fetchone()
        return dict(retention_days=row[0] if row else 0)

    def set_policy(self, learner, days):
        if type(days) is not int or not 0 <= days <= 30: raise StorageError('retention days must be 0 to 30')
        self.store.learner(_id(learner))
        with self._locked():
            with self.store._transaction() as c:
                c.execute('INSERT INTO recording_preferences VALUES (?,?) ON CONFLICT(learner_id) DO UPDATE SET retention_days=excluded.retention_days', (learner, days))
                if days == 0:
                    c.execute("UPDATE learner_recordings SET state='deleted' WHERE learner_id=? AND state='retained'", (learner,))
                else:
                    c.execute("UPDATE learner_recordings SET expires_at=min(expires_at,created_at+?) WHERE learner_id=? AND state='retained'", (days*86400, learner))
                self._expire(c, self._now())
            self._purge()
        return dict(retention_days=days)

    def keep(self, learner, session, request, data, media_type):
        learner, session, request = (_id(v) for v in (learner, session, request))
        if media_type not in MEDIA or not isinstance(data, bytes) or not 0 < len(data) <= 8*1024*1024: raise StorageError('invalid retained recording')
        digest = hashlib.sha256(data).hexdigest()
        recording = identity(learner, session, request)
        created = False
        self.cleanup()
        with self._locked():
            try:
                with self.store._transaction() as c:
                    accepted = c.execute('SELECT input_json FROM speech_requests WHERE learner_id=? AND session_id=? AND request_id=?', (learner, session, request)).fetchone()
                    if accepted is None: raise StorageError('recording request not accepted')
                    bound = json.loads(accepted[0])
                    if bound.get('sha256') != digest or bound.get('media_type') != media_type: raise StorageError('recording intent mismatch')
                    old = c.execute('SELECT recording_id FROM learner_recordings WHERE recording_id=?', (recording,)).fetchone()
                    if old is not None: return recording  # never extend or resurrect on retry
                    setting = c.execute('SELECT retention_days FROM recording_preferences WHERE learner_id=?', (learner,)).fetchone()
                    days = setting[0] if setting else 0
                    now = self._now()
                    c.execute('INSERT INTO learner_recordings VALUES (?,?,?,?,?,?,?,?,?)',
                        (recording, learner, session, request, digest, media_type, now, now+days*86400 if days else None, 'retained' if days else 'not_retained'))
                    if days:
                        path = self._path(recording)
                        fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=self.root)
                        try:
                            with os.fdopen(fd, 'wb') as stream:
                                stream.write(data); stream.flush(); os.fsync(stream.fileno())
                            os.replace(temporary, path); created = True; self._fsync()
                        finally:
                            if os.path.exists(temporary): os.unlink(temporary)
            except Exception:
                if created: self._remove(recording); self._fsync()
                raise
        return recording

    def _expire(self, c, now):
        return c.execute("UPDATE learner_recordings SET state='expired' WHERE state='retained' AND expires_at<=?", (now,)).rowcount

    def _purge(self):
        # Caller holds the recording lock. Persist denial/disable BEFORE deleting
        # bytes: rollback cannot undo an unlink. A failed purge stays denied and
        # a later cleanup retries all managed files no longer marked retained.
        with self.store._connection() as c:
            self._orphans(c)
        self._fsync()

    def cleanup(self, learner=None):
        if learner is not None: self.store.learner(_id(learner))
        with self._locked():
            with self.store._transaction() as c:
                # Expiry is global; the count exposed to a client is owner-only.
                now = self._now()
                before = c.execute("SELECT count(*) FROM learner_recordings WHERE state='retained' AND expires_at<=?" + (' AND learner_id=?' if learner else ''), (now, learner) if learner else (now,)).fetchone()[0]
                self._expire(c, now)
            self._purge()
        return dict(expired=before)

    def _orphans(self, c):
        live = {r[0] for r in c.execute("SELECT recording_id FROM learner_recordings WHERE state='retained'")}
        for path in self.root.iterdir():
            if path.is_symlink(): raise StorageError('recording symlink refused during cleanup')
            if path.name.startswith('.pending-') or (re.fullmatch('[a-f0-9]{64}\\.bin', path.name) and path.stem not in live):
                if not path.is_file(): raise StorageError('unexpected recording artifact')
                path.unlink()

    @staticmethod
    def _public(row):
        return {k: row[k] for k in ('recording_id','request_id','media_type','created_at','expires_at','state')}

    def list(self, learner, session):
        self.store.session(learner, session)
        self.cleanup(learner)
        with self._locked():
            with self.store._transaction() as c:
                self._expire(c, self._now())
                rows = c.execute('SELECT * FROM learner_recordings WHERE learner_id=? AND session_id=? ORDER BY created_at,recording_id', (learner, session)).fetchall()
                result = []
                for row in rows:
                    value = self._public(row)
                    if row['state'] == 'retained' and not self._path(row['recording_id']).is_file():
                        c.execute("UPDATE learner_recordings SET state='unavailable' WHERE recording_id=?", (row['recording_id'],)); value['state'] = 'unavailable'
                    result.append(value)
            self._purge()
        return result

    def read(self, learner, session, recording):
        self.store.session(learner, session)
        if not isinstance(recording, str) or not re.fullmatch('[a-f0-9]{64}', recording): return None
        self.cleanup(learner)
        with self._locked():
            with self.store._transaction() as c:
                self._expire(c, self._now())
                row = c.execute('SELECT * FROM learner_recordings WHERE learner_id=? AND session_id=? AND recording_id=?', (learner, session, recording)).fetchone()
                result = None
                if row is not None:
                    value = self._public(row)
                    data = None
                    if row['state'] == 'retained':
                        path = self._path(recording)
                        try:
                            with path.open('rb') as stream: data = stream.read(8*1024*1024+1)
                        except FileNotFoundError: data = b''
                        if hashlib.sha256(data).hexdigest() != row['sha256']:
                            c.execute("UPDATE learner_recordings SET state='unavailable' WHERE recording_id=?", (recording,))
                            value['state'] = 'unavailable'; data = None
                    result = value, data
            self._purge()
        return result


def main():
    import argparse
    from pathlib import Path
    from . import Store
    parser = argparse.ArgumentParser(description='Expire private learner recordings without changing progress')
    parser.add_argument('--runtime', required=True)
    args = parser.parse_args()
    try:
        database = Path(args.runtime).expanduser() / 'voice-teacher.sqlite'
        if database.is_symlink() or not database.is_file(): raise StorageError('runtime database required')
        result = Recordings(Store(args.runtime)).startup_cleanup
    except (ValueError, OSError, sqlite3.Error): parser.error('recording cleanup failed; inspect private configuration')
    print(json.dumps(result))


if __name__ == '__main__': main()
