"""Typed HTTP adapter around validated sources and durable session coordination."""
import re
from pathlib import Path

from fastapi import FastAPI, Request, Query
from fastapi.exceptions import RequestValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

from ..content.registry import SourceRegistry, SourceSpec, SourceError
from ..storage import StorageError, RevisionConflict
from ..storage.work import RequestConflict, WorkBusy
from .auth import Auth
from .boundary import Guard, error
from . import models as m


class Problem(Exception):
    def __init__(self, status, code, message): self.status, self.code, self.message = status, code, message


def _plain(text):
    return text.replace("\u0301", "") if text is not None else None


def _format_presentation(value):
    # Only explicitly planned teacher speech is exposed, with plain display text.
    ids = value.get("delivery", {}).get("audio_ids", [])
    if not isinstance(ids, list) or any(not isinstance(i, str) or not re.fullmatch(m.ID, i) for i in ids):
        raise Problem(502, "provider_failed", "Audio preparation failed; retry the same request")
    return m.Presentation(session_id=value["session_id"], request_id=value["request_id"], revision=value["revision"],
        status=value["status"], done=value["done"], card=_plain(value["card"]),
        teacher=[m.Teacher(text=_plain(s["display"]), kind=s["kind"]) for s in value["teacher"]], audio_ids=ids)


def _presentation(value):
    try: return _format_presentation(value)
    except Problem: raise
    except Exception:
        raise Problem(502, "provider_failed", "Provider returned an invalid response; retry the same request") from None


