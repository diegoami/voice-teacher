"""Opt-in synthetic live probe: at most six turns, no retry or model fallback.

This is provider integration evidence, not a human unscripted conversation or
listening acceptance. Outputs must remain outside every Git checkout.
"""
import argparse
import json
import os
from pathlib import Path

import httpx2
from voice_teacher.practice.coordinator import Coordinator
from voice_teacher.practice.free import FreePolicy, plan_free
from voice_teacher.providers.dialogue import OpenRouterDialogue, REASONING_EFFORTS
from voice_teacher.providers.feedback import OpenRouterFeedback
from voice_teacher.providers.speech import ElevenLabs
from voice_teacher.storage import Store

INPUTS = (
    "Я хочу поїхати потягом зі Львова до Києва завтра вранці.",
    "Я хочу один квиток біля вікна. Скільки це коштує?",
    "Я купив два квиток. Ми їдемо з другом.",
    "Я не зрозумів слово пересадка. Що це означає?",
    "Ми хочемо прямий потяг. Чи можна взяти з собою велосипед?",
    "Дякую. Я виберу ранковий потяг і візьму велосипед.",
)


def observe_response(response, observe):
    """Observe decoded bytes under the same cap as the production adapter."""
    original = response.iter_bytes

    def observed_bytes(*args, **kwargs):
        raw = bytearray()
        for chunk in original(*args, **kwargs):
            raw.extend(chunk)
            if len(raw) > 64 * 1024:
                raise ValueError("provider response exceeds metadata limit")
            yield chunk
        observe(response.status_code, bytes(raw))

    response.iter_bytes = observed_bytes


def bounded_turns(value):
    count = int(value)
    if not 1 <= count <= 6:
        raise argparse.ArgumentTypeError("live probe requires one to six turns")
    return count


def private_output(value):
    path = Path(value).expanduser().resolve()
    if path.exists() or any((p / ".git").exists() for p in (path, *path.parents)):
        raise ValueError("select a fresh private output outside Git checkouts")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--turns", type=bounded_turns, default=6)
    parser.add_argument("--correction-style", choices=["light_immediate", "end_of_session"], default="light_immediate")
    parser.add_argument("--output", required=True)
    parser.add_argument("--reasoning-effort", choices=REASONING_EFFORTS)
    parser.add_argument("--reply-tokens", type=int, choices=range(64, 513), default=256, metavar="64..512")
    parser.add_argument("--speech", action="store_true", help="also generate private ElevenLabs samples")
    args = parser.parse_args()
    root = private_output(args.output)
    key = os.environ.get("OPENROUTER_API_KEY")
    speech_key = os.environ.get("ELEVENLABS_API_KEY")
    if not key or (args.speech and not speech_key):
        raise SystemExit("required private provider credential is unavailable")
    # Validate the exact requested live ID before spending; never replace it.
    response = httpx2.get("https://openrouter.ai/api/v1/models", timeout=30)
    response.raise_for_status()
    if args.model not in {m["id"] for m in response.json()["data"]}:
        raise SystemExit("selected model unavailable; no substitute or live turn started")
    root.mkdir(mode=0o700)
    report = dict(model=args.model, turns=[], input_kind="synthetic_text", correction_style=args.correction_style, max_reply_tokens=args.reply_tokens, reasoning_effort=args.reasoning_effort,
                  human_conversation="incomplete", human_listening="incomplete", real_microphone="not run",
                  generated_stress="unverified: generated words have no authored stress guarantee")
    def save():
        p = root / "report.json"
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        p.chmod(0o600)
    save()
    try:
        def response_metadata(status, raw):
            try:
                body = json.loads(raw)
                choice = (body.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                report.setdefault("provider_responses", []).append({
                    "http_status": status, "model": body.get("model"),
                    "finish_reason": choice.get("finish_reason"),
                    "refused": bool(message.get("refusal")),
                    "error_code": (body.get("error") or {}).get("code"),
                    "completion_tokens": (body.get("usage") or {}).get("completion_tokens"),
                    "reasoning_tokens": ((body.get("usage") or {}).get("completion_tokens_details") or {}).get("reasoning_tokens"),
                    "content_characters": len(message.get("content") or ""),
                })
            except Exception:
                report.setdefault("provider_responses", []).append({"http_status": status})
            save()
        client = httpx2.Client(timeout=20, follow_redirects=False,
                               event_hooks={"response": [lambda response: observe_response(response, response_metadata)]})
        dialogue = OpenRouterDialogue(key, args.model, client=client, max_reply_tokens=args.reply_tokens, reasoning_effort=args.reasoning_effort)
        feedback = OpenRouterFeedback(key, args.model, client=client, reasoning_effort=args.reasoning_effort)
        speech = ElevenLabs(speech_key) if args.speech else None
        store = Store(root / "runtime")
        learner, sid = "synthetic-eval", "bounded-live"
        store.save_learner(learner, {"level": "A2"})
        policy = FreePolicy(max_turns=args.turns)
        coordinator = Coordinator(store, lambda *a: (_ for _ in ()).throw(AssertionError("no fixed-answer judge")),
                                  dialogue=dialogue, feedback=feedback, free_policies={("uk", "en"): policy})
        plan = plan_free(None, None, None, topic="Train travel in Ukraine", learner_level="A2",
                         provider=dialogue.identity, policy=policy, correction_style=args.correction_style)
        template = dict(schema_version=1, kind="session_snapshot", learner_id=learner, session_id=sid,
                        revision=0, event_sequence=0, mode="free_conversation", status="created", source=None,
                        curriculum_snapshot=None, topic=plan.topic, language="uk", instruction_language="en",
                        learner_profile={"level": "A2"}, engine_state={"format_version": 1, "data": {}})
        state = coordinator.create_free(template, plan)
        for index, text in enumerate(INPUTS[:args.turns], 1):
            state = coordinator.submit(learner, sid, f"live-{index}", expected_revision=state["revision"], text=text)
            row = dict(turn=index, input=text, teacher=state["teacher"], revision=state["revision"])
            report["turns"].append(row)
            save()  # retain successful text even if synthesis fails; no automatic retry
            if speech:
                audio = speech.synthesize(" ".join(t["text"] for t in state["teacher"]), language="uk")
                file = root / f"turn-{index}.mp3"
                file.write_bytes(audio)
                file.chmod(0o600)
                row["speech_bytes"] = len(audio)
                save()
        report["provider_check"] = "completed"
        report["evidence"] = [e["evidence"] for e in store.events(learner, sid) if e["event_type"] == "evidence.recorded"]
    except Exception as error:
        report["failure_type"] = type(error).__name__
        report["provider_check"] = "failed; no automatic retry or fallback"
        save()
        raise SystemExit("live operation failed; private partial report retained") from None
    save()
    print(json.dumps({"model": args.model, "completed_turns": len(report["turns"]), "provider_check": report["provider_check"],
                      "human_conversation": "incomplete", "human_listening": "incomplete"}))


if __name__ == "__main__":
    main()
