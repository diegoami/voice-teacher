import hashlib
import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from voice_teacher.api import create_app
from voice_teacher.api.audio import Audio
from voice_teacher.content.registry import SourceRegistry, SourceSpec
from voice_teacher.practice.coordinator import Coordinator
from voice_teacher.providers import Judgement, Verdict
from voice_teacher.storage import Store
from voice_teacher.storage.migrations import APPLICATION_ID, V1, V2, V3, V4, VERSION

OPERATOR = "synthetic-operator-token-" + "a" * 32
ORIGIN = "http://teacher.test"


class Judge:
    def __init__(self): self.calls = 0; self.failure = None
    def __call__(self, item, text):
        self.calls += 1
        if self.failure: raise self.failure
        return Judgement(Verdict("accept", True, "", "", 0, ""), 0, {})


class FakeAudio:
    def __init__(self, coordinator): self.c = coordinator; self.recordings = {}; self.requests = {}; self.calls = 0; self.failure = None
    def submit(self, learner, session, request, *, expected_revision, data, media_type):
        from voice_teacher.storage.work import RequestConflict
        key = learner, session, request
        args = expected_revision, hashlib.sha256(data).hexdigest(), media_type
        if key in self.requests:
            old, result = self.requests[key]
            if old != args: raise RequestConflict("different recording")
            return result
        self.calls += 1
        if self.failure: raise self.failure
        result = self.c.submit(learner, session, request, expected_revision=expected_revision, text="Synthetic recognized greeting")
        aid = "audio-" + request
        self.recordings[learner, session, aid] = Audio(b"synthetic teacher audio", "audio/mpeg")
        result["delivery"] = {"audio_ids": [aid], "unsafe": "SYNTHETIC_PROVIDER_SECRET /private/internal"}
        self.requests[key] = args, result
        return result
    def read(self, learner, session, audio_id):
        if self.failure: raise self.failure
        return self.recordings.get((learner, session, audio_id))


@pytest.fixture
def system(tmp_path):
    store = Store(tmp_path / "private")
    for name in ["alice", "bob"]: store.save_learner(name, {"level": "SYNTHETIC_PRIVATE_PROFILE"})
    root = tmp_path / "content"; root.mkdir()
    value = json.loads((Path(__file__).resolve().parents[1] / "contracts/fixtures/guided.json").read_text())
    value["courses"][0]["items"][0]["text"] = {"display": "HIDDEN TARGET", "speech": "HIDDEN TÁRGET"}
    lesson = value["courses"][0]["lessons"][0]
    lesson["repetition_item_ids"] = ["hello"]
    (root / "voice-teacher.json").write_text(json.dumps(value))
    registry = SourceRegistry(store)
    registry.register(SourceSpec("synthetic-alpha", "Synthetic", str(root), allow_dirty=True))
    registry.refresh("synthetic-alpha")
    judge = Judge(); coordinator = Coordinator(store, judge, clock=lambda: 0)
    audio = FakeAudio(coordinator)
    now = [1000.0]
    app = create_app(store, coordinator, operator_token=OPERATOR, origin=ORIGIN, audio=audio,
                     clock=lambda: now[0], max_json_bytes=32768, max_audio_bytes=64)
    client = TestClient(app, base_url=ORIGIN)
    def grant(learner):
        code = client.post("/api/v1/operator/pairing-codes", headers=bearer(OPERATOR), json={"learner_id": learner, "label": "Synthetic client"}).json()["code"]
        return client.post("/api/v1/pair", json={"code": code}).json()
    return dict(store=store, app=app, client=client, grant=grant, alice=grant("alice"), bob=grant("bob"),
                judge=judge, audio=audio, coordinator=coordinator, now=now, root=root)


def bearer(token): return {"Authorization": "Bearer " + token}


def start(s, name="one", identity="alice", **overrides):
    body = dict(session_id=name, source_id="synthetic-alpha", course_id="basics", lesson_id="lesson-1",
                activity="second_sitting", mode="guided_conversation")
    body.update(overrides)
    return s["client"].post("/api/v1/sessions", headers=bearer(s[identity]["token"]), json=body)


def post(s, path, body, identity="alice"):
    return s["client"].post(path, headers=bearer(s[identity]["token"]), json=body)


