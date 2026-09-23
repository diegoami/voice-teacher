"""End to end over Streamable HTTP with the SDK client, as the Claude app would connect."""

import asyncio
import socket
import threading
import time

import uvicorn
from mcp import Client

from connector.export import report, write_transcript
from connector.lesson import next_package, plain, spoken_line
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
    package = next_package(sessions_dir)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app(lessons, "secret"), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)

    lines = [plain(line) for line in package.opening_lines]
    later = [plain(spoken_line(s)) for s in package.guided_steps] + [plain(r) for r in package.recall_prompts]
    replies = []

    async def lesson() -> str:
        async with Client(f"http://127.0.0.1:{port}/secret/mcp") as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert names == {"start_lesson", "turn", "end_session"}
            delivered = text(await client.call_tool("start_lesson", {"start_command": "Počnimo."}))
            assert delivered.startswith("DELIVERY NOTE") and "VOICE_SESSION_PACKAGE" in delivered
            session_id = delivered.split("Session id: ")[1].split("\n")[0]

            async def turn(said: str, heard: str) -> str:
                reply = text(await client.call_tool("turn", {
                    "session_id": session_id, "teacher_said": said, "learner_said": heard}))
                replies.append(reply)
                return reply

            said = f"Сьогодні ми повторимо час. Спочатку послухайте, а потім повторіть. {lines[0]}"
            for i in range(len(lines)):
                reply = await turn(said, f"повтор {i + 1}")
                said = reply.split("«")[1].split("»")[0] if i + 1 < len(lines) else \
                    f"Добре. А тепер почнімо розмову. {later[0]}"
            assert "Opening complete" in reply and "Guided step 1 of 10" in reply
            for i, line in enumerate(later):
                said = line if i else said
                reply = await turn(said, f"відповідь {i + 1}")
            assert "call end_session" in reply
            writeup = "Teacher: Сьогодні…\nLearner: Počnimo.\nTeacher: Заняття закінчено."
            await client.call_tool("end_session", {
                "session_id": session_id, "closing": "Заняття закінчено.", "transcript": writeup})
            return session_id

    try:
        session_id = asyncio.run(lesson())
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    assert "Guided step 2 of 10" in replies[11]
    assert any("Delayed recall prompt 1 of 6" in r and "no model" in r for r in replies)
    events = store.read(session_id)
    assert [e["event"] for e in events].count("turn") == 11 + 16
    summary = report(session_id, events)
    assert "end_session     called" in summary and "recall, item 16" in summary
    assert "2 teacher / 1 learner lines" in summary
    written = write_transcript(session_id, events, sessions_dir).read_text(encoding="utf-8")
    assert "## Teacher's write-up (end_session)" in written and "Learner: Počnimo." in written
    assert "## Per-turn log (turn)" in written and "**Learner:** відповідь 16" in written
    assert "- Mode: voice (lesson connector)" in written


def test_wrong_path_is_not_served(sessions_dir, tmp_path):
    from starlette.testclient import TestClient
    client = TestClient(app(Lessons(sessions_dir, Store(tmp_path / "d")), "secret"))
    assert client.post("/mcp", json={}).status_code == 404
    assert client.post("/other/mcp", json={}).status_code == 404
