import pytest
from starlette.testclient import TestClient

from engine.package import STRESS
from engine.server import create_app
from engine.voice import ProviderError, Transcript, cache_key
from test_session import FakeJudge, small_lesson

TOKEN = "s3cret"
AUDIO = b"x" * 500


class Fakes:
    def __init__(self, *heard):
        self.heard = list(heard)
        self.synthesised: list[str] = []
        self.transcribed: list[tuple[int, str]] = []
        self.saved: list[tuple[object, str]] = []
        self.judge = FakeJudge()
        self.fail_tts = False

    def transcribe(self, audio, content_type):
        self.transcribed.append((len(audio), content_type))
        item = self.heard.pop(0)
        return item if isinstance(item, Transcript) else Transcript(item, 2.0)

    def synthesise(self, text):
        if self.fail_tts:
            raise ProviderError("speech synthesis failed, HTTP 401: bad key")
        self.synthesised.append(text)
        return b"MP3:" + text.encode()

    def save(self, session, part):
        self.saved.append((session, part))


def make(tmp_path, *heard, verdicts=()):
    fakes = Fakes(*heard)
    fakes.judge = FakeJudge(*verdicts)
    app = create_app(small_lesson(), TOKEN, fakes.transcribe, fakes.synthesise, lambda lesson: fakes.judge,
                     tmp_path / "cache", save=fakes.save)
    return TestClient(app), fakes


def url(path):
    return f"/{TOKEN}/{path}"


def turn(client, session, audio=AUDIO, content_type="audio/webm;codecs=opus"):
    return client.post(url(f"turn?s={session}"), content=audio, headers={"content-type": content_type})


def test_wrong_token_is_404_everywhere(tmp_path):
    client, fakes = make(tmp_path)
    for path in ("/", "/wrong/", "/wrong/start", "/wrong/manifest.webmanifest", f"/{TOKEN}x/", "/audio/abc.mp3"):
        assert client.get(path).status_code == 404, path
    assert client.post("/wrong/start").status_code == 404
    assert client.post("/start").status_code == 404
    assert fakes.synthesised == []


def test_page_manifest_worker_and_icons(tmp_path):
    client, _ = make(tmp_path)
    for path in (f"/{TOKEN}", f"/{TOKEN}/"):
        page = client.get(path)
        assert page.status_code == 200 and "text/html" in page.headers["content-type"]
        assert f'href="/{TOKEN}/manifest.webmanifest"' in page.text and "__BASE__" not in page.text
    manifest = client.get(url("manifest.webmanifest")).json()
    assert manifest["start_url"] == f"/{TOKEN}/" and manifest["display"] == "fullscreen"
    assert {i["sizes"] for i in manifest["icons"]} >= {"192x192", "512x512"}
    assert "fetch" in client.get(url("sw.js")).text
    assert "javascript" in client.get(url("sw.js")).headers["content-type"]
    png = client.get(url("icon-192.png"))
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert "svg" in client.get(url("icon.svg")).headers["content-type"]


def test_start_returns_plain_text_card_and_audio(tmp_path):
    client, fakes = make(tmp_path)
    data = client.post(url("start")).json()
    assert [t["text"] for t in data["turns"]] == ["Сьогодні ми купимо квиток. Спочатку послухайте, а потім повторіть.",
                                                  "Один квиток, будь ласка."]
    assert all(STRESS not in t["text"] for t in data["turns"])  # the learner reads plain spelling
    assert data["card"].startswith("Listen and repeat") and data["done"] is False and data["session"]
    assert any(STRESS in text for text in fakes.synthesised)  # the voice gets the marks
    audio = client.get(data["turns"][1]["audio"])
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/mpeg"
    assert audio.content == "MP3:Оди́н квито́к, будь ла́ска.".encode()
    assert client.get(url("audio/" + "0" * 32 + ".mp3")).status_code == 404
    assert client.get(url("audio/..%2Fx.mp3")).status_code == 404


def test_turn_flow_reports_what_was_heard_and_logs_timings(tmp_path):
    client, fakes = make(tmp_path, "один квиток будь ласка", verdicts=())
    session = client.post(url("start")).json()["session"]
    data = turn(client, session).json()
    assert data["heard"] == "один квиток будь ласка"
    assert [t["text"] for t in data["turns"]] == ["Скільки це коштує?"] and not data["done"]
    assert fakes.transcribed == [(500, "audio/webm;codecs=opus")]
    timing = [e for e in client.app.state.lessons.session.log if e["event"] == "timing"][-1]
    assert timing["turn"] == 1 and timing["heard"] == "один квиток будь ласка"
    for key in ("stt_seconds", "judge_seconds", "tts_seconds", "total_seconds", "cost_usd", "tts_chars_billed"):
        assert key in timing
    assert timing["cost_usd"]["stt"] == pytest.approx(2.0 / 3600 * 0.22)
    assert timing["tts_chars_billed"] == len("Скі́льки це ко́штує?")
    assert timing["cost_usd"]["tts"] == pytest.approx(timing["tts_chars_billed"] * 0.0001)


