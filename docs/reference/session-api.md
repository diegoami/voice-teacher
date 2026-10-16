# Authenticated personal-client API

T09 adds `voice_teacher.api.create_app`, a FastAPI ASGI application around the
durable coordinator and validated source registry. Importing it creates no
providers and reads no credentials. Construct it with one runtime Store,
Coordinator and operator token supplied out of band. `uvicorn` is included for
same-origin local serving; [T10](voice-pipeline.md) supplies production speech/judging wiring.

```python
from voice_teacher.api import create_app

app = create_app(store, coordinator,
                 operator_token=operator_token_from_private_configuration,
                 origin="http://localhost:8000",
                 audio=durable_audio_gateway, assets="/path/to/built/web")
```

`audio` and `assets` are optional. Audio endpoints return a typed 503 error when
no gateway is configured. An embedding server can serve `app` through Uvicorn
on `127.0.0.1:8000`. Use HTTPS for access outside loopback development; T28 owns
phone-access deployment. The exact configured origin has no trailing slash and
must match the browser origin and request Host. No proxy-header trust is enabled
here; deployment must explicitly configure the trusted reverse proxy.

## Pairing and identities

Use a cryptographically random operator token of at least 32 characters, provided
through private configuration/environment, never a URL or source file. The
operator provisions a learner and issues an expiring pairing code. The client
exchanges the code once for an opaque bearer token, then sends
`Authorization: Bearer <token>` on every API request. Codes/tokens have 256 bits
of generated entropy; codes expire after five minutes, clients after 30 days.
SQLite stores hashes only, with learner binding and expiry. Concurrent exchanges
consume a code once. Grant revocation persists across restart. Bootstrap token
rotation does not silently change existing clients' learner identities.

The operator identity accesses only `/api/v1/operator/` endpoints; a paired
learner accesses only the ordinary API. Being operator does not grant implicit
learner-session access. Every session lookup uses the learner from the token;
clients cannot supply or override learner ownership. Unknown/wrong-owner sessions
return the same 404. Session IDs are client-generated stable IDs scoped by learner.
Creating an existing ID returns 409; it never replaces a session.

Cookies and query-string tokens are not accepted or set. Every supplied Origin
must exactly match configuration; cross-site Fetch Metadata, duplicate auth or
Origin headers and unexpected Hosts are rejected. Requests without Origin are
allowed for authenticated non-browser clients. Pair exchange receives the same
Host/origin/body protections. No permissive CORS middleware is enabled. API and
audio responses have `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`.
Tokens and pairing responses must stay out of telemetry and exported progress;
T15 owns the client token lifecycle and T26 broader privacy verification.

## Endpoints

All paths below start with `/api/v1`. JSON input models reject unknown fields and
wrong JSON types. Public response models are explicit allowlists. OpenAPI types
are available programmatically via `app.openapi()`; HTTP documentation/schema
routes are disabled. `/healthz` exposes only `{"status":"ok"}` without identity.

| Method/path | Identity | Behaviour |
| --- | --- | --- |
| `POST /pair` | Pair code | Exchange `{code}` for `{token,client_id,expires_at}` |
| `PUT /operator/learners/{id}` | Operator | Provision/update `{level}` without changing existing grants |
| `POST /operator/pairing-codes` | Operator | Issue code for `{learner_id,label}` |
| `DELETE /operator/clients/{id}` | Operator | Revoke a grant |
| `PUT /operator/sources/{id}` | Operator | Register typed SourceSpec fields and refresh; return safe metadata |
| `GET /sources` | Learner | Names, IDs, active versions and availability |
| `GET /sources/{source}/courses` | Learner | Course IDs, titles and languages |
| `GET /sources/{source}/courses/{course}/lessons` | Learner | Lesson metadata and authored/available modes |
| `POST /sessions` | Learner | Create pinned session with `{session_id,source_id,course_id,lesson_id,mode,activity}` |
| `GET /sessions/{id}` | Owner | Latest saved presentation |
| `GET /sessions/{id}/transcript` | Owner | Plain visible turns; no internal judge/engine state |
| `POST /sessions/{id}/turns` | Owner | `{request_id,expected_revision,text}` |
| `POST /sessions/{id}/controls` | Owner | `{request_id,expected_revision,operation}`; pause/resume/finish |
| `POST /sessions/{id}/audio` | Owner | Bounded binary recording, query request_id/expected_revision |
| `GET /sessions/{id}/audio/{audio_id}?revision=N` | Owner | Session-bound audio at the current revision |

Progress-destination configuration is not exposed yet. Future administrative
routes must remain in the operator namespace; no learner request can configure
an implicit destination or change learner ownership.

Current planners support [guided activities](guided-activities.md) and
[independent repetition](repetition.md), including partial lessons and explicitly
configured language profiles. Guided practice defaults to no opening repetition;
`routine=combined` adds authored review and modelling. `activity` selects both
sittings or `first_sitting` / `second_sitting`. Cards, spoken tasks and block size
are independently configurable. [Free conversation](free-dialogue.md) is available when explicitly configured,
with an optional complete lesson reference or a source-free topic.
Source selection does not apply historical personal introduction/settings.
Source updates cannot alter an existing pinned session.

