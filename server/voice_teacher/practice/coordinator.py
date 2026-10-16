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
from .session import Session, Say
from .repetition import RepetitionPlan, RepetitionSession, validate_plan
from .guided import GuidedPlan, GuidedSession, plan_guided, ACTIVITY_END_EN
from .free import FreePlan, FreeSession, FreePolicy, plan_free
from ..providers.dialogue import DialogueReply, provider_identity

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
    def __init__(self, store, judge, *, delivery=None, delivery_context=None, clock=None, profiles=None, guided_activity_endings=None, dialogue=None, free_policies=None, feedback=None):
        self.store, self.work, self.judge = store, WorkStore(store), judge
        # Delivery creates replayable audio refs/metadata; it does not own state.
        self.delivery = delivery or (lambda says: {})
        self.delivery_context = delivery_context
        self.clock = clock
        self.feedback = feedback
        if feedback is not None: provider_identity(feedback.identity)
        self.dialogue = dialogue
        if dialogue is not None: provider_identity(dialogue.identity)
        self.free_policies = dict(free_policies) if free_policies is not None else {("uk", "en"): FreePolicy()}
        for pair, policy in self.free_policies.items():
            policy.validate()
            if pair != (policy.language, policy.instruction_language): raise ValueError("free policy language mismatch")
        self.guided_activity_endings = dict(guided_activity_endings) if guided_activity_endings is not None else {"en": ACTIVITY_END_EN}
        self.profiles = dict(profiles) if profiles is not None else {("uk", "en"): UKRAINIAN}
        if any(not isinstance(p, LanguageProfile) or pair != (p.language, p.instruction_language) for pair, p in self.profiles.items()):
            raise ValueError("profile mapping must match language pairs")

    def _engine(self, snapshot, judge):
        data = snapshot["engine_state"]["data"]
        if data.get("coordinator_version") not in {1, 2, 3, 4, 5, 6}:
            raise StorageError("unsupported coordinator capsule")
        profile_data = dict(data["profile"])
        profile_data["stop_words"] = tuple(profile_data["stop_words"])
        options = {"clock": self.clock} if self.clock else {}
        if data["coordinator_version"] in {5, 6}:
            if snapshot["mode"] != "free_conversation" or data.get("engine_kind") != "free": raise StorageError("unsupported mode capsule")
            engine = FreeSession.from_snapshot(FreePlan.from_dict(data["lesson"]), judge, data["engine"], profile=LanguageProfile(**profile_data), **options)
            if data["coordinator_version"] == 6:
                from .free_feedback import checked_state
                engine.feedback_state = checked_state(data["feedback"], snapshot, self.store.projection(snapshot["learner_id"],snapshot["session_id"])["turns"])
            return engine
        if data["coordinator_version"] == 4:
            if snapshot["mode"] != "guided_conversation" or data.get("engine_kind") != "guided": raise StorageError("unsupported mode capsule")
            return GuidedSession.from_snapshot(GuidedPlan.from_dict(data["lesson"]), judge, data["engine"], profile=LanguageProfile(**profile_data), **options)
        if data["coordinator_version"] == 3:
            if snapshot["mode"] != "repetition" or data.get("engine_kind") != "repetition": raise StorageError("unsupported mode capsule")
            return RepetitionSession.from_snapshot(RepetitionPlan.from_dict(data["lesson"]), judge, data["engine"], profile=LanguageProfile(**profile_data), **options)
        return Session.from_snapshot(Lesson.from_dict(data["lesson"]), judge, data["engine"],
                                     profile=LanguageProfile(**profile_data), **options)

    @staticmethod
    def _capsule(engine, presentation):
        if isinstance(engine, (RepetitionSession, GuidedSession, FreeSession)):
            return {"format_version": 1, "data": {"coordinator_version": 3 if isinstance(engine, RepetitionSession) else 4 if isinstance(engine, GuidedSession) else 6 if hasattr(engine,"feedback_state") else 5,
                "engine_kind": "repetition" if isinstance(engine, RepetitionSession) else "guided" if isinstance(engine, GuidedSession) else "free",
                "lesson": engine.lesson.to_dict(), "profile": {**asdict(engine.profile), "stop_words": list(engine.profile.stop_words)},
                "engine": engine.snapshot(), "presentation": presentation,
                **({"feedback": deepcopy(engine.feedback_state)} if hasattr(engine,"feedback_state") else {})}}
        return {"format_version": 1, "data": {"coordinator_version": 2,
            "lesson": engine.lesson.to_dict(), "profile": {**asdict(engine.profile), "stop_words": list(engine.profile.stop_words)},
            "engine": engine.snapshot(), "presentation": presentation}}

    @staticmethod
    def _presentation(snapshot, request, engine, says):
        return {"session_id": snapshot["session_id"], "request_id": request,
                "revision": snapshot["revision"], "status": snapshot["status"],
                "done": engine.done, "card": engine.card, "teacher": [asdict(s) for s in says if s.text],
                **({"activity": engine.activity} if isinstance(engine, GuidedSession) else {})}

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
        says = self._publish_feedback(snapshot, request, engine, says, events)
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

    def _extract_feedback(self, snapshot, engine, request, turn, assistance):
        from .free_feedback import context_for
        from ..storage.feedback import FeedbackStore
        from ..providers.feedback import FeedbackReply
        context = context_for(snapshot, turn)
        state = engine.feedback_state
        cache = FeedbackStore(self.store)
        saved = cache.get(snapshot["learner_id"], snapshot["session_id"], request, context, state["provider"])
        if saved is None:
            if self.feedback is None or provider_identity(self.feedback.identity) != state["provider"]:
                raise StorageError("pinned feedback provider is unavailable")
            reply = self.feedback(context)
            if not isinstance(reply, FeedbackReply): raise ValueError("invalid feedback provider result")
            reply = reply.checked(context)
            saved = cache.save(snapshot["learner_id"], snapshot["session_id"], request, context, state["provider"], asdict(reply))
        reply = FeedbackReply(**saved).checked(context)
        for n, claim in enumerate(reply.observations):
            state["observations"].append({"event_id": _identity(snapshot["learner_id"],snapshot["session_id"],request,"feedback",n),
                "turn": deepcopy(turn), "assistance": deepcopy(assistance), "claim": claim, "uncertain": context["recognition_uncertain"]})

    def _publish_feedback(self, snapshot, request, engine, says, events):
        state = getattr(engine,"feedback_state",None)
        if state is None or (engine.lesson.correction_style == "end_of_session" and not engine.done): return says
        feedback_says = []
        for row in state["observations"]:
            if row["event_id"] in state["published"]: continue
            claim = row["claim"]
            reports = snapshot["engine_state"]["data"].get("recognition_reports",{})
            if any(r.get("origin_turn_id") == row["turn"]["turn_id"] for r in reports.values()): row["uncertain"] = True
            item = None
            if claim["item_id"] is not None:
                course = next(c for c in snapshot["curriculum_snapshot"]["courses"] if c["course_id"] == snapshot["source"]["course_id"])
                authored = next(i for i in course["items"] if i["item_id"] == claim["item_id"])
                item = {"source_id":snapshot["source"]["source_id"],"course_id":course["course_id"],"item_id":authored["item_id"],"item_revision":authored["item_revision"]}
            evidence = {"outcome":"observed","attempt":claim["original"],"preferred":claim["preferred"],"reason":claim["reason"],"recognition_uncertain":row["uncertain"]}
            event = self._event(snapshot,request,snapshot["event_sequence"]+len(events)+1,"evidence.recorded",turn=row["turn"],assistance=row["assistance"],evidence=evidence,item=item)
            event["event_id"] = row["event_id"]
            events.append(event);state["published"].append(row["event_id"])
            if claim["preferred"] is not None and not row["uncertain"]:
                from .free_feedback import _plain
                limit = 3 if engine.done else 1
                already_spoken = any(_plain(claim["preferred"]) in _plain(s.text) for s in says)
                if len(feedback_says) < limit and (engine.done or not already_spoken):
                    text = claim["preferred"] + " — " + claim["reason"]
                    feedback_says.append(Say(text,"feedback"))
        return feedback_says + says if engine.done else says + feedback_says

    def promote_personal(self, learner, session, request, *, expected_revision, observation_id, form, meaning):
        from .personal_review import target_id, validate_targets, history
        if form not in {"original","preferred"} or not isinstance(meaning,str) or not meaning.strip() or len(meaning)>500:
            raise StorageError("choose an observed form and its review meaning")
        value = {"operation":"promote_personal","observation_id":observation_id,"form":form,"meaning":meaning}
        with _lock(self.store,learner,session):
            try: old = self.work.get(learner,session,request)
            except KeyError: old = None
            if old is not None:
                if old["input_json"] != canonical_json(value) or old["expected_revision"] != expected_revision: raise RequestConflict("promotion request changed")
                if old["stage"] in {"committed","delivered"}: return json.loads(old["result_json"])
            snapshot = self.store.session(learner,session)
            engine = self._engine(snapshot,self.judge)
            state = getattr(engine,"feedback_state",None)
            if state is None: raise StorageError("session has no free feedback")
            observation = next((r for r in state["observations"] if r["event_id"] == observation_id),None)
            reports = snapshot["engine_state"]["data"].get("recognition_reports",{})
            _, owned_events = history(self.store,learner)
            superseded = {e["supersedes_event_id"] for e in owned_events if e["supersedes_event_id"]}
            if observation is None or observation_id not in state["published"] or observation["uncertain"] or observation_id in superseded or any(r.get("origin_turn_id") == observation["turn"]["turn_id"] for r in reports.values()):
                raise StorageError("review needs a supported, undisputed published observation")
            claim = observation["claim"]
            text = claim["original"] if form == "original" else claim["preferred"]
            if text is None: raise StorageError("this observation has no preferred form")
            identity = target_id(learner,session,observation_id,form)
            existing = next((r for r in state["review_targets"] if r["target_id"] == identity),None)
            if existing is not None:
                if existing["meaning"] != meaning: raise RequestConflict("saved review meaning cannot be overwritten")
                return {"target":deepcopy(existing),"revision":snapshot["revision"]}
            self.work.accept(learner,session,request,expected_revision,value,statuses={"active","paused","finished"})
            original_source,item = None,None
            if claim["item_id"] is not None:
                original_source = snapshot["source"]
                course = next(c for c in snapshot["curriculum_snapshot"]["courses"] if c["course_id"] == original_source["course_id"])
                authored = next(i for i in course["items"] if i["item_id"] == claim["item_id"])
                item = {"source_id":original_source["source_id"],"course_id":course["course_id"],"item_id":authored["item_id"],"item_revision":authored["item_revision"]}
            target = {"target_id":identity,"observation_id":observation_id,"form":form,"text":text,"meaning":meaning,
                "origin_session_id":session,"origin_turn_id":observation["turn"]["turn_id"],"language":snapshot["language"],"instruction_language":snapshot["instruction_language"],
                "original_source":deepcopy(original_source),"original_item":item}
            state["review_targets"].append(target);validate_targets(state,snapshot)
            presentation = deepcopy(snapshot["engine_state"]["data"]["presentation"])
            snapshot["revision"] = expected_revision + 1;snapshot["event_sequence"] += 1
            presentation.update(revision=snapshot["revision"],request_id=request)
            snapshot["engine_state"] = self._capsule(engine,presentation)
            if reports: snapshot["engine_state"]["data"]["recognition_reports"] = reports
            event = self._event(snapshot,request,snapshot["event_sequence"],"state.saved",state=deepcopy(snapshot))
            event["provenance"]["origin_turn_id"] = observation["turn"]["turn_id"]
            result = {"target":deepcopy(target),"revision":snapshot["revision"]}
            self.store.commit(learner,session,[event],expected_revision=expected_revision,_completion=(request,result))
            return result

    def create_personal_review(self, learner, session, target_ids, *, recall_before_model=False):
        from .personal_review import compile_plan
        source, plan = compile_plan(self.store,learner,target_ids,recall_before_model=recall_before_model)
        template = dict(schema_version=1,kind="session_snapshot",learner_id=learner,session_id=session,revision=0,event_sequence=0,
            mode="repetition",status="created",source=source.source_ref("personal-review","personal-set"),curriculum_snapshot=source.curriculum,
            topic=None,language=plan.language,instruction_language=plan.instruction_language,learner_profile=self.store.learner(learner),engine_state={"format_version":1,"data":{}})
        return self.create_repetition(template,plan)

    def create_free(self, template, plan, *, profile=None):
        snapshot = deepcopy(template)
        try:
            from ..content.registry import SourceSnapshot
            validate_session(snapshot)
            if snapshot["mode"] != "free_conversation" or snapshot["source"] != plan.source or snapshot["topic"] != plan.topic:
                raise ValueError("free conversation source/topic mismatch")
            pair = (snapshot["language"], snapshot["instruction_language"])
            policy = self.free_policies.get(pair)
            if policy is None or self.dialogue is None or provider_identity(self.dialogue.identity) != plan.provider:
                raise ValueError("free conversation provider/policy unavailable")
            source = SourceSnapshot("pinned", canonical_json({"curriculum": snapshot["curriculum_snapshot"],
                "provenance": snapshot["source"]["revision"]})) if snapshot["source"] else None
            expected = plan_free(source, plan.course_id, plan.lesson_id, topic=plan.topic,
                learner_level=snapshot["learner_profile"].get("level", "A2"), provider=self.dialogue.identity,
                policy=policy, correction_style=plan.correction_style)
            if expected.to_dict() != plan.to_dict(): raise ValueError("free conversation plan mismatch")
            profile = profile or self.profiles.get(pair)
            if profile is None: raise ValueError("free conversation language unavailable")
            engine = FreeSession(plan, self.dialogue, profile=profile)
        except ValueError:
            raise StorageError("invalid free conversation plan or provider") from None
        if self.feedback is not None:
            from .free_feedback import new_state
            engine.feedback_state = new_state(self.feedback.identity)
        says = engine.start()
        snapshot.update(revision=0, event_sequence=0, status="active")
        events = []
        presentation = self._finish_events(snapshot, None, engine, says, events, 0)
        self.store.commit(snapshot["learner_id"], snapshot["session_id"], events, expected_revision=None,
            activities=[{"activity_id": "conversation", "position": 0,
                "data": {"topic": plan.topic, "correction_style": plan.correction_style, "turn_limit": policy.max_turns}}])
        return presentation

    def create_guided(self, template, plan, *, profile=None):
        snapshot = deepcopy(template)
        try:
            from ..content.registry import SourceSnapshot
            validate_session(snapshot)
            if snapshot["mode"] != "guided_conversation" or snapshot["source"] != plan.source or plan.activity_end != self.guided_activity_endings.get(plan.instruction_language):
                raise ValueError("guided source mismatch")
            source = SourceSnapshot("pinned", canonical_json({"curriculum": snapshot["curriculum_snapshot"],
                "provenance": snapshot["source"]["revision"]}))
            expected = plan_guided(source, plan.course_id, plan.lesson_id, routine=plan.routine, cards=plan.cards,
                spoken_tasks=plan.spoken_tasks, max_goals=plan.max_goals, sitting=plan.sitting, activity_end=plan.activity_end)
            if expected.to_dict() != plan.to_dict() or (snapshot["language"], snapshot["instruction_language"]) != (plan.language, plan.instruction_language):
                raise ValueError("guided plan differs from pinned curriculum")
            profile = profile or self.profiles.get((plan.language, plan.instruction_language))
            if profile is None: raise ValueError("no configured guided language profile")
            engine = GuidedSession(plan, self.judge, profile=profile, clock=self.clock)
        except ValueError:
            raise StorageError("invalid guided plan or language profile") from None
        says = engine.start()
        snapshot.update(revision=0, event_sequence=0, status="active")
        events = []
        presentation = self._finish_events(snapshot, None, engine, says, events, 0)
        self.store.commit(snapshot["learner_id"], snapshot["session_id"], events, expected_revision=None,
            activities=[{"activity_id": a["activity_id"], "position": n, "data": {"part": a["part"],
                "step_ids": [s["step_id"] for s in a["lesson"]["steps"]],
                "recall_goal_ids": [r["goal_id"] for r in a["lesson"]["recall"]]}}
                for n, a in enumerate(plan.activities)])
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
        if snapshot["engine_state"]["data"].get("coordinator_version") not in {1, 2, 3, 4, 5, 6}:
            raise StorageError("unsupported coordinator capsule")
        result = deepcopy(snapshot["engine_state"]["data"]["presentation"])
        if self.delivery_context:
            result["delivery"] = self.delivery_context(learner, session, result["request_id"], deepcopy(result["teacher"]))
        return result

    def request_status(self, learner, session, request):
        """Read only the owned durable receipt, never input/provider payloads."""
        record = self.work.get(learner, session, request)
        stage = record["stage"]
        if stage not in {"accepted", "judged", "committed", "delivered", "cancelled"}:
            raise StorageError("unsupported request stage")
        ready = stage in {"committed", "delivered"}
        return {"request_id": request, "status": "ready" if ready else "cancelled" if stage == "cancelled" else "pending",
                "revision": record["expected_revision"] + 1 if ready else None}

    def report_recognition(self, learner, session, request, *, status, text):
        """Portable learner annotation; no invented correction or engine advance."""
        with _lock(self.store, learner, session):
            snapshot = self.store.session(learner, session)
            data = snapshot["engine_state"]["data"]
            if data.get("coordinator_version") not in {1, 2, 3, 4, 5, 6}: raise StorageError("unsupported coordinator capsule")
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
        if isinstance(engine, (RepetitionSession, GuidedSession, FreeSession)): return engine.assistance
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
            def judge(item, heard=None):
                saved = self.work.get(learner, session, request)
                if saved["stage"] == "cancelled":
                    raise RequestConflict("request was cancelled before judging")
                free = snapshot["mode"] == "free_conversation"
                if saved["judgment_json"] is not None:
                    data = json.loads(saved["judgment_json"])
                    return DialogueReply(**data) if free else _judgement(data)
                if free:
                    feedback_state = snapshot["engine_state"]["data"].get("feedback")
                    if feedback_state is not None and (self.feedback is None or provider_identity(self.feedback.identity) != feedback_state["provider"]):
                        raise StorageError("pinned feedback provider is unavailable")
                    pinned = snapshot["engine_state"]["data"]["lesson"]["provider"]
                    if self.dialogue is None or provider_identity(self.dialogue.identity) != pinned:
                        raise StorageError("pinned dialogue provider is unavailable")
                    value = self.dialogue(item)
                    if not isinstance(value, DialogueReply): raise ValueError("invalid dialogue response")
                    return DialogueReply(**self.work.judgment(learner, session, request, asdict(value)))
                value = self.judge(item, heard)  # no DB transaction or write lock
                return _judgement(self.work.judgment(learner, session, request, asdict(value)))
            engine = self._engine(snapshot, judge)
            before = len(engine.evidence)
            assistance = self._assistance(engine)
            free_turns = engine.turns if isinstance(engine, FreeSession) else None
            says = engine.hear(text)
            snapshot["revision"] = expected_revision + 1
            if engine.done: snapshot["status"] = "finished"
            elif (isinstance(engine, GuidedSession) and engine.boundary) or (isinstance(engine, FreeSession) and engine.paused): snapshot["status"] = "paused"
            index = len(self.store.projection(learner, session)["turns"])
            turn = {"turn_id": _identity(learner, session, request, "learner"), "index": index,
                    "role": "learner", "text": text}
            events = [self._event(snapshot, request, snapshot["event_sequence"] + 1, "turn.accepted", turn=turn, assistance=assistance)]
            if free_turns is not None and engine.turns > free_turns and hasattr(engine,"feedback_state"):
                self._extract_feedback(snapshot, engine, request, turn, assistance)
            new_evidence = engine.evidence[before:]
            items = next(c for c in snapshot["curriculum_snapshot"]["courses"] if c["course_id"] == engine.lesson.course_id)["items"] if new_evidence else []
            revisions = {i["item_id"]: i["item_revision"] for i in items}
            for e in new_evidence:
                target = engine.lesson.targets[e.number - 1] if isinstance(engine, RepetitionSession) else None
                item = target["item"] if target else None if not e.item_id else {"source_id": e.source_id, "course_id": e.course_id, "item_id": e.item_id,
                        "item_revision": revisions[e.item_id]}
                evidence = {"outcome": e.label, "attempt": text, "preferred": e.target,
                            "reason": "goal skipped by a later-step response" if e.label == "skipped" else ("accepted goal; offered item attribution ambiguous" if not e.item_id else None),
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
            if operation == "stop": says = engine.stop()
            elif operation == "resume" and isinstance(engine, FreeSession):
                try: says = engine.resume()
                except ValueError: raise StorageError("conversation has reached its stable limit") from None
            elif operation == "resume" and isinstance(engine, GuidedSession): says = engine.resume()
            elif operation == "resume" and isinstance(engine, RepetitionSession): says = engine.present()
            elif operation == "pause" and isinstance(engine, FreeSession): says = engine.pause()
            else: says = []
            snapshot["status"] = {"pause": "paused", "resume": "active", "stop": "finished"}[operation]
            snapshot["revision"] = expected_revision + 1
            events = []
            presentation = self._finish_events(snapshot, request, engine, says, events,
                                                len(self.store.projection(learner, session)["turns"]))
            self.store.commit(learner, session, events, expected_revision=expected_revision, _completion=(request, presentation))
            return self._deliver(learner, session, request)
