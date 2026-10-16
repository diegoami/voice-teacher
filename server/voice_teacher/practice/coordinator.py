"""Resumable text turns around the synchronous engine and transactional store."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
import threading
import weakref
from uuid import uuid5, NAMESPACE_URL

from schemas.validate import canonical_json, validate_session
from ..providers import Judgement, Verdict
from ..storage import RevisionConflict, StorageError
from ..storage.work import WorkStore, RequestConflict, WorkBusy
from .models import Lesson
from .profiles import LanguageProfile, UKRAINIAN
from .session import Session
from .repetition import RepetitionPlan, RepetitionSession, validate_plan

_locks_guard = threading.Lock()
_locks = weakref.WeakValueDictionary()


def _lock(store, learner, session):
    # One writer process is the supported deployment. SQL revision/work guards
    # additionally prevent duplicate transitions across competing connections.
    with _locks_guard:
        return _locks.setdefault((str(store.path), learner, session), threading.RLock())


def _identity(*parts):
    return str(uuid5(NAMESPACE_URL, canonical_json(list(parts))))


def _judgement(value):
    return Judgement(Verdict(**value["verdict"]), value["seconds"], value["usage"])


class Coordinator:
    def __init__(self, store, judge, *, delivery=None, delivery_context=None, clock=None, profiles=None):
        self.store, self.work, self.judge = store, WorkStore(store), judge
        # Delivery creates replayable audio refs/metadata; it does not own state.
        self.delivery = delivery or (lambda says: {})
        self.delivery_context = delivery_context
        self.clock = clock
        self.profiles = dict(profiles) if profiles is not None else {("uk", "en"): UKRAINIAN}
        if any(not isinstance(p, LanguageProfile) or pair != (p.language, p.instruction_language) for pair, p in self.profiles.items()):
            raise ValueError("profile mapping must match language pairs")

    def _engine(self, snapshot, judge):
        data = snapshot["engine_state"]["data"]
        if data.get("coordinator_version") not in {1, 2, 3}:
            raise StorageError("unsupported coordinator capsule")
        profile_data = dict(data["profile"])
        profile_data["stop_words"] = tuple(profile_data["stop_words"])
        options = {"clock": self.clock} if self.clock else {}
        if data["coordinator_version"] == 3:
            if snapshot["mode"] != "repetition" or data.get("engine_kind") != "repetition": raise StorageError("unsupported mode capsule")
            return RepetitionSession.from_snapshot(RepetitionPlan.from_dict(data["lesson"]), judge, data["engine"], profile=LanguageProfile(**profile_data), **options)
        return Session.from_snapshot(Lesson.from_dict(data["lesson"]), judge, data["engine"],
                                     profile=LanguageProfile(**profile_data), **options)

    @staticmethod
    def _capsule(engine, presentation):
        if isinstance(engine, RepetitionSession):
            return {"format_version": 1, "data": {"coordinator_version": 3, "engine_kind": "repetition",
                "lesson": engine.lesson.to_dict(), "profile": {**asdict(engine.profile), "stop_words": list(engine.profile.stop_words)},
                "engine": engine.snapshot(), "presentation": presentation}}
        return {"format_version": 1, "data": {"coordinator_version": 2,
            "lesson": engine.lesson.to_dict(), "profile": {**asdict(engine.profile), "stop_words": list(engine.profile.stop_words)},
            "engine": engine.snapshot(), "presentation": presentation}}

    @staticmethod
    def _presentation(snapshot, request, engine, says):
        return {"session_id": snapshot["session_id"], "request_id": request,
                "revision": snapshot["revision"], "status": snapshot["status"],
                "done": engine.done, "card": engine.card, "teacher": [asdict(s) for s in says if s.text]}

    def _event(self, snapshot, request, sequence, kind, *, turn=None, assistance=None,
               evidence=None, item=None, state=None):
        source = snapshot["source"]
        return {"schema_version": 1, "kind": "progress_event",
                "event_id": _identity(snapshot["learner_id"], snapshot["session_id"], request, kind, sequence),
                "learner_id": snapshot["learner_id"], "session_id": snapshot["session_id"],
                "sequence": sequence, "occurred_at": datetime.now(timezone.utc).isoformat(),
                "event_type": kind, "mode": snapshot["mode"], "source": source,
                "turn": turn, "assistance": assistance, "evidence": evidence, "snapshot": state,
                "supersedes_event_id": None,
                "provenance": {"original_source": source if item else None, "original_item": item,
                               "practice_source": source, "origin_session_id": snapshot["session_id"],
                               "origin_turn_id": turn["turn_id"] if turn else _identity(request, "state")}}

    def _finish_events(self, snapshot, request, engine, says, events, turn_index):
        base = snapshot["event_sequence"]
        presentation = self._presentation(snapshot, request, engine, says)
        for i, say in enumerate(presentation["teacher"]):
            turn = {"turn_id": _identity(snapshot["learner_id"], snapshot["session_id"], request, "teacher", i),
                    "index": turn_index + i, "role": "teacher", "text": say["text"]}
            events.append(self._event(snapshot, request, base + len(events) + 1, "teacher.reply_planned", turn=turn))
        snapshot["event_sequence"] = base + len(events) + 1
        reports = deepcopy(snapshot["engine_state"]["data"].get("recognition_reports", {}))
        snapshot["engine_state"] = self._capsule(engine, presentation)
        if reports: snapshot["engine_state"]["data"]["recognition_reports"] = reports
        state_event = self._event(snapshot, request, snapshot["event_sequence"], "state.saved", state=deepcopy(snapshot))
        origin = next((e["turn"] for e in reversed(events) if e["turn"] is not None), None)
        if origin is None:
            previous = self.store.projection(snapshot["learner_id"], snapshot["session_id"])["turns"]
            if not previous:
                raise StorageError("saved state must reference an existing session turn")
            origin = previous[-1]
        state_event["provenance"]["origin_turn_id"] = origin["turn_id"]
        events.append(state_event)
        return presentation

    def create(self, template, lesson, *, profile=UKRAINIAN, part="all"):
        """Create a pinned guided session; speech can be prepared from saved presentation.

        The caller supplies a T03 snapshot envelope with validated curriculum;
        its engine_state/revision/sequence/status are replaced by this coordinator.
        """
        snapshot = deepcopy(template)
        source = snapshot.get("source")
        if snapshot.get("mode") != "guided_conversation" or source is None or (
            lesson.source_id, lesson.course_id, lesson.lesson_id
        ) != (source["source_id"], source["course_id"], source["lesson_id"]):
            raise StorageError("prepared lesson must match the pinned guided source")
        if (snapshot["language"], snapshot["instruction_language"]) != (lesson.language, lesson.instruction_language):
            raise StorageError("prepared lesson language does not match session")
        options = {"clock": self.clock} if self.clock else {}
        engine = Session(lesson, self.judge, profile=profile, part=part, **options)
        says = engine.start()
        snapshot.update(revision=0, event_sequence=0, status="active")
        events = []
        presentation = self._finish_events(snapshot, None, engine, says, events, 0)
        validate_session(snapshot)
        items = next(c for c in snapshot["curriculum_snapshot"]["courses"] if c["course_id"] == lesson.course_id)["items"]
        known = {i["item_id"] for i in items}
        if any(i not in known for i in [*lesson.opening_item_ids, *(i for s in lesson.steps for i in s.target_item_ids),
                                      *(i for r in lesson.recall for i in r.target_item_ids)]):
            raise StorageError("prepared lesson has an unknown curriculum item")
        speech = {i["item_id"]: i["text"]["speech"] for i in items}
        pairs = list(zip(lesson.opening_item_ids, lesson.opening))
        for row in [*lesson.steps, *lesson.recall]:
            pairs.extend(zip(row.target_item_ids, row.targets))
        if any(speech[identity] != text for identity, text in pairs):
            raise StorageError("prepared target rendering does not match pinned curriculum")
        self.store.commit(snapshot["learner_id"], snapshot["session_id"], events, expected_revision=None,
                          activities=[{"activity_id": "combined", "position": 0, "data": {"part": part}}])
        return presentation

    def create_repetition(self, template, plan, *, profile=None):
        snapshot = deepcopy(template)
        try:
            validate_session(snapshot)
            plan.validate()
            validate_plan(self.store, snapshot, plan)
            profile = profile or self.profiles.get((plan.language, plan.instruction_language))
            if profile is None: raise StorageError("no configured profile for repetition language pair")
            engine = RepetitionSession(plan, self.judge, profile=profile, clock=self.clock)
        except ValueError:
            raise StorageError("invalid repetition plan or language profile") from None
        says = engine.start()
        snapshot.update(revision=0, event_sequence=0, status="active")
        events = []
        presentation = self._finish_events(snapshot, None, engine, says, events, 0)
        self.store.commit(snapshot["learner_id"], snapshot["session_id"], events, expected_revision=None,
            activities=[{"activity_id": "repetition", "position": 0, "data": {"item_count": len(plan.targets), "recall_before_model": plan.recall_before_model}}])
        return presentation

    def _deliver(self, learner, session, request):
        record = self.work.get(learner, session, request)
        if record["stage"] not in {"committed", "delivered"}:
            raise RequestConflict("request has no committed presentation")
        if record["stage"] == "committed":
            result = json.loads(record["result_json"])
            delivered = self.delivery_context(learner, session, request, deepcopy(result["teacher"])) if self.delivery_context else self.delivery(deepcopy(result["teacher"]))
            if not isinstance(delivered, dict):
                raise StorageError("delivery must return JSON-object metadata")
            record = self.work.delivered(learner, session, request, delivered)
        return {**json.loads(record["result_json"]), "delivery": json.loads(record["delivery_json"])}

    def presentation(self, learner, session):
        """Materialize saved speech, including creation, without a new transition."""
        snapshot = self.store.session(learner, session)
        if snapshot["engine_state"]["data"].get("coordinator_version") not in {1, 2, 3}:
            raise StorageError("unsupported coordinator capsule")
        result = deepcopy(snapshot["engine_state"]["data"]["presentation"])
        if self.delivery_context:
            result["delivery"] = self.delivery_context(learner, session, result["request_id"], deepcopy(result["teacher"]))
        return result

    def report_recognition(self, learner, session, request, *, status, text):
        """Portable learner annotation; no invented correction or engine advance."""
        with _lock(self.store, learner, session):
            snapshot = self.store.session(learner, session)
            data = snapshot["engine_state"]["data"]
            if data.get("coordinator_version") not in {1, 2, 3}: raise StorageError("unsupported coordinator capsule")
            reports = data.setdefault("recognition_reports", {})
            if request in reports: return
            report_request = _identity(learner, session, request, "recognition-report")
            with self.store._connection() as connection:
                active = connection.execute("SELECT request_id FROM requests WHERE learner_id=? AND session_id=? AND stage IN ('accepted','judged')", (learner, session)).fetchone()
            if active is not None and active[0] not in {request, report_request}:
                raise WorkBusy("another turn must finish before reporting an older recording")
            self.work.accept(learner, session, report_request, snapshot["revision"], {"recognition_report": request},
                             statuses={snapshot["status"]}, cancel_pending=True)
            turns = self.store.projection(learner, session)["turns"]
            origin = _identity(learner, session, request, "learner")
            reports[request] = {"request_id": request, "status": status, "text": text, "reported_problem": True,
                                "origin_turn_id": origin if any(t["turn_id"] == origin for t in turns) else None}
            data["coordinator_version"] = max(2, data["coordinator_version"])
            revision = snapshot["revision"]
            snapshot["revision"] += 1
            snapshot["event_sequence"] += 1
            data["presentation"]["revision"] = snapshot["revision"]
            event = self._event(snapshot, "@recognition-report:" + request, snapshot["event_sequence"], "state.saved", state=deepcopy(snapshot))
            if not turns: raise StorageError("recognition report requires an existing session plan")
            event["provenance"]["origin_turn_id"] = turns[-1]["turn_id"]
            self.store.commit(learner, session, [event], expected_revision=revision,
                              _completion=(report_request, {"status": "reported", "revision": snapshot["revision"]}))

    @staticmethod
    def _assistance(engine):
        if isinstance(engine, RepetitionSession): return engine.assistance
        model = engine.phase == "opening" or (engine.phase == "guided" and engine.round == 0)
        kind = "model" if model else engine.state.help or ("task_card" if engine.phase == "guided" and engine.round == 1 else "none")
        return {"kind": kind, "help_level": 2 if kind == "model" else int(kind in {"cue", "correction"}),
                "target_exposed": model or kind in {"cue", "correction", "model"}}

    def submit(self, learner, session, request, *, expected_revision, text):
        if not isinstance(text, str) or not text.strip():
            raise StorageError("nonempty learner text required")
        with _lock(self.store, learner, session):
            record = self.work.accept(learner, session, request, expected_revision, {"text": text}, statuses={"active"})
            if record["stage"] in {"committed", "delivered"}:
                return self._deliver(learner, session, request)
            snapshot = self.store.session(learner, session)
            def judge(item, heard):
                saved = self.work.get(learner, session, request)
                if saved["stage"] == "cancelled":
                    raise RequestConflict("request was cancelled before judging")
                if saved["judgment_json"] is not None:
                    return _judgement(json.loads(saved["judgment_json"]))
                value = self.judge(item, heard)  # no DB transaction or write lock
                return _judgement(self.work.judgment(learner, session, request, asdict(value)))
            engine = self._engine(snapshot, judge)
            before = len(engine.evidence)
            assistance = self._assistance(engine)
            says = engine.hear(text)
            snapshot["revision"] = expected_revision + 1
            if engine.done: snapshot["status"] = "finished"
            index = len(self.store.projection(learner, session)["turns"])
            turn = {"turn_id": _identity(learner, session, request, "learner"), "index": index,
                    "role": "learner", "text": text}
            events = [self._event(snapshot, request, snapshot["event_sequence"] + 1, "turn.accepted", turn=turn, assistance=assistance)]
            items = next(c for c in snapshot["curriculum_snapshot"]["courses"] if c["course_id"] == engine.lesson.course_id)["items"]
            revisions = {i["item_id"]: i["item_revision"] for i in items}
            for e in engine.evidence[before:]:
                target = engine.lesson.targets[e.number - 1] if isinstance(engine, RepetitionSession) else None
                item = target["item"] if target else {"source_id": e.source_id, "course_id": e.course_id, "item_id": e.item_id,
                        "item_revision": revisions[e.item_id]}
                evidence = {"outcome": e.label, "attempt": text, "preferred": e.target,
                            "reason": "goal skipped by a later-step response" if e.label == "skipped" else None,
                            "recognition_uncertain": False}
                event = self._event(snapshot, request, snapshot["event_sequence"] + len(events) + 1,
                    "evidence.recorded", turn=turn, assistance=assistance, evidence=evidence, item=item)
                if target:
                    event["provenance"]["original_source"] = deepcopy(target["source"])
                    if target["origin_session_id"]:
                        event["provenance"].update(origin_session_id=target["origin_session_id"], origin_turn_id=target["origin_turn_id"])
                events.append(event)
            presentation = self._finish_events(snapshot, request, engine, says, events, index + 1)
            self.store.commit(learner, session, events, expected_revision=expected_revision, _completion=(request, presentation))
            return self._deliver(learner, session, request)

    def control(self, learner, session, request, *, expected_revision, operation):
        allowed = {"pause": {"active"}, "resume": {"paused"}, "stop": {"active", "paused"}}
        if operation not in allowed:
            raise StorageError("unknown session control")
        with _lock(self.store, learner, session):
            record = self.work.accept(learner, session, request, expected_revision, {"operation": operation},
                                      statuses=allowed[operation], cancel_pending=True)
            if record["stage"] in {"committed", "delivered"}:
                return self._deliver(learner, session, request)
            snapshot = self.store.session(learner, session)
            engine = self._engine(snapshot, self.judge)
            says = engine.stop() if operation == "stop" else (engine.present() if operation == "resume" and isinstance(engine, RepetitionSession) else [])
            snapshot["status"] = {"pause": "paused", "resume": "active", "stop": "finished"}[operation]
            snapshot["revision"] = expected_revision + 1
            events = []
            presentation = self._finish_events(snapshot, request, engine, says, events,
                                                len(self.store.projection(learner, session)["turns"]))
            self.store.commit(learner, session, events, expected_revision=expected_revision, _completion=(request, presentation))
            return self._deliver(learner, session, request)
