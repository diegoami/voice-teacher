"""Compose the personal server from explicit private settings and environment."""
import argparse
import os

import uvicorn

from .api import create_app
from .practice.coordinator import Coordinator
from .providers.judge import OpenRouterJudge
from .providers.dialogue import OpenRouterDialogue
from .providers.pipeline import VoicePipeline
from .providers.speech import ElevenLabs
from .storage import Store


def build_app(data_dir, *, operator_token, speech_key, judge_key, judge_model,
              origin="http://localhost:8000", assets=None, speech_config=None, dialogue_model=None):
    store = Store(data_dir)
    judge = OpenRouterJudge(judge_key, judge_model)
    dialogue = OpenRouterDialogue(judge_key, dialogue_model) if dialogue_model is not None else None
    coordinator = Coordinator(store, judge, dialogue=dialogue)
    speech = ElevenLabs(speech_key, config=speech_config)
    pipeline = VoicePipeline(store, coordinator, speech, speech)
    return create_app(store, coordinator, operator_token=operator_token, origin=origin, audio=pipeline, assets=assets)


def main():
    parser = argparse.ArgumentParser(description="Run the paired personal Voice Teacher API")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--judge-model", default=os.environ.get("TEACHER_MODEL"))
    parser.add_argument("--dialogue-model", default=os.environ.get("VOICE_TEACHER_DIALOGUE_MODEL"))
    parser.add_argument("--origin", default="http://localhost:8000")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--assets")
    args = parser.parse_args()
    if not args.judge_model: parser.error("select --judge-model or TEACHER_MODEL explicitly")
    try:
        app = build_app(args.data_dir, operator_token=os.environ.get("VOICE_TEACHER_OPERATOR_TOKEN"),
            speech_key=os.environ.get("ELEVENLABS_API_KEY"), judge_key=os.environ.get("OPENROUTER_API_KEY"),
            judge_model=args.judge_model, origin=args.origin, assets=args.assets, dialogue_model=args.dialogue_model)
    except (ValueError, OSError): parser.error("invalid private server configuration; check selected credentials, paths and settings")
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=False, access_log=False)


if __name__ == "__main__": main()