A presentation contains `session_id`, `request_id`, `revision`, `status`, `done`,
`card`, `teacher: [{text,kind}]`, `audio_ids` and nullable guided `activity` metadata. Catalogue responses omit curriculum
items, targets, goals, private context and internal paths. Presentations expose
only actually planned teacher speech, with plain display text rather than stress
notation; deliberately spoken models/corrections are visible when offered.
Private snapshots, target alternatives, provider metadata and keys never become
generic response dictionaries. Retrying the same completed turn/control request
returns its original saved result, even after later revisions; a different request
at a stale revision returns 409. Status/transcript reads optionally accept
`?revision=N` and reject stale versions with 409; omitting it explicitly fetches
the latest owned state for resume/history. Audio reads require the current
revision. Finish maps to the coordinator's durable stop.

## Audio and errors

Recording uploads accept `audio/webm`, `audio/ogg`, `audio/wav`, or `audio/mp4`.
Defaults are 8 MiB audio and 32 KiB JSON, checked before parsing for both declared
and streamed bodies. Empty audio, unsupported formats, invalid IDs/revisions and
wrong owners are rejected before provider work. Downloads require current session
revision and opaque IDs, not filesystem paths. The injected AudioGateway receives
the authenticated learner/session on both submit/read and must bind every artifact
to that pair; knowing an ID is insufficient. T10 implements durable recognition,
synthesis and cache/retry stages behind this tested transport interface.

Errors have `{error: {code, message}}`. Expected statuses are 401 unauthenticated,
403 forbidden/origin, 404 unavailable ownership/resource, 409 session conflict or
mode unavailable, 413 body too large, 415 unsupported audio, 422 invalid request,
502 provider failure and 503 audio unavailable. Provider exceptions and validation
input values are never echoed. On a provider failure retry the same request ID;
T06 preserves accepted/judged stages. No confidence score or pronunciation inference
is invented at this HTTP layer.

SQLite v5 adds hashed pairing/client grants in one transaction. No authentication
material is added to practice events. Tests cover migration failure rollback,
pairing concurrency/expiry/revocation/restart, origins/Hosts, ownership and stale
updates, hidden fields, fake audio ACL/replay, streamed limits, provider sanitization,
typed error shapes and same-origin assets. No live provider is contacted:

```bash
uv run pytest tests/api -q
uv run pytest tests -q
```

T15 adds paired `learner_id` to the pairing response and authenticated
`GET /api/v1/identity` returning only that ID for the
[web app](web-app.md). Operator tokens cannot use this client endpoint.

T10 adds saved first-reply audio recovery through session status, plus owner-only
recognition read/report endpoints described in [voice-pipeline.md](voice-pipeline.md).
A recognition report saves a portable annotation and returns the new revision,
while preserving the original evidence and native lesson state.

T13 adds [independent repetition](repetition.md), optional pre-model recall,
authenticated review candidate IDs, and bounded lesson/queue item selection.

T16 adds owner-only `GET /sessions/{id}?prepare_audio=false` to read the saved
presentation without preparing speech. The default stays `true`. Finish recovery
uses this path so a speech outage cannot prevent confirming committed state;
all ownership, revision and response-field protections still apply.

T20 adds optional `topic`, target/instruction language and `correction_style` for
free conversation. Source-free starts omit the lesson triple; other modes still
require it. The confirmed correction default is `light_immediate`.

### Owned request receipts (T17)

`GET /api/v1/sessions/{session_id}/requests/{request_id}` is a read-only,
owner-bound receipt lookup. It returns only `request_id`, `status` (`pending`,
`ready`, or `cancelled`) and `revision` (accepted next revision for `ready`,
otherwise null). Unknown requests and other owners' sessions return 404. It
makes no speech/model call and exposes no input, transcript or judgement.
A 404 can precede durable coordinator acceptance (for example during speech
recognition); a client may recover its original recording with the same ID
and bytes. It must not manufacture another attempt. A ready receipt confirms
that original attempt even if later controls changed the latest presentation;
clients then load the current owned session, rather than replaying old state.

### History and item practice (T18)

`GET /api/v1/progress?limit=50` lists recent owned sessions and separate pinned
course coverage. `GET /api/v1/sessions/{id}/evidence?offset=0&limit=50` returns
owned observation details and accepted supporting-turn references. Response
models are closed field allowlists; no private engine/profile or future answers
are serialized. The [progress view contract](progress-views.md) defines coverage,
limits, original/later provenance and saved/exported/pushed states. Optional
`create_app(..., progress_sync=worker)` reads the configured same-store GitSync
status without selecting a destination or starting synchronization.

### Personal observations and review (T21)

Feedback-enabled free conversations retain structured post-attempt observations
with actual learner-turn references; correction preference controls their delivery.
`GET /review-targets` lists owned explicit personal choices. `POST
/sessions/{id}/review-targets` promotes an owned observation under a revision and
stable request ID. `POST /sessions` supports repetition with
`personal_target_ids: [id]` (one or two) and optional `recall_before_model`, without
repository references. These paths compile private snapshots and never change a
lesson repository. See the [feedback contract](free-feedback.md) for bounds,
held feedback, recognition disputes, durable replay and provenance.
