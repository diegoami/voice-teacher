"""The voice lesson as a web app: Starlette, one session in memory, everything under a secret path.

A learner turn is one request: audio in, speech recognition, the session's
`hear`, synthesis of each line the teacher says, JSON out with an audio URL per
line. The speech services and the judge are injected, so tests run offline.
"""

from __future__ import annotations

import json
import re
import secrets
import struct
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Callable

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from .package import Lesson, plain
from .session import REPEAT_PLEASE, Say, Session
from .stress import Stresser
from .voice import STT_USD_PER_HOUR, TTS_USD_PER_1000_CHARS, ProviderError, Transcript, cache_key

PAGE = Path(__file__).with_name("app.html")
MAX_UPLOAD = 10_000_000  # bytes; a spoken turn is a few tens of kilobytes
MIN_UPLOAD = 200  # bytes; smaller is an empty recording
NO_STORE = {"Cache-Control": "no-store"}

SERVICE_WORKER = """// Network first for the page shell, never for the lesson itself (API and audio).
const SHELL = 'shell-v1';
self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || !/\\/(index\\.html|manifest\\.webmanifest|icon[^/]*)?$/.test(url.pathname)) return;
  e.respondWith(fetch(e.request).then(r => {
    const copy = r.clone();
    caches.open(SHELL).then(c => c.put(e.request, copy));
    return r;
  }).catch(() => caches.match(e.request)));
});
"""