def test_fake_session_lifecycle_retry_and_hidden_response_fields(system):
    s = system; client = s["client"]; headers = bearer(s["alice"]["token"])
    for path in ["/api/v1/sources", "/api/v1/sources/synthetic-alpha/courses", "/api/v1/sources/synthetic-alpha/courses/basics/lessons"]:
        r = client.get(path, headers=headers)
        assert r.status_code == 200
        assert "HIDDEN" not in r.text and "target" not in r.text
        assert str(s["root"]) not in r.text
    response = start(s); assert response.status_code == 201
    assert "HIDDEN" not in response.text and "SYNTHETIC_PRIVATE" not in response.text
    assert "targets" not in response.text and "engine_state" not in response.text
    assert response.json()["revision"] == 0
    request = dict(request_id="turn-one", expected_revision=0, text="Synthetic answer")
    accepted = post(s, "/api/v1/sessions/one/turns", request)
    assert accepted.status_code == 200
    assert post(s, "/api/v1/sessions/one/turns", request).json() == accepted.json()
    assert s["judge"].calls == 1
    for operation, revision, status in [("resume", 1, "active"), ("pause", 2, "paused"), ("resume", 3, "active"), ("finish", 4, "finished")]:
        result = post(s, "/api/v1/sessions/one/controls", dict(request_id=f"{operation}-{revision}", expected_revision=revision, operation=operation))
        assert result.status_code == 200, result.text
        assert result.json()["status"] == status
    assert post(s, "/api/v1/sessions/one/turns", dict(request_id="after-finish", expected_revision=5, text="late")).status_code == 409
    transcript = client.get("/api/v1/sessions/one/transcript", headers=headers)
    assert transcript.status_code == 200
    assert "Synthetic answer" in transcript.text
    assert "\u0301" not in transcript.text
    assert client.get("/api/v1/sessions/one", headers=headers).json()["status"] == "finished"
    # Request receipts remain replayable even after later controls finish the session.
    assert post(s, "/api/v1/sessions/one/turns", request).json() == accepted.json()


def test_unauthenticated_wrong_learner_and_stale_requests(system):
    s = system; assert start(s).status_code == 201
    for path in ["/api/v1/sources", "/api/v1/sessions/one", "/api/v1/sessions/one/transcript", "/api/v1/sessions/one/audio/unknown?revision=0"]:
        assert s["client"].get(path).status_code == 401
        if "/sessions/" in path:
            assert s["client"].get(path, headers=bearer(s["bob"]["token"])).status_code == 404
    body = dict(request_id="r1", expected_revision=0, text="answer")
    assert post(s, "/api/v1/sessions/one/turns", body, "bob").status_code == 404
    assert post(s, "/api/v1/sessions/one/turns", body).status_code == 200
    for path in ["/api/v1/sessions/one?revision=0", "/api/v1/sessions/one/transcript?revision=0"]:
        assert s["client"].get(path, headers=bearer(s["alice"]["token"])).status_code == 409
    assert post(s, "/api/v1/sessions/one/turns", {**body, "request_id": "stale"}).status_code == 409
    assert post(s, "/api/v1/sessions/one/controls", dict(request_id="stale-control", expected_revision=0, operation="finish")).status_code == 409
    assert s["judge"].calls == 1
    assert start(s).status_code == 409
    assert start(s, name="another", learner_id="bob").status_code == 422


def test_pairing_single_use_expiry_revocation_and_hash_only_storage(system):
    s = system; client = s["client"]
    r = client.post("/api/v1/operator/pairing-codes", headers=bearer(OPERATOR), json={"learner_id": "alice", "label": "phone"})
    code = r.json()["code"]
    paired = client.post("/api/v1/pair", json={"code": code})
    assert paired.status_code == 200
    assert client.post("/api/v1/pair", json={"code": code}).status_code == 401
    token = paired.json()["token"]
    with s["store"]._connection() as c:
        text = repr([tuple(row) for row in c.execute("SELECT * FROM clients")])
        assert token not in text and OPERATOR not in text and code not in text
    # A fresh API process/object uses the persistent grant, without storing plaintext.
    restarted = TestClient(create_app(Store(s["store"].path.parent), s["coordinator"], operator_token=OPERATOR,
        origin=ORIGIN, clock=lambda: s["now"][0]), base_url=ORIGIN)
    assert restarted.get("/api/v1/sources", headers=bearer(token)).status_code == 200
    assert client.delete("/api/v1/operator/clients/" + paired.json()["client_id"], headers=bearer(OPERATOR)).status_code == 204
    assert restarted.get("/api/v1/sources", headers=bearer(token)).status_code == 401
    code = client.post("/api/v1/operator/pairing-codes", headers=bearer(OPERATOR), json={"learner_id": "alice", "label": "expired"}).json()["code"]
    s["now"][0] += 301
    assert client.post("/api/v1/pair", json={"code": code}).status_code == 401
    s["now"][0] += 31 * 86400
    assert client.get("/api/v1/sources", headers=bearer(s["alice"]["token"])).status_code == 401