def create_app(store, coordinator, *, operator_token, origin="http://localhost:8000", audio=None,
               assets=None, clock=None, max_json_bytes=32768, max_audio_bytes=8 * 1024 * 1024):
    if coordinator.store.path != store.path: raise ValueError("coordinator must use the API runtime store")
    if any(type(v) is not int or v <= 0 for v in (max_json_bytes, max_audio_bytes)): raise ValueError("body limits must be positive")
    auth = Auth(store, operator_token, **({"clock": clock} if clock else {}))
    registry = SourceRegistry(store)
    app = FastAPI(title="Voice Teacher API", version="1", docs_url=None, redoc_url=None, openapi_url=None,
                  responses={status: {"model": m.Error} for status in (400, 401, 403, 404, 409, 413, 415, 422, 502, 503)})
    app.state.auth = auth
    app.add_middleware(Guard, auth=auth, origin=origin, max_json_bytes=max_json_bytes, max_audio_bytes=max_audio_bytes)

    @app.exception_handler(Problem)
    async def problem(request, exc): return error(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation(request, exc): return error(422, "invalid_request", "Request fields or types are invalid")

    @app.exception_handler(HTTPException)
    async def http(request, exc): return error(exc.status_code, "not_found" if exc.status_code == 404 else "invalid_request", "Endpoint not found" if exc.status_code == 404 else "Request rejected")

    def learner(request): return request.state.principal.learner_id

    def owned(request, session_id, revision=None):
        if not re.fullmatch(m.ID, session_id): raise Problem(404, "not_found", "Session not found")
        try: snapshot = store.session(learner(request), session_id)
        except KeyError: raise Problem(404, "not_found", "Session not found") from None
        if revision is not None and snapshot["revision"] != revision:
            raise Problem(409, "session_conflict", "Session changed; reload its status")
        return snapshot

    def call(function, *args, **kwargs):
        try: return function(*args, **kwargs)
        except Problem: raise
        except (RevisionConflict, RequestConflict, WorkBusy):
            raise Problem(409, "session_conflict", "Session changed or request conflicts; reload its status") from None
        except StorageError:
            raise Problem(409, "session_conflict", "Session cannot accept this request") from None
        except Exception:
            # Provider exceptions can contain API keys, request data or paths.
            raise Problem(502, "provider_failed", "Provider operation failed; retry the same request") from None

    def active(source):
        try: return registry.active(source)
        except (SourceError, StorageError): raise Problem(404, "not_found", "Source not available") from None

    def course(snapshot, course_id):
        for c in snapshot.curriculum["courses"]:
            if c["course_id"] == course_id: return c
        raise Problem(404, "not_found", "Course not found")

    @app.get("/healthz")
    def health(): return {"status": "ok"}

    @app.post("/api/v1/pair", response_model=m.Paired)
    def pair(body: m.Pair):
        result = auth.pair(body.code)
        if result is None: raise Problem(401, "invalid_pairing", "Pairing code is invalid or expired")
        return result

    @app.put("/api/v1/operator/learners/{learner_id}", status_code=204)
    def configure_learner(learner_id: str, body: m.Learner):
        if not re.fullmatch(m.ID, learner_id): raise Problem(422, "invalid_request", "Invalid learner identity")
        store.save_learner(learner_id, body.model_dump())
        return Response(status_code=204)

    @app.post("/api/v1/operator/pairing-codes", response_model=m.Code)
    def pairing_code(body: m.PairCode):
        try: return auth.issue_code(body.learner_id, body.label)
        except KeyError: raise Problem(404, "not_found", "Learner not found") from None

    @app.delete("/api/v1/operator/clients/{client_id}", status_code=204)
    def revoke(client_id: str):
        if not re.fullmatch(m.ID, client_id): raise Problem(422, "invalid_request", "Invalid client identity")
        auth.revoke(client_id)
        return Response(status_code=204)

    @app.put("/api/v1/operator/sources/{source_id}", response_model=m.Source)
    def configure_source(source_id: str, body: m.SourceConfig):
        try:
            if body.source_id != source_id: raise ValueError()
            registry.register(SourceSpec(**body.model_dump()))
            registry.refresh(source_id)
        except Exception:
            raise Problem(422, "invalid_source", "Source configuration or content is invalid; previous active catalogue retained") from None
        return next(m.Source(source_id=s["source_id"], name=s["name"], version_id=s["version_id"], available=s["version_id"] is not None) for s in registry.list_sources() if s["source_id"] == source_id)

    @app.get("/api/v1/sources", response_model=list[m.Source])
    def sources():
        return [m.Source(source_id=s["source_id"], name=s["name"], version_id=s["version_id"], available=s["version_id"] is not None) for s in registry.list_sources()]

    @app.get("/api/v1/sources/{source_id}/courses", response_model=list[m.Course])
    def courses(source_id: str):
        return [m.Course(**{k: c[k] for k in m.Course.model_fields}) for c in active(source_id).curriculum["courses"]]

    @app.get("/api/v1/sources/{source_id}/courses/{course_id}/lessons", response_model=list[m.Lesson])
    def lessons(source_id: str, course_id: str):
        snap = active(source_id)
        result = []
        for lesson in course(snap, course_id)["lessons"]:
            available = []
            try:
                prepared = snap.prepared_lesson(course_id, lesson["lesson_id"])
                if "guided_conversation" in lesson["modes"] and (prepared.language, prepared.instruction_language) == ("uk", "en"):
                    available = ["guided_conversation"]
            except SourceError: pass
            result.append(m.Lesson(lesson_id=lesson["lesson_id"], title=lesson["title"], authored_modes=lesson["modes"], available_modes=available))
        return result

    @app.post("/api/v1/sessions", response_model=m.Presentation, status_code=201)
    def start(request: Request, body: m.Start):
        if body.mode != "guided_conversation": raise Problem(409, "mode_unavailable", "This mode is not available yet")
        snap = active(body.source_id)
        c = course(snap, body.course_id)
        try: lesson = snap.lesson(body.course_id, body.lesson_id)
        except SourceError: raise Problem(404, "not_found", "Lesson not found") from None
        if body.mode not in lesson["modes"] or (c["language"], c["instruction_language"]) != ("uk", "en"):
            raise Problem(409, "mode_unavailable", "This lesson/language mode is not available yet")
        try: prepared = snap.prepared_lesson(body.course_id, body.lesson_id)
        except SourceError: raise Problem(409, "mode_unavailable", "This lesson needs its mode-specific planner") from None
        template = dict(schema_version=1, kind="session_snapshot", learner_id=learner(request), session_id=body.session_id,
            revision=0, event_sequence=0, mode=body.mode, status="created", source=snap.source_ref(body.course_id, body.lesson_id),
            curriculum_snapshot=snap.curriculum, topic=None, language=c["language"], instruction_language=c["instruction_language"],
            learner_profile=store.learner(learner(request)), engine_state={"format_version": 1, "data": {}})
        result = call(coordinator.create, template, prepared, part={"combined": "all", "first_sitting": "1", "second_sitting": "2"}[body.activity])
        if coordinator.delivery_context: result = call(coordinator.presentation, learner(request), body.session_id)
        return _presentation(result)

    @app.get("/api/v1/sessions/{session_id}", response_model=m.Presentation)
    def status(request: Request, session_id: str, revision: int | None = Query(default=None, ge=0)):
        snapshot = owned(request, session_id, revision)
        result = call(coordinator.presentation, learner(request), session_id) if coordinator.delivery_context else snapshot["engine_state"]["data"]["presentation"]
        if revision is not None and result["revision"] != revision: raise Problem(409, "session_conflict", "Session changed; reload its status")
        return _presentation(result)

    @app.get("/api/v1/sessions/{session_id}/transcript", response_model=list[m.TranscriptTurn])
    def transcript(request: Request, session_id: str, revision: int | None = Query(default=None, ge=0)):
        owned(request, session_id, revision)
        return [m.TranscriptTurn(turn_id=t["turn_id"], role=t["role"], text=_plain(t["text"])) for t in store.projection(learner(request), session_id)["turns"]]

    @app.post("/api/v1/sessions/{session_id}/turns", response_model=m.Presentation)
    def turn(request: Request, session_id: str, body: m.Turn):
        owned(request, session_id)
        return _presentation(call(coordinator.submit, learner(request), session_id, body.request_id, expected_revision=body.expected_revision, text=body.text))

    @app.post("/api/v1/sessions/{session_id}/controls", response_model=m.Presentation)
    def control(request: Request, session_id: str, body: m.Control):
        owned(request, session_id)
        return _presentation(call(coordinator.control, learner(request), session_id, body.request_id, expected_revision=body.expected_revision,
                                  operation="stop" if body.operation == "finish" else body.operation))

    @app.post("/api/v1/sessions/{session_id}/audio", response_model=m.Presentation)
    async def upload(request: Request, session_id: str, request_id: str = Query(pattern=m.ID), expected_revision: int = Query(ge=0)):
        snapshot = owned(request, session_id)
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type not in {"audio/webm", "audio/ogg", "audio/wav", "audio/mp4"}: raise Problem(415, "unsupported_audio", "Unsupported recording format")
        data = await request.body()
        if not data: raise Problem(422, "empty_audio", "Recording is empty")
        with store._connection() as db:
            receipt = db.execute("SELECT expected_revision,stage FROM requests WHERE learner_id=? AND session_id=? AND request_id=?", (learner(request), session_id, request_id)).fetchone()
        replay = receipt is not None and receipt[0] == expected_revision and receipt[1] in {"committed", "delivered"}
        if not replay and (snapshot["revision"] != expected_revision or snapshot["status"] != "active"):
            raise Problem(409, "session_conflict", "Session changed; reload its status")
        if audio is None: raise Problem(503, "audio_unavailable", "Speech providers are not configured")
        return _presentation(await run_in_threadpool(call, audio.submit, learner(request), session_id, request_id,
                            expected_revision=expected_revision, data=data, media_type=media_type))

    @app.get("/api/v1/sessions/{session_id}/audio/{audio_id}")
    def recording(request: Request, session_id: str, audio_id: str, revision: int = Query(ge=0)):
        snapshot = owned(request, session_id)
        if snapshot["revision"] != revision: raise Problem(409, "session_conflict", "Session changed; reload its status")
        if not re.fullmatch(m.ID, audio_id): raise Problem(404, "not_found", "Audio not found")
        if audio is None: raise Problem(503, "audio_unavailable", "Speech providers are not configured")
        result = call(audio.read, learner(request), session_id, audio_id)
        if result is None: raise Problem(404, "not_found", "Audio not found")
        if getattr(result, "media_type", None) not in {"audio/mpeg", "audio/ogg", "audio/wav", "audio/webm", "audio/mp4"} or not isinstance(getattr(result, "data", None), bytes):
            raise Problem(502, "provider_failed", "Audio preparation failed")
        return Response(result.data, media_type=result.media_type, headers={"Content-Disposition": "inline"})

    @app.get("/api/v1/sessions/{session_id}/recognition/{request_id}", response_model=m.RecognitionView)
    def recognition(request: Request, session_id: str, request_id: str):
        owned(request, session_id)
        if not re.fullmatch(m.ID, request_id): raise Problem(404, "not_found", "Recognition not found")
        if not callable(getattr(audio, "recognition", None)): raise Problem(503, "audio_unavailable", "Recognition records are unavailable")
        result = call(audio.recognition, learner(request), session_id, request_id)
        if result is None: raise Problem(404, "not_found", "Recognition not found")
        return m.RecognitionView(request_id=result["request_id"], status=result["status"], text=_plain(result["text"]), reported_problem=result["reported_problem"])

    @app.post("/api/v1/sessions/{session_id}/recognition/{request_id}/report", response_model=m.Reported)
    def recognition_report(request: Request, session_id: str, request_id: str, body: m.Report):
        owned(request, session_id)
        if not re.fullmatch(m.ID, request_id): raise Problem(404, "not_found", "Recognition not found")
        if not callable(getattr(audio, "report_problem", None)): raise Problem(503, "audio_unavailable", "Recognition records are unavailable")
        if not call(audio.report_problem, learner(request), session_id, request_id): raise Problem(404, "not_found", "Recognition not found")
        return {"status": "reported", "revision": store.session(learner(request), session_id)["revision"]}

    # Built assets are operator-configured; API routes always take precedence.
    if assets is not None:
        app.mount("/", StaticFiles(directory=Path(assets), html=True, follow_symlink=False), name="web")
    return app
