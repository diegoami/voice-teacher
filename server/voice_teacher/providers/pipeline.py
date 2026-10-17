"""Durable recognition and owner-bound, retryable teacher audio delivery."""
from dataclasses import asdict
import hashlib
import json
import os
import re
import tempfile

from schemas.validate import canonical_json
from . import Audio
from ..practice.coordinator import _lock
from ..storage import RevisionConflict
from ..storage.sqlite import _id
from ..storage.work import RequestConflict
from .speech import Recognition, SpeechError


def _hash(data): return hashlib.sha256(data).hexdigest()


class VoicePipeline:
    def __init__(self, store, coordinator, recognizer, synthesizer, *, recordings=None):
        if store.path != coordinator.store.path: raise ValueError("voice coordinator must use the same store")
        self.store, self.coordinator, self.recognizer, self.synthesizer = store, coordinator, recognizer, synthesizer
        from ..storage.recordings import Recordings
        self.recordings = recordings if recordings is not None else Recordings(store)
        if self.recordings.store.path != store.path: raise ValueError("recordings must use the voice runtime store")
        self.cache = store.path.parent / "teacher-audio"
        if self.cache.is_symlink(): raise SpeechError("audio cache symlinks are refused")
        self.cache.mkdir(mode=0o700, exist_ok=True)
        directory = os.open(store.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
        self.coordinator.delivery_context = self.deliver

    def _path(self, audio_id):
        if not isinstance(audio_id, str) or not re.fullmatch(r"[a-f0-9]{64}", audio_id): raise SpeechError("invalid audio identity")
        if self.cache.is_symlink(): raise SpeechError("audio cache symlinks are refused")
        path = self.cache / (audio_id + ".mp3")
        if path.is_symlink(): raise SpeechError("audio file symlinks are refused")
        return path

    def _cached(self, audio_id):
        path = self._path(audio_id)
        with self.store._connection() as c:
            row = c.execute("SELECT sha256,size FROM speech_cache WHERE audio_id=?", (audio_id,)).fetchone()
        if row is None or not path.is_file(): return None
        with path.open("rb") as f: data = f.read(16 * 1024 * 1024 + 1)
        if len(data) != row["size"] or _hash(data) != row["sha256"]: return None
        return data

    def _synthesize(self, text, language):
        config = self.synthesizer.config
        identity = config.cache_key(text, language)
        with _lock(self.store, "@speech-cache", identity):
            return self._synthesize_locked(text, language, identity, config)

    def _synthesize_locked(self, text, language, identity, config):
        data = self._cached(identity)
        if data is None:
            data = self.synthesizer.synthesize(text, language=language)  # outside SQLite
            if not isinstance(data, bytes) or not data or len(data) > 16 * 1024 * 1024: raise SpeechError("invalid synthesized audio")
            path = self._path(identity)
            fd, name = tempfile.mkstemp(prefix=".pending-", dir=self.cache)
            try:
                with os.fdopen(fd, "wb") as f: f.write(data); f.flush(); os.fsync(f.fileno())
                os.replace(name, path)
                directory = os.open(self.cache, os.O_RDONLY | os.O_DIRECTORY)
                try: os.fsync(directory)
                finally: os.close(directory)
            finally:
                if os.path.exists(name): os.unlink(name)
            with self.store._transaction() as c:
                c.execute("INSERT INTO speech_cache VALUES (?,?,?,?,?,?) ON CONFLICT(audio_id) DO UPDATE SET sha256=excluded.sha256,size=excluded.size",
                    (identity, text, language, canonical_json(config.definition()), _hash(data), len(data)))
        return identity

    def deliver(self, learner, session, request, says):
        with _lock(self.store, learner, session):
            snapshot = self.store.session(learner, session)
            plan = _hash(canonical_json([request, says, self.synthesizer.config.definition()]).encode())
            result = []
            for position, say in enumerate(says):
                identity = self._synthesize(say["text"], snapshot["language"])
                with self.store._transaction() as c:
                    c.execute("INSERT OR IGNORE INTO speech_attachments VALUES (?,?,?,?,?)", (learner, session, plan, position, identity))
                result.append(identity)
            return {"audio_ids": result}

    def read(self, learner, session, audio_id):
        if not isinstance(audio_id, str) or not re.fullmatch(r"[a-f0-9]{64}", audio_id): return None
        with _lock(self.store, learner, session):
            with self.store._connection() as c:
                row = c.execute("SELECT c.* FROM speech_cache c WHERE c.audio_id=? AND EXISTS (SELECT 1 FROM speech_attachments a WHERE a.audio_id=c.audio_id AND a.learner_id=? AND a.session_id=?)",
                    (audio_id, _id(learner), _id(session))).fetchone()
            if row is None: return None
            data = self._cached(audio_id)
            if data is None:
                if self.synthesizer.config.cache_key(row["text"], row["language"]) != audio_id:
                    raise SpeechError("audio uses a different configured voice; reload the current presentation")
                self._synthesize(row["text"], row["language"])
                data = self._cached(audio_id)
            if data is None: raise SpeechError("audio cache is unavailable; retry the saved presentation")
            return Audio(data, "audio/mpeg")

    def submit(self, learner, session, request, *, expected_revision, data, media_type):
        learner, session, request = _id(learner), _id(session), _id(request)
        if not isinstance(data, bytes) or not data or len(data) > 8 * 1024 * 1024: raise SpeechError("invalid recording")
        with _lock(self.store, learner, session):
            snapshot = self.store.session(learner, session)
            body = canonical_json({"sha256": _hash(data), "media_type": media_type, "language": snapshot["language"], "expected_revision": expected_revision})
            with self.store._transaction() as c:
                row = c.execute("SELECT * FROM speech_requests WHERE learner_id=? AND session_id=? AND request_id=?", (learner, session, request)).fetchone()
                work = c.execute("SELECT stage FROM requests WHERE learner_id=? AND session_id=? AND request_id=?", (learner, session, request)).fetchone()
                if row is None:
                    if work is not None: raise RequestConflict("request already identifies another input type")
                    if snapshot["revision"] != expected_revision or snapshot["status"] != "active": raise RevisionConflict("session changed")
                    c.execute("INSERT INTO speech_requests(learner_id,session_id,request_id,input_json,status) VALUES (?,?,?,?,'accepted')", (learner, session, request, body))
                elif row["input_json"] != body: raise RequestConflict("recording request has different input")
                elif work is None and (snapshot["revision"] != expected_revision or snapshot["status"] != "active"):
                    raise RevisionConflict("session changed")
                cached = json.loads(row["transcript_json"]) if row is not None and row["status"] == "recognized" else None
            self.recordings.keep(learner, session, request, data, media_type)
            if cached is None:
                failed_status = "failed"
                try:
                    result = self.recognizer.transcribe(data, language=snapshot["language"], media_type=media_type)
                    if not isinstance(result, Recognition): raise SpeechError("invalid recognition result")
                    if not result.text.strip():
                        failed_status = "empty"
                        raise SpeechError("empty recognition")
                except Exception:
                    with self.store._transaction() as c:
                        c.execute("UPDATE speech_requests SET status=? WHERE learner_id=? AND session_id=? AND request_id=?",
                            (failed_status, learner, session, request))
                    raise SpeechError("recognition failed or was empty; lesson unchanged") from None
                cached = asdict(result)
                with self.store._transaction() as c:
                    c.execute("UPDATE speech_requests SET status='recognized',transcript_json=? WHERE learner_id=? AND session_id=? AND request_id=?",
                              (canonical_json(cached), learner, session, request))
            return self.coordinator.submit(learner, session, request, expected_revision=expected_revision, text=cached["text"])

    def recognition(self, learner, session, request):
        snapshot = self.store.session(learner, session)
        report = snapshot["engine_state"]["data"].get("recognition_reports", {}).get(request)
        with self.store._connection() as c:
            row = c.execute("SELECT status,transcript_json,reported_problem FROM speech_requests WHERE learner_id=? AND session_id=? AND request_id=?", (_id(learner), _id(session), _id(request))).fetchone()
        if row is None:
            return {k: report[k] for k in ("request_id", "status", "text", "reported_problem")} if report else None
        return {"request_id": request, "status": row["status"], "text": json.loads(row["transcript_json"])["text"] if row["transcript_json"] else None,
                "reported_problem": bool(row["reported_problem"]) or report is not None}

    def report_problem(self, learner, session, request):
        # The saved-session annotation is canonical/portable. The local provider
        # row is a retryable projection; a crash between writes cannot lose it.
        with _lock(self.store, learner, session):
            value = self.recognition(learner, session, request)
            if value is None: return False
            self.coordinator.report_recognition(learner, session, request, status=value["status"], text=value["text"])
            with self.store._transaction() as c:
                c.execute("UPDATE speech_requests SET reported_problem=1 WHERE learner_id=? AND session_id=? AND request_id=?",
                          (_id(learner), _id(session), _id(request)))
            return True