def test_judge_seconds_and_cost_come_from_the_judge_entry(tmp_path):
    # Opening and round 0 need no judge; round 1's first step does.
    heard = ["один квиток будь ласка", "скільки це коштує"] * 2 + ["один квиток будь ласка"]
    client, fakes = make(tmp_path, *heard, verdicts=[("accept",)])
    session = client.post(url("start")).json()["session"]
    for _ in heard:
        data = turn(client, session).json()
    assert data["turns"][0]["text"] == "Ось, будь ласка."
    timing = [e for e in client.app.state.lessons.session.log if e["event"] == "timing"][-1]
    assert timing["judge_seconds"] == 0.4 and timing["cost_usd"]["judge"] == 0.001
    assert timing["cost_usd"]["total"] > 0.001


def test_cache_means_a_second_request_for_the_same_text_makes_no_synthesis_call(tmp_path):
    client, fakes = make(tmp_path)
    first = client.post(url("start")).json()
    calls = len(fakes.synthesised)
    assert calls == 2
    second = client.post(url("start")).json()  # the same fixed lines again
    assert len(fakes.synthesised) == calls
    assert [t["audio"] for t in second["turns"]] == [t["audio"] for t in first["turns"]]
    assert (tmp_path / "cache" / (cache_key("Оди́н квито́к, будь ла́ска.") + ".mp3")).exists()
    timing = [e for e in client.app.state.lessons.session.log if e["event"] == "timing"][0]
    assert timing["tts_chars_billed"] == 0 and timing["cost_usd"]["tts"] == 0  # nothing billed from the cache


def test_a_new_cache_object_reads_the_files_left_on_disk(tmp_path):
    first, _ = make(tmp_path)
    first.post(url("start"))
    again, fakes = make(tmp_path)
    again.post(url("start"))
    assert fakes.synthesised == []


def test_nothing_recognised_asks_again_without_changing_the_lesson(tmp_path):
    client, fakes = make(tmp_path, "", "один квиток будь ласка")
    session = client.post(url("start")).json()["session"]
    data = turn(client, session).json()
    assert data["heard"] == "" and [t["text"] for t in data["turns"]] == ["Повторіть, будь ласка."]
    assert data["card"].startswith("Listen and repeat")
    assert [t["text"] for t in turn(client, session).json()["turns"]] == ["Скільки це коштує?"]


def test_model_text_is_stress_marked_before_synthesis(tmp_path):
    heard = ["один квиток будь ласка", "скільки це коштує"] * 2 + ["один квиток будь ласка", "сколько стоит"]
    client, fakes = make(tmp_path, *heard, verdicts=[("accept",), ("error", "у мене квиток")])
    session = client.post(url("start")).json()["session"]
    for _ in heard:
        data = turn(client, session).json()
    assert data["turns"][0]["text"] == "Виправлення: у мене квиток. Скажіть усе речення."
    spoken = fakes.synthesised[-1]
    assert spoken == "Ви́правлення: у мене́ квито́к. Скажі́ть усе́ ре́чення."


def test_stop_ends_the_lesson_and_saves_the_log_once(tmp_path):
    client, fakes = make(tmp_path)
    session = client.post(url("start")).json()["session"]
    data = client.post(url(f"stop?s={session}")).json()
    assert data["done"] is True and data["card"] is None
    assert [t["text"] for t in data["turns"]] == ["Заняття закінчено."]
    assert len(fakes.saved) == 1 and fakes.saved[0][1] == "9A"
    assert client.post(url(f"stop?s={session}")).json()["turns"] == [] and len(fakes.saved) == 1
    assert turn(client, session).status_code == 409


def test_a_finished_lesson_is_saved(tmp_path):
    heard = ["один квиток будь ласка", "скільки це коштує"] * 2 + ["a", "b", "c", "d", "e"]
    client, fakes = make(tmp_path, *heard, verdicts=[("accept",)] * 5)
    session = client.post(url("start")).json()["session"]
    for _ in heard[:-1]:
        assert turn(client, session).json()["done"] is False
    assert fakes.saved == []
    data = turn(client, session).json()
    assert data["done"] is True and [t["text"] for t in data["turns"]] == ["Заняття закінчено."]
    assert len(fakes.saved) == 1 and fakes.saved[0][1] == "9A"
    assert turn(client, session).status_code == 409


def test_starting_again_keeps_the_log_of_the_abandoned_lesson(tmp_path):
    client, fakes = make(tmp_path, "один квиток будь ласка")
    first = client.post(url("start")).json()["session"]
    turn(client, first)
    second = client.post(url("start")).json()["session"]
    assert second != first and len(fakes.saved) == 1
    assert turn(client, first).status_code == 409  # the old lesson's id no longer works


def test_turn_without_start_and_bad_uploads(tmp_path):
    client, fakes = make(tmp_path)
    assert turn(client, "nope").status_code == 409
    session = client.post(url("start")).json()["session"]
    assert turn(client, session, audio=b"tiny").status_code == 400
    assert fakes.transcribed == []


def test_provider_failures_are_readable_json(tmp_path):
    client, fakes = make(tmp_path)
    fakes.fail_tts = True
    response = client.post(url("start"))
    assert response.status_code == 502 and "speech synthesis failed" in response.json()["error"]
    fakes.fail_tts = False
    session = client.post(url("start")).json()["session"]

    def broken(audio, content_type):
        raise ProviderError("speech recognition failed, HTTP 500: down")
    client.app.state.lessons.transcribe = broken
    response = turn(client, session)
    assert response.status_code == 502 and "speech recognition failed" in response.json()["error"]