def test_operator_config_and_origin_protections(system):
    s = system; client = s["client"]; headers = bearer(s["alice"]["token"])
    assert client.post("/api/v1/operator/pairing-codes", headers=headers, json={"learner_id": "bob", "label": "evil"}).status_code == 403
    assert client.put("/api/v1/operator/learners/bob", headers=headers, json={"level": "changed"}).status_code == 403
    assert client.put("/api/v1/operator/sources/alpha", headers=headers, json={}).status_code == 403
    assert client.get("/api/v1/sessions/anything", headers=bearer(OPERATOR)).status_code == 403
    assert client.put("/api/v1/operator/learners/new", headers=bearer(OPERATOR), json={"level": "beginner"}).status_code == 204
    for origin in ["https://evil.invalid", "null", ORIGIN + "/"]:
        assert client.get("/api/v1/sources", headers={**headers, "Origin": origin}).status_code == 403
        assert client.post("/api/v1/pair", headers={"Origin": origin}, json={"code": "x" * 43}).status_code == 403
    assert client.get("/api/v1/sources", headers={**headers, "Origin": ORIGIN}).status_code == 200
    assert client.get("/api/v1/sources", headers={**headers, "Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/v1/sources", headers={**headers, "Host": "evil.invalid"}).status_code == 400
    assert client.get("/api/v1/sources?token=" + s["alice"]["token"]).status_code == 401
    client.cookies.set("token", s["alice"]["token"])
    assert client.get("/api/v1/sources").status_code == 401
    r = client.get("/api/v1/sources", headers=headers)
    assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"
    assert "access-control-allow-origin" not in r.headers


def test_audio_acl_limits_retry_and_sanitized_metadata(system):
    s = system; start(s)
    url = "/api/v1/sessions/one/audio?request_id=voice-one&expected_revision=0"
    headers = {**bearer(s["alice"]["token"]), "Content-Type": "audio/webm"}
    assert s["client"].post(url, headers={**headers, **bearer(s["bob"]["token"])}, content=b"recording").status_code == 404
    assert s["client"].post(url, headers=headers, content=b"").status_code == 422
    assert s["client"].post(url, headers={**headers, "Content-Type": "text/plain"}, content=b"recording").status_code == 415
    assert s["client"].post(url, headers=headers, content=b"x" * 65).status_code == 413
    result = s["client"].post(url, headers=headers, content=b"recording")
    assert result.status_code == 200, result.text
    assert "SYNTHETIC_PROVIDER_SECRET" not in result.text and "/private/" not in result.text
    assert s["client"].post(url, headers=headers, content=b"recording").json() == result.json()
    assert s["audio"].calls == 1 and s["judge"].calls == 1
    assert s["client"].post(url, headers=headers, content=b"different").status_code == 409
    audio_url = "/api/v1/sessions/one/audio/" + result.json()["audio_ids"][0]
    assert s["client"].get(audio_url + "?revision=0", headers=headers).status_code == 409
    assert s["client"].get(audio_url + "?revision=1", headers=bearer(s["bob"]["token"])).status_code == 404
    sound = s["client"].get(audio_url + "?revision=1", headers=headers)
    assert sound.status_code == 200 and sound.content == b"synthetic teacher audio"
    assert sound.headers["content-type"] == "audio/mpeg" and sound.headers["cache-control"] == "no-store"
    assert s["client"].post(url.replace("voice-one", "stale"), headers=headers, content=b"recording").status_code == 409
    # Knowing an audio ID does not grant access via another owned session.
    assert start(s, name="one", identity="bob").status_code == 201
    assert s["client"].get(audio_url + "?revision=0", headers=bearer(s["bob"]["token"])).status_code == 404
    assert start(s, name="two").status_code == 201
    assert s["client"].get(audio_url.replace("/one/", "/two/") + "?revision=0", headers=headers).status_code == 404


def test_chunked_and_json_upload_limits_invalid_fields_and_errors(system):
    s = system; client = s["client"]; start(s)
    headers = {**bearer(s["alice"]["token"]), "Content-Type": "audio/webm"}
    def chunks():
        yield b"a" * 40
        yield b"b" * 40
    assert client.post("/api/v1/sessions/one/audio?request_id=x&expected_revision=0", headers=headers, content=chunks()).status_code == 413
    assert s["audio"].calls == 0
    assert client.post("/api/v1/sessions", headers=bearer(s["alice"]["token"]), content=b"x" * 32769).status_code == 413
    r = post(s, "/api/v1/sessions/one/turns", dict(request_id="SYNTHETIC_SECRET!", expected_revision="private", text="x"))
    assert r.status_code == 422 and "SYNTHETIC_SECRET" not in r.text and "private" not in r.text
    s["judge"].failure = RuntimeError("SYNTHETIC_PROVIDER_SECRET /private/credentials")
    r = post(s, "/api/v1/sessions/one/turns", dict(request_id="judge-fail", expected_revision=0, text="answer"))
    assert r.status_code == 502 and r.json()["error"]["code"] == "provider_failed"
    assert "SYNTHETIC_PROVIDER_SECRET" not in r.text and "/private/" not in r.text
    assert s["store"].session("alice", "one")["revision"] == 0
    s["audio"].failure = RuntimeError("SYNTHETIC_PROVIDER_SECRET")
    r = client.get("/api/v1/sessions/one/audio/missing?revision=0", headers=headers)
    assert r.status_code == 502 and "SYNTHETIC_PROVIDER_SECRET" not in r.text


def test_operator_source_configuration_and_unavailable_modes(system):
    s = system; client = s["client"]
    body = dict(source_id="synthetic-alpha", name="Renamed", checkout=str(s["root"]), allow_dirty=True)
    r = client.put("/api/v1/operator/sources/synthetic-alpha", headers=bearer(OPERATOR), json=body)
    assert r.status_code == 200 and str(s["root"]) not in r.text
    r = client.put("/api/v1/operator/sources/synthetic-alpha", headers=bearer(OPERATOR), json={**body, "manifest": "../escape"})
    assert r.status_code == 422 and str(s["root"]) not in r.text and "escape" not in r.text
    assert start(s, mode="repetition").status_code == 409
    assert start(s, lesson_id="missing").status_code == 404
    assert start(s, source_id="missing").status_code == 404


def test_same_origin_assets_and_typed_schema(system, tmp_path):
    s = system; assets = tmp_path / "dist"; assets.mkdir(); (assets / "index.html").write_text("Synthetic app")
    client = TestClient(create_app(s["store"], s["coordinator"], operator_token=OPERATOR, origin=ORIGIN, assets=assets, clock=lambda: s["now"][0]), base_url=ORIGIN)
    assert client.get("/").text == "Synthetic app"
    assert client.get("/api/v1/sources").status_code == 401
    assert client.get("/api/v1/unknown", headers=bearer(s["alice"]["token"])).status_code == 404
    assert "Presentation" in s["app"].openapi()["components"]["schemas"]


def test_pairing_race_consumes_code_once_and_header_ambiguity_is_rejected(system):
    from concurrent.futures import ThreadPoolExecutor
    s = system; client = s["client"]
    code = client.post("/api/v1/operator/pairing-codes", headers=bearer(OPERATOR), json={"learner_id": "alice", "label": "race"}).json()["code"]
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: client.post("/api/v1/pair", json={"code": code}).status_code, range(2)))
    assert sorted(results) == [200, 401]
    token = s["alice"]["token"]
    assert client.get("/api/v1/sources", headers=[("Authorization", "Bearer " + token), ("Authorization", "Bearer " + token)]).status_code == 401
    assert client.get("/api/v1/sources", headers=[("Origin", ORIGIN), ("Origin", ORIGIN), ("Authorization", "Bearer " + token)]).status_code == 403


