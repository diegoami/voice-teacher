"""End to end over Streamable HTTP with the SDK client, as the Claude app would connect."""

import asyncio
import socket
import threading
import time

import uvicorn
from mcp import Client

from connector.export import report, write_transcript
from connector.lesson import plain
from connector.server import Lessons, app
from connector.store import Store


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def text(result) -> str:
    return result.content[0].text


def test_full_lesson_over_http(sessions_dir, tmp_path):
    store = Store(tmp_path / "data")
    lessons = Lessons(sessions_dir, store)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app(lessons, "secret"), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)

    lines = [plain(line) for line in lessons_lines(sessions_dir)]

    async def lesson() -> str:
        async with Client(f"http://127.0.0.1:{port}/secret/mcp") as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert names == {"start_lesson", "turn", "end_session"}
            package = text(await client.call_tool("start_lesson", {"start_command": "Počnimo."}))
            assert package.startswith("DELIVERY NOTE") and "VOICE_SESSION_PACKAGE" in package
            session_id = package.split("Session id: ")[1].split("\n")[0]
            said = f"Сьогодні ми повторимо час. Спочатку послухайте, а потім повторіть. {lines[0]}"
            for i in range(len(lines)):
                reply = text(await client.call_tool("turn", {
                    "session_id": session_id, "teacher_said": said, "learner_said": f"повтор {i + 1}"}))
                said = reply.split("«")[1].split("»")[0] if i + 1 < len(lines) else \
                    "Добре. А тепер почнімо розмову. Добрий день! Ви вільні сьогодні ввечері?"
            assert "Opening complete" in reply
            reply = text(await client.call_tool("turn", {
                "session_id": session_id, "teacher_said": said, "learner_said": "На жаль, сьогодні я не можу."}))
            assert reply == "Recorded."
            await client.call_tool("end_session", {"session_id": session_id, "closing": "Заняття закінчено."})
            return session_id

    try:
        session_id = asyncio.run(lesson())
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    events = store.read(session_id)
    assert [e["event"] for e in events].count("turn") == 12
    summary = report(session_id, events)
    assert "finished at turn call 12" in summary and "end_session     called" in summary
    path = write_transcript(session_id, events, sessions_dir)
    written = path.read_text(encoding="utf-8")
    assert "**Learner:** Počnimo." in written
    assert "**Learner:** На жаль, сьогодні я не можу." in written
    assert written.rstrip().endswith("**Teacher:** Заняття закінчено.")
    assert "- Mode: voice (lesson connector)" in written


def lessons_lines(sessions_dir):
    from connector.lesson import next_package
    return next_package(sessions_dir).opening_lines


def test_wrong_path_is_not_served(sessions_dir, tmp_path):
    from starlette.testclient import TestClient
    client = TestClient(app(Lessons(sessions_dir, Store(tmp_path / "d")), "secret"))
    assert client.post("/mcp", json={}).status_code == 404
    assert client.post("/other/mcp", json={}).status_code == 404
