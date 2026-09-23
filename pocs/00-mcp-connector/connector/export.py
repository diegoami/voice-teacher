"""Turn a connector session log into a learnukrainian transcript and a POC report."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .lesson import TEMPLATE_MARKER

NOTE = """\
Recorded by the lesson connector (voice-teacher POC 0), session `{session_id}`.
The package was delivered by the `start_lesson` tool, not pasted. Two records
follow: the teacher's write-up of the whole lesson, passed to `end_session`,
and the per-turn log from the `turn` tool. Both are the teacher's copies of
the conversation; learner turns should be the speech-recognition output
verbatim. Where they overlap they should agree; a disagreement is itself a
finding.
"""


def turns(events: list[dict]) -> list[tuple[str, str]]:
    start = events[0]
    out = [("Learner", start["start_command"]),
           ("Teacher", f"[start_lesson tool: package {start['folder']}, prompt {start['prompt_version']}]")]
    for event in events[1:]:
        if event["event"] == "turn":
            out += [("Teacher", event["teacher_said"]), ("Learner", event["learner_said"])]
        elif event["event"] == "end":
            out.append(("Teacher", event["closing"]))
    return out


def transcript(session_id: str, events: list[dict], template: str) -> str:
    head, sep, _ = template.partition("\n---\n")
    if not sep:
        raise ValueError("transcript template has no '---' separator")
    head = head.replace("- Mode: voice | text dry run", "- Mode: voice (lesson connector)")
    log = "\n\n".join(f"**{who}:** {text}" for who, text in turns(events))
    ends = [e for e in events if e["event"] == "end"]
    writeup = ends[-1].get("transcript", "").strip() if ends else ""
    writeup = f"```text\n{writeup}\n```" if writeup else "Not provided: `end_session` was not called."
    title, _, rest = head.partition("\n\n")
    return (f"{title}\n\n{NOTE.format(session_id=session_id)}\n{rest}\n---\n\n"
            f"## Teacher's write-up (end_session)\n\n{writeup}\n\n## Per-turn log (turn)\n\n{log}\n")


def write_transcript(session_id: str, events: list[dict], sessions_dir: Path, force: bool = False) -> Path:
    path = sessions_dir / events[0]["folder"] / "transcript.md"
    current = path.read_text(encoding="utf-8")
    if TEMPLATE_MARKER in current and not force:
        raise FileExistsError(f"{path} already holds a transcript; use --force to overwrite")
    path.write_text(transcript(session_id, events, current), encoding="utf-8", newline="\n")
    return path


def report(session_id: str, events: list[dict]) -> str:
    start = events[0]
    turn_events = [e for e in events if e["event"] == "turn"]
    ends = [e for e in events if e["event"] == "end"]
    times = [datetime.fromisoformat(e["at"]) for e in events]
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
    opening_done = next((i + 1 for i, e in enumerate(turn_events) if e["opening_finished"]), None)
    lines = [
        f"Session {session_id}",
        f"  lesson part     {start['lesson_part']} ({start['folder']}), prompt {start['prompt_version']}",
        f"  start command   {start['start_command']!r}",
        f"  turn calls      {len(turn_events)}",
        f"  opening         {'finished at turn call ' + str(opening_done) if opening_done else 'not finished'}",
        f"  end_session     {'called' if ends else 'NOT called'}",
        f"  duration        {(times[-1] - times[0]).total_seconds() / 60:.1f} min",
        f"  median gap      {sorted(gaps)[len(gaps) // 2]:.0f} s between tool calls" if gaps else "  median gap      n/a",
    ]
    last = turn_events[-1] if turn_events else {}
    lines.append(f"  last position   {last.get('phase', 'opening')}, item {last.get('step', 0)} "
                 "(guided steps first, then recall prompts)")
    if ends:
        writeup = ends[-1].get("transcript", "")
        who = [line.split(":", 1)[0].strip() for line in writeup.splitlines() if ":" in line]
        lines.append(f"  write-up        {who.count('Teacher')} teacher / {who.count('Learner')} learner lines")
        events_seen = ends[-1].get("opening_events", []) + ends[-1].get("step_events", [])
        if events_seen:
            lines.append("  tracker events:")
            lines += [f"    - {e}" for e in events_seen]
    return "\n".join(lines)