@lru_cache(maxsize=2)
def icon_png(size: int) -> bytes:
    """A plain app icon (a white ring on blue) written without an imaging library."""
    bg, fg = (31, 111, 235), (255, 255, 255)
    centre, outer, inner = size / 2, size * 0.30, size * 0.17
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            d = ((x + 0.5 - centre) ** 2 + (y + 0.5 - centre) ** 2) ** 0.5
            row += bytes(fg if inner <= d <= outer else bg)
        rows.append(bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + chunk(b"IEND", b""))


ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" fill="#1f6feb"/>
<circle cx="256" cy="256" r="125" fill="none" stroke="#fff" stroke-width="44"/></svg>"""


def manifest(base: str) -> dict:
    return {
        "name": "Voice teacher", "short_name": "Voice teacher", "start_url": base, "scope": base,
        "display": "fullscreen", "orientation": "portrait", "background_color": "#1f6feb",
        "theme_color": "#1f6feb",
        "icons": [
            {"src": base + "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": base + "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
            {"src": base + "icon.svg", "sizes": "any", "type": "image/svg+xml"},
        ],
    }


class Speaker:
    """Synthesis with a disk cache: a fixed line is paid for once."""

    def __init__(self, synthesise: Callable[[str], bytes], folder: Path):
        self.synthesise = synthesise
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        return self.folder / f"{key}.mp3"

    def speak(self, text: str) -> tuple[str, bool]:
        """(audio id, served from the cache)."""
        key = cache_key(text)
        if self.path(key).exists():
            return key, True
        audio = self.synthesise(text)
        temporary = self.path(key).with_suffix(f".{secrets.token_hex(3)}.tmp")
        temporary.write_bytes(audio)
        temporary.replace(self.path(key))
        return key, False


class Lessons:
    """The one running lesson and the work of a turn."""

    def __init__(self, lesson: Lesson, token: str, transcribe, speaker: Speaker, judge_factory, save, clock,
                 recordings: Path | None = None, part: str = "all"):
        self.lesson, self.token, self.part = lesson, token, part
        self.name = lesson.part if part == "all" else f"{lesson.part}-p{part}"  # 4B, 4B-p1, 4B-p2
        self.recordings = recordings  # where the learner's turns are kept (local, git-ignored); None: not kept
        self.transcribe, self.speaker, self.judge_factory, self.save, self.clock = \
            transcribe, speaker, judge_factory, save, clock
        self.stresser = Stresser(lesson)
        self.session: Session | None = None
        self.id = ""
        self.saved = True
        self.lock = threading.Lock()  # a double tap must not run two turns at once

    def finish_old(self) -> None:
        """Keep the log of a lesson that was abandoned by starting another one."""
        if self.session is not None and not self.saved and any(e["event"] == "learner" for e in self.session.log):
            self._save()

    def _save(self) -> None:
        self.saved = True
        self.save(self.session, self.name)

    def start(self) -> dict:
        self.finish_old()
        started = self.clock()
        self.session = Session(self.lesson, self.judge_factory(self.lesson), part=self.part)
        self.id, self.saved = secrets.token_hex(4), False
        self.started_at = time.strftime("%Y%m%d-%H%M%S")
        says = self.session.start()
        turns, tts = self.speech(says)
        self.session._log("timing", turn=0, stt_seconds=None, judge_seconds=0, tts_seconds=tts["seconds"],
                          total_seconds=round(self.clock() - started, 3),
                          cost_usd={"stt": 0, "judge": 0, "tts": tts["cost"], "total": tts["cost"]},
                          tts_chars_billed=tts["chars"])
        return self.reply(turns, session=self.id)

    def turn(self, audio: bytes, content_type: str) -> dict:
        started, session = self.clock(), self.session
        mark = len(session.log)
        recording = self.keep(audio, content_type)
        t0 = self.clock()
        heard: Transcript = self.transcribe(audio, content_type)
        stt_seconds = round(self.clock() - t0, 3)
        if heard.text:
            says = session.hear(heard.text)
            retry = False
        else:  # nothing recognised: ask again without touching the lesson
            says, retry = [Say(REPEAT_PLEASE, "repeat")], True
        judged = [e for e in session.log[mark:] if e["event"] == "judge"]
        turns, tts = self.speech(says)
        stt_cost = heard.audio_seconds / 3600 * STT_USD_PER_HOUR if heard.audio_seconds is not None else None
        judge_cost = sum((e["usage"].get("cost_usd") or 0) for e in judged)
        costs = {"stt": stt_cost, "judge": judge_cost, "tts": tts["cost"]}
        costs["total"] = round(sum(v or 0 for v in costs.values()), 6)
        session._log("timing", turn=sum(e["event"] == "learner" for e in session.log), heard=heard.text,
                     stt_seconds=stt_seconds, judge_seconds=round(sum(e["seconds"] for e in judged), 3),
                     tts_seconds=tts["seconds"], total_seconds=round(self.clock() - started, 3),
                     audio_seconds=heard.audio_seconds, cost_usd=costs, tts_chars_billed=tts["chars"],
                     retry=retry, recording=recording)
        if session.done:
            self._save()
        return self.reply(turns, heard=heard.text, retry=retry)

    def keep(self, audio: bytes, content_type: str) -> str | None:
        """Save the learner's turn so recognition and pronunciation can be checked later; returns its name."""
        if self.recordings is None:
            return None
        number = sum(e["event"] == "timing" and bool(e.get("turn")) for e in self.session.log) + 1
        ext = {"audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}.get(
            content_type.split(";")[0].strip(), "webm")
        folder = self.recordings / f"{self.name}-{self.started_at}-{self.id}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{number:03d}.{ext}"
        path.write_bytes(audio)
        return str(path.relative_to(self.recordings))

    def stop(self) -> dict:
        session = self.session
        if session.done:
            return self.reply([])
        says = session.hear("стоп")
        turns, tts = self.speech(says)
        session._log("timing", turn=None, stopped=True, tts_seconds=tts["seconds"], tts_chars_billed=tts["chars"],
                     cost_usd={"tts": tts["cost"]})
        self._save()
        return self.reply(turns)

    def speech(self, says: list[Say]) -> tuple[list[dict], dict]:
        """Synthesise each line (marked), the new ones in parallel. Display text is plain."""
        marked = [self.stresser.mark(s.text) for s in says]
        started = self.clock()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(self.speaker.speak, marked))
        chars = sum(len(m) for m, (_, cached) in zip(marked, results) if not cached)
        turns = [{"text": plain(s.text), "kind": s.kind, "audio": f"/{self.token}/audio/{key}.mp3"}
                 for s, (key, _) in zip(says, results)]
        return turns, {"seconds": round(self.clock() - started, 3), "chars": chars,
                       "cost": round(chars / 1000 * TTS_USD_PER_1000_CHARS, 6)}

    def reply(self, turns: list[dict], **extra) -> dict:
        session = self.session
        return {"turns": turns, "card": session.card, "done": session.done, **extra}