def test_audio_unconfigured_invalid_responses_and_planned_model_exposure(system):
    s = system
    path = s["root"] / "voice-teacher.json"
    value = json.loads(path.read_text())
    value["courses"][0]["lessons"][0]["modes"].append("repetition")
    path.write_text(json.dumps(value))
    SourceRegistry(s["store"]).refresh("synthetic-alpha")
    r = start(s, activity="combined", routine="combined")
    assert r.status_code == 201
    assert "HIDDEN TARGET" in r.text  # A deliberately spoken model is visible.
    assert "\u0301" not in r.text and "curriculum_snapshot" not in r.text
    client = TestClient(create_app(s["store"], s["coordinator"], operator_token=OPERATOR, origin=ORIGIN,
        clock=lambda: s["now"][0]), base_url=ORIGIN)
    headers = {**bearer(s["alice"]["token"]), "Content-Type": "audio/webm"}
    assert client.post("/api/v1/sessions/one/audio?request_id=voice&expected_revision=0", headers=headers, content=b"recording").status_code == 503
    assert s["store"].session("alice", "one")["revision"] == 0
    assert post(s, "/api/v1/sessions/one/turns", dict(request_id="empty", expected_revision=0, text="   ")).status_code == 422
    s["audio"].recordings["alice", "one", "invalid"] = Audio(b"bad", "text/html")
    r = s["client"].get("/api/v1/sessions/one/audio/invalid?revision=0", headers=headers)
    assert r.status_code == 502 and "bad" not in r.text


