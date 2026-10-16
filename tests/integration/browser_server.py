"""Loopback-only synthetic service for browser recovery tests; never production config."""
import argparse
import json
from pathlib import Path
import os
import time

import uvicorn
from voice_teacher.api import create_app
from voice_teacher.content.registry import SourceRegistry, SourceSpec
from voice_teacher.practice.coordinator import Coordinator
from voice_teacher.providers import Judgement, Verdict
from voice_teacher.providers.pipeline import VoicePipeline
from voice_teacher.providers.speech import Recognition, SpeechConfig
from voice_teacher.storage import Store

LEARNER = "browser-learner"
TICKET = "Оди́н квито́к, будь ла́ска."


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    root = args.data
    root.mkdir(parents=True, exist_ok=True)
    store = Store(root / "runtime")
    if not (root / "initialized").exists():
        store.save_learner(LEARNER, {"level": "A2"})
        store.save_learner("other-learner", {"level": "B1"})
    registry = SourceRegistry(store)
    for source in ("alpha", "beta"):
        checkout = root / source
        checkout.mkdir(exist_ok=True)
        manifest = checkout / "voice-teacher.json"
        if not manifest.exists():
            raw = json.loads((Path(__file__).parents[1] / "contracts/fixtures/guided.json").read_text())
            raw["source_id"] = source
            course = raw["courses"][0]
            course["items"][0].update(text={"display": TICKET.replace("\u0301", ""), "speech": TICKET}, meaning="One ticket, please")
            lesson = course["lessons"][0]
            lesson.update(title="Tickets", modes=["guided_conversation", "repetition"], repetition_item_ids=["hello"])
            lesson["guided_steps"][0].update(teacher={"display": "Добрий день!", "speech": "До́брий день!"}, goal="Ask for one ticket")
            manifest.write_text(json.dumps(raw, ensure_ascii=False))
        registry.register(SourceSpec(source, "Synthetic " + source, str(checkout), allow_dirty=True))
        registry.refresh(source)

    def stage(name):
        with (root / "calls.jsonl").open("a") as log:
            log.write(json.dumps({"stage": name, "pid": os.getpid()}) + "\n")
        arm = root / "arm.json"
        if arm.exists() and json.loads(arm.read_text())["stage"] == name:
            (root / "arrived.json").write_text(json.dumps({"stage": name, "pid": os.getpid()}))
            deadline = time.monotonic() + 25
            while arm.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            if arm.exists(): raise RuntimeError("synthetic provider stage timed out")

    class Judge:
        def __call__(self, item, text):
            stage("judge")
            return Judgement(Verdict("error" if text == "bad" else "accept", text != "bad", "", "", 0, ""), 0, {})

    class Recognizer:
        def transcribe(self, audio, *, language, media_type):
            stage("recognition")
            return Recognition(audio.decode(), 1)

    class Synthesizer:
        config = SpeechConfig()
        def synthesize(self, text, *, language):
            stage("synthesis")
            return b"synthetic audio: " + text.encode()

    coordinator = Coordinator(store, Judge())
    pipeline = VoicePipeline(store, coordinator, Recognizer(), Synthesizer())
    origin = "http://127.0.0.1:" + str(args.port)
    app = create_app(store, coordinator, operator_token="synthetic-operator-" + "x" * 40,
                     origin=origin, audio=pipeline, assets=args.assets)
    # Auth grants are persisted by the actual service. No special browser bypass.
    code = app.state.auth.issue_code(LEARNER, "browser-test")["code"]
    (root / "ready.json").write_text(json.dumps({"origin": origin, "code": code, "pid": os.getpid()}))
    (root / "initialized").touch()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="error", access_log=False)


if __name__ == "__main__": main()