def create_app(lesson: Lesson, token: str, transcribe, synthesise, judge_factory, cache_dir: Path,
               save: Callable[[Session, str], Path] | None = None, clock=time.monotonic,
               recordings: Path | None = None, part: str = "all") -> Starlette:
    """`transcribe(audio, content_type) -> Transcript`, `synthesise(marked text) -> mp3 bytes`,
    `judge_factory(lesson) -> judge`, `save(session, part)` writes the session log."""
    base = f"/{token}/"
    lessons = Lessons(lesson, token, transcribe, Speaker(synthesise, cache_dir), judge_factory,
                      save or (lambda session, part: Path()), clock, recordings, part)

    def failure(exc: Exception) -> JSONResponse:
        text = str(exc) if isinstance(exc, (ProviderError, RuntimeError)) else f"{type(exc).__name__}: {exc}"
        return JSONResponse({"error": text}, status_code=502, headers=NO_STORE)

    def locked(work, *args):
        with lessons.lock:
            return work(*args)

    def no_lesson() -> JSONResponse:
        return JSONResponse({"error": "No lesson is running; press Start."}, status_code=409, headers=NO_STORE)

    async def page(request: Request) -> Response:
        html = PAGE.read_text(encoding="utf-8").replace("__BASE__", base).replace("__TITLE__", f"Lesson {lesson.part}" + (f", part {part}" if part != "all" else ""))
        return Response(html, media_type="text/html", headers=NO_STORE)

    async def manifest_route(request: Request) -> Response:
        return Response(json.dumps(manifest(base)), media_type="application/manifest+json", headers=NO_STORE)

    async def worker(request: Request) -> Response:
        return Response(SERVICE_WORKER, media_type="text/javascript", headers=NO_STORE)

    async def svg(request: Request) -> Response:
        return Response(ICON_SVG, media_type="image/svg+xml")

    def png(size: int):
        async def route(request: Request) -> Response:
            return Response(icon_png(size), media_type="image/png")
        return route

    async def start(request: Request) -> Response:
        try:
            return JSONResponse(await run_in_threadpool(locked, lessons.start), headers=NO_STORE)
        except Exception as exc:
            return failure(exc)

    async def turn(request: Request) -> Response:
        if lessons.session is None or lessons.session.done or request.query_params.get("s") != lessons.id:
            return no_lesson()
        audio = await request.body()
        if len(audio) > MAX_UPLOAD:
            return JSONResponse({"error": "That recording is too long."}, status_code=413, headers=NO_STORE)
        if len(audio) < MIN_UPLOAD:
            return JSONResponse({"error": "The recording was empty. Try again."}, status_code=400, headers=NO_STORE)
        try:
            data = await run_in_threadpool(locked, lessons.turn, audio,
                                           request.headers.get("content-type", "audio/webm"))
            return JSONResponse(data, headers=NO_STORE)
        except Exception as exc:
            return failure(exc)

    async def stop(request: Request) -> Response:
        if lessons.session is None or request.query_params.get("s") != lessons.id:
            return no_lesson()
        try:
            return JSONResponse(await run_in_threadpool(locked, lessons.stop), headers=NO_STORE)
        except Exception as exc:
            return failure(exc)

    async def audio(request: Request) -> Response:
        key = request.path_params["key"]
        path = lessons.speaker.path(key)
        if not re.fullmatch(r"[0-9a-f]{32}", key) or not path.exists():
            return Response("Not found", status_code=404)
        return FileResponse(path, media_type="audio/mpeg")

    routes = [
        Route(f"/{token}", page), Route(base, page), Route(base + "manifest.webmanifest", manifest_route),
        Route(base + "sw.js", worker), Route(base + "icon.svg", svg),
        Route(base + "icon-192.png", png(192)), Route(base + "icon-512.png", png(512)),
        Route(base + "start", start, methods=["POST"]), Route(base + "turn", turn, methods=["POST"]),
        Route(base + "stop", stop, methods=["POST"]), Route(base + "audio/{key}.mp3", audio),
    ]
    app = Starlette(routes=routes)
    app.state.lessons = lessons
    return app
