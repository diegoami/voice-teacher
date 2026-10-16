"""Explicit bounded live speech check; synthetic audio only, no judge calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
import unicodedata

import httpx2 as httpx

from schemas.validate import canonical_json
from voice_teacher.providers.speech import ElevenLabs, SpeechConfig, SpeechError
from voice_teacher.storage import Store

PHRASE = "Оди́н квито́к, будь ла́ска."


def plain(value):
    return " ".join(re.sub(r"[^\w\s]", " ", unicodedata.normalize("NFC", value.replace("\u0301", "")).lower()).split())


def write(path, data):
    if path.is_symlink(): raise ValueError("smoke artifact symlinks are refused")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as file: file.write(data); file.flush(); os.fsync(file.fileno())


def run_smoke(directory, key, *, client=None):
    root = Path(directory).resolve()
    if any((p / ".git").exists() for p in [root, *root.parents]): raise ValueError("smoke artifacts must be outside Git")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.stat().st_mode & 0o077: raise ValueError("smoke artifacts directory must be private")
    Store(root / "runtime")  # Apply the same code/runtime path protection as serving.
    if not key: raise ValueError("selected speech credential is missing")
    if any((root / name).exists() for name in ("synthetic.mp3", "result.json")):
        raise ValueError("use a fresh private smoke directory; existing artifacts are preserved")
    owned = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=False)
    try:
        # POC models/voice, with explicit reproducible settings instead of
        # mutable account defaults. No extra voice-settings read permission.
        config = SpeechConfig()
        config.definition()
        speech = ElevenLabs(key, config=config, client=client, timeout=30, max_response_bytes=256 * 1024)
        started = time.monotonic()
        audio = speech.synthesize(PHRASE, language="uk")
        synthesis = round(time.monotonic() - started, 3)
        write(root / "synthetic.mp3", audio)
        started = time.monotonic()
        transcript = speech.transcribe(audio, language="uk", media_type="audio/mpeg")
        recognition = round(time.monotonic() - started, 3)
        report = {"schema_version": 1, "synthetic": True, "at": datetime.now(timezone.utc).isoformat(),
            "configuration": config.definition(), "phrase": PHRASE, "transcript": transcript.text,
            "matches_plain_phrase": plain(transcript.text) == plain(PHRASE), "audio_seconds": transcript.audio_seconds,
            "synthesis_seconds": synthesis, "recognition_seconds": recognition,
            "audio_bytes": len(audio), "audio_sha256": hashlib.sha256(audio).hexdigest(),
            "limits": {"settings_requests": 0, "synthesis_requests": 1, "recognition_requests": 1,
                       "timeout_seconds": 30, "max_audio_bytes": 256 * 1024},
            "credential_source": "existing ELEVENLABS_API_KEY environment; value never recorded"}
        write(root / "result.json", canonical_json(report).encode())
        return report
    finally:
        if owned: client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", required=True)
    args = parser.parse_args()
    try: result = run_smoke(args.artifacts, os.environ.get("ELEVENLABS_API_KEY"))
    except Exception as error:
        status = re.search(r"HTTP (\d{3})", str(error)) if isinstance(error, SpeechError) else None
        print(json.dumps({"ok": False, "error": "speech_smoke_failed", "http_status": int(status[1]) if status else None}))
        raise SystemExit(1) from None
    print(canonical_json(result))
    if not result["matches_plain_phrase"]: raise SystemExit(1)


if __name__ == "__main__": main()
