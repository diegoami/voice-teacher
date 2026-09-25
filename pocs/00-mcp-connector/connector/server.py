"""The MCP server the Claude app connects to."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from .lesson import LessonTracker, Package, next_package, parse_package
from .store import Store

INSTRUCTIONS = """\
This connector runs the learner's spoken Ukrainian lessons. When the learner
asks to start a Ukrainian lesson, or says a start command such as «Почнімо»
(however speech recognition transcribed it), call start_lesson and follow the
package it returns. During the lesson call `turn` after every learner turn,
before you speak. Never mention these tools or the recording to the learner."""

DELIVERY_NOTE = """\
DELIVERY NOTE (lesson connector, POC 0)
This package was delivered by the start_lesson tool after the learner's start
command. Skip ON RECEIPT: do not say the ready sentence. Begin the OPENING now.
Session id: {session_id}
After every learner turn, before you speak, call `turn` with this session id,
teacher_said = your previous spoken turn exactly as you said it, and
learner_said = the learner's turn exactly as it was transcribed, without any
correction. Keep calling it until the end. The result tells you where you are
in the brief and what comes next: during the opening, your exact next turn;
afterwards, the current and the next Guided sequence step or Delayed recall
prompt. Follow it.
To close (after the last Delayed recall answer, or when the learner asks to
stop), call `end_session` with the closing sentence and transcript = the whole
lesson from your introduction to the learner's last turn, one turn per line,
each line starting "Teacher:" or "Learner:", your turns exactly as you said
them and the learner's exactly as transcribed, garbled ones included. Then say
the closing sentence. Never mention the tools or the recording to the learner.
END DELIVERY NOTE

"""


DELIVERY_INSTRUCTIONS = """\
This connector starts the learner's spoken Ukrainian lessons. When the learner
asks to start a Ukrainian lesson, or says a start command such as «Почнімо»
(however speech recognition transcribed it), call start_lesson and follow the
package it returns."""

DELIVERY_ONLY_NOTE = """\
This package was delivered after the learner's start command. Skip ON
RECEIPT: do not say the ready sentence. Begin the OPENING now.

"""

MODES = ("delivery", "full")


@dataclass
class Live:
    package: Package
    tracker: LessonTracker
    ended: bool = False


@dataclass
class Lessons:
    sessions_dir: Path
    store: Store
    pinned: str | None = None
    mode: str = "delivery"  # "delivery": start_lesson only; "full": run 2's turn and end_session as well
    live: dict[str, Live] = field(default_factory=dict)

    def get(self, session_id: str) -> Live:
        """Live state, rebuilt from the log if the server restarted."""
        if session_id not in self.live:
            events = self.store.read(session_id)
            package = parse_package(self.sessions_dir / events[0]["folder"])
            live = Live(package, LessonTracker.for_package(package))
            for event in events:
                if event["event"] == "turn":
                    live.tracker.observe(event["teacher_said"])
                live.ended |= event["event"] == "end"
            self.live[session_id] = live
        return self.live[session_id]

    def start(self, start_command: str) -> str:
        try:
            package = next_package(self.sessions_dir, self.pinned)
        except (LookupError, ValueError) as exc:
            return f"No lesson available: {exc} Tell the learner in one short Ukrainian sentence."
        session_id = self.store.new_session(package.name)
        self.store.append(session_id, "start", folder=package.name, prompt_version=package.prompt_version,
                          lesson_part=package.session_label, start_command=start_command, mode=self.mode)
        self.live[session_id] = Live(package, LessonTracker.for_package(package))
        if self.mode == "delivery":
            return DELIVERY_ONLY_NOTE + package.text
        return DELIVERY_NOTE.format(session_id=session_id) + package.text

    def turn(self, session_id: str, teacher_said: str, learner_said: str) -> str:
        try:
            live = self.get(session_id)
        except (KeyError, ValueError):
            return "Unknown session id. Continue the lesson; do not mention this."
        tracker = live.tracker
        tracker.observe(teacher_said)
        self.store.append(session_id, "turn", teacher_said=teacher_said, learner_said=learner_said,
                          opening_next=tracker.opening.next_index, opening_finished=tracker.opening.finished,
                          phase=tracker.phase, step=tracker.steps.current + 1)
        return tracker.instruction()

    def end(self, session_id: str, closing: str, transcript: str) -> str:
        try:
            live = self.get(session_id)
        except (KeyError, ValueError):
            return "Unknown session id. Say the closing sentence."
        live.ended = True
        self.store.append(session_id, "end", closing=closing, transcript=transcript,
                          opening_events=live.tracker.opening.events, step_events=live.tracker.steps.events)
        return "Recorded. Now say the closing sentence and nothing else."


def build(lessons: Lessons) -> MCPServer:
    if lessons.mode not in MODES:
        raise ValueError(f"unknown mode {lessons.mode!r}; use one of {MODES}")
    full = lessons.mode == "full"
    mcp = MCPServer("ukrainian-lessons", instructions=INSTRUCTIONS if full else DELIVERY_INSTRUCTIONS)

    @mcp.tool()
    def start_lesson(start_command: str) -> str:
        """Start the learner's next prepared Ukrainian speaking lesson.

        Call this when the learner asks to start a Ukrainian lesson or says a
        start command such as «Почнімо», however it was transcribed. Returns the
        lesson package to follow for the rest of the conversation.

        start_command: the learner's message exactly as transcribed.
        """
        return lessons.start(start_command)

    if not full:
        return mcp

    @mcp.tool()
    def turn(session_id: str, teacher_said: str, learner_said: str) -> str:
        """Record one exchange of the running lesson; call after every learner turn, before speaking.

        teacher_said: your previous spoken turn, exactly as you said it.
        learner_said: the learner's latest turn exactly as transcribed, uncorrected.
        Returns where you are in the brief and what comes next: the exact next
        turn during the opening, then the current and next step or recall prompt.
        """
        return lessons.turn(session_id, teacher_said, learner_said)

    @mcp.tool()
    def end_session(session_id: str, closing: str, transcript: str) -> str:
        """Record the end of the lesson; call just before saying the closing sentence.

        closing: the closing sentence you are about to say.
        transcript: the whole lesson from your introduction to the learner's last
        turn, one turn per line starting "Teacher:" or "Learner:", your turns as
        you said them and the learner's exactly as transcribed.
        """
        return lessons.end(session_id, closing, transcript)

    return mcp


def app(lessons: Lessons, token: str):
    """Streamable HTTP app served under a secret path.

    DNS-rebinding protection is off: it guards servers reached from a local
    browser, while this one is reached through a tunnel whose host name is not
    known in advance. The secret path is the access control for the POC.
    """
    return build(lessons).streamable_http_app(
        streamable_http_path=f"/{token}/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
