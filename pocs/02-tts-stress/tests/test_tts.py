import json
import threading
import urllib.request
from pathlib import Path

import httpx
import pytest

from tts import __main__ as cli
from tts import providers
from tts.items import VARIANTS, load_items, plain
from tts.providers import ProviderError, synthesise
from tts.report import report

HERE = Path(__file__).resolve().parents[1]
ITEMS = HERE / "stress_items.md"


def test_items():
    items = load_items(ITEMS)
    assert [i.number for i in items] == list(range(1, 16))
    for item in items:
        assert item.targets
        for target in item.targets:
            assert target in item.marked.lower(), (item.number, target)  # a target is a word of the sentence
            assert "́" in target  # and says where the stress goes
        assert "́" not in item.plain
    assert items[12].targets == ("за́мок", "замо́к")
    assert plain(items[12].targets[0]) == plain(items[12].targets[1])  # the homograph pair


def test_variants_send_plain_or_marked_text():
    item = load_items(ITEMS)[3]
    names = {v.name: v for v in VARIANTS}
    assert len(VARIANTS) == 8
    assert names["el-v3-plain"].text(item) == "Станція буде ліворуч."
    assert names["el-v3-marks"].text(item) == "Ста́нція бу́де лі́воруч."


def test_requests(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=b"ID3 fake mp3")

    names = {v.name: v for v in VARIANTS}
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        for name in ("el-v2-marks", "el-flash-plain", "openai-marks", "openai-plain"):
            audio, _ = synthesise(names[name], "Так.", "KEY", client)
            assert audio == b"ID3 fake mp3"
    v2, flash, oa_marks, oa_plain = seen
    body = json.loads(v2.content)
    assert v2.headers["xi-api-key"] == "KEY"
    assert body["model_id"] == "eleven_multilingual_v2" and "language_code" not in body
    assert json.loads(flash.content)["language_code"] == "uk"
    assert "stressed syllable" in json.loads(oa_marks.content)["instructions"]
    assert "stressed syllable" not in json.loads(oa_plain.content)["instructions"]
    assert oa_plain.headers["authorization"] == "Bearer KEY"


def test_error_message():
    transport = httpx.MockTransport(lambda r: httpx.Response(
        404, json={"detail": {"code": "voice_not_found", "message": "A voice was not found."}}))
    with httpx.Client(transport=transport) as client, pytest.raises(ProviderError, match="^HTTP 404: A voice was not found.$"):
        synthesise(VARIANTS[0], "Так.", "KEY", client)


@pytest.fixture
def rendered(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "synthesise", lambda variant, text, key: (b"mp3:" + text.encode(), 0.5))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert cli.render(ITEMS, tmp_path, None, [4, 13], False) == 0
    return tmp_path


def test_render_writes_clips_and_manifest(rendered, monkeypatch):
    manifest = json.loads((rendered / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["clips"]) == 16 and len(manifest["items"]) == 15
    clip = manifest["clips"]["13/el-v3-marks"]
    assert (rendered / clip["file"]).read_bytes() == "mp3:Це стари́й за́мок, а на дверя́х нови́й замо́к.".encode()
    # Cached: a second render asks for nothing.
    monkeypatch.setattr(cli, "synthesise", lambda *a: pytest.fail("should not synthesise again"))
    assert cli.render(ITEMS, rendered, None, [4, 13], False) == 0


def test_server_saves_verdicts_and_report_counts_them(rendered):
    server = cli.serve(rendered, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert b"listening test" in urllib.request.urlopen(base + "/listen.html").read()
        verdicts = {
            "13/el-v3-plain": {"verdict": "wrong", "wrong": ["замо́к"], "other": False, "note": "lock as castle"},
            "13/el-v3-marks": {"verdict": "right"},
            "4/el-v3-plain": {"verdict": "right"},
            "4/openai-plain": {"verdict": "unclear"},
        }
        request = urllib.request.Request(base + "/verdicts", data=json.dumps(verdicts).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        assert urllib.request.urlopen(request).status == 204
    finally:
        server.shutdown()
    assert json.loads((rendered / "verdicts.json").read_text(encoding="utf-8")) == verdicts
    text = report(rendered)
    assert "4 of 16 clips judged" in text
    assert "| el-v3-plain | eleven_v3 | 1/2 | 1 | 0 | 1/3 | 0 |" in text
    assert "| el-v3-marks | eleven_v3 | 1/1 | 0 | 0 | 0/2 | 0 |" in text
    assert "✗ замо́к" in text
    assert "- 13/el-v3-plain: lock as castle" in text