def test_authentication_material_is_excluded_from_progress_archive(system, tmp_path):
    from voice_teacher.progress import Archive
    from voice_teacher.api.auth import digest
    s = system; start(s)
    destination = tmp_path / "progress"; destination.mkdir()
    archive = Archive(destination)
    archive.export(s["store"])
    data = b"".join(p.read_bytes() for p in (destination / archive.NAMESPACE).glob("*.json"))
    for token in [OPERATOR, s["alice"]["token"], s["bob"]["token"]]:
        assert token.encode() not in data and digest(token).encode() not in data
    assert b"pairing_codes" not in data and b"token_hash" not in data


@pytest.mark.parametrize("failure", [False, True])
def test_v4_auth_migration_is_atomic_and_preserves_existing_state(tmp_path, monkeypatch, failure):
    import voice_teacher.storage.sqlite as implementation
    directory = tmp_path / "data"; directory.mkdir(); path = directory / "voice-teacher.sqlite"
    with sqlite3.connect(path) as c:
        for sql in (*V1, *V2, *V3, *V4): c.execute(sql)
        c.execute(f"PRAGMA application_id={APPLICATION_ID}"); c.execute("PRAGMA user_version=4")
        c.execute("INSERT INTO learners VALUES ('preserved','{}')")
    if failure:
        monkeypatch.setattr(implementation, "V5", (*implementation.V5, "SELECT bad_auth_migration()"))
        with pytest.raises(sqlite3.OperationalError): Store(directory)
        with sqlite3.connect(path) as c:
            assert c.execute("PRAGMA user_version").fetchone()[0] == 4
            assert c.execute("SELECT name FROM sqlite_master WHERE name='clients'").fetchall() == []
    else:
        store = Store(directory)
        assert store.learner("preserved") == {}
        with store._connection() as c: assert c.execute("PRAGMA user_version").fetchone()[0] == VERSION


def test_browser_pairing_exposes_only_verified_learner_identity(system):
    s = system; client = s["client"]
    assert s["alice"]["learner_id"] == "alice"
    assert client.get("/api/v1/identity", headers=bearer(s["alice"]["token"])).json() == {"learner_id": "alice"}
    assert client.get("/api/v1/identity", headers=bearer(s["bob"]["token"])).json() == {"learner_id": "bob"}
    assert client.get("/api/v1/identity").status_code == 401
    assert client.get("/api/v1/identity", headers=bearer(OPERATOR)).status_code == 403
    client.delete("/api/v1/operator/clients/" + s["alice"]["client_id"], headers=bearer(OPERATOR))
    assert client.get("/api/v1/identity", headers=bearer(s["alice"]["token"])).status_code == 401


def test_saved_status_can_be_read_without_speech_for_control_recovery(system):
    s = system; client = s["client"]; headers = bearer(s["alice"]["token"])
    assert start(s).status_code == 201
    def unavailable(*args): raise RuntimeError("SYNTHETIC_SECRET speech unavailable")
    s["coordinator"].delivery_context = unavailable
    assert client.get("/api/v1/sessions/one", headers=headers).status_code == 502
    state = client.get("/api/v1/sessions/one?prepare_audio=false", headers=headers)
    assert state.status_code == 200 and state.json()["revision"] == 0 and state.json()["audio_ids"] == []
    stopped = post(s, "/api/v1/sessions/one/controls", dict(request_id="finish", expected_revision=0, operation="finish"))
    assert stopped.status_code == 502  # State committed before delivery failed.
    saved = client.get("/api/v1/sessions/one?prepare_audio=false", headers=headers)
    assert saved.status_code == 200 and saved.json()["status"] == "finished" and saved.json()["done"]
    assert "SYNTHETIC_SECRET" not in saved.text and "SYNTHETIC_PRIVATE" not in saved.text
    assert client.get("/api/v1/sessions/one?prepare_audio=false", headers=bearer(s["bob"]["token"])).status_code == 404
