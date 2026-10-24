"""End-to-end with the real bundled models, through the HTTP API (no network, no mocks).

1. Import: a two-speaker clip alternating Hindi (a real FLEURS speaker) and English (a SAPI voice).
2. Crash recovery: a two-track recording whose WAV headers were never finalized is recovered and processed;
   the microphone track becomes "You", the system track is diarized.
"""
import json
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from conftest import DATA, models_available

pytestmark = pytest.mark.skipif(not models_available(), reason="bundled models not present")

TOKEN = "integration-test-token-0123456789"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from sabhalekh import netguard

    netguard.install()
    from sabhalekh import config
    from sabhalekh.api import App, create_app
    from sabhalekh.audio.recorder import Recorder
    from sabhalekh.db import Database
    from sabhalekh.events import EventBus
    from sabhalekh.hardware import HardwareManager
    from sabhalekh.models import ModelRegistry
    from sabhalekh.pipeline.jobs import JobQueue

    config.ensure_dirs()
    db = Database(config.DB_PATH)
    bus = EventBus()
    hw = HardwareManager()
    reg = ModelRegistry()
    q = JobQueue(db, hw, reg, bus)
    state = App(db, hw, reg, bus, q, Recorder(bus.publish), TOKEN)
    q.start()
    with TestClient(create_app(state), base_url="http://127.0.0.1") as c:
        c.headers["Authorization"] = f"Bearer {TOKEN}"
        yield c
    q.stop()


def wait_done(client, sid, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = client.get(f"/api/sessions/{sid}").json()["session"]
        if s["status"] in ("done", "error", "cancelled"):
            return s
        time.sleep(0.5)
    raise TimeoutError("processing did not finish")


def test_api_requires_token_and_local_host(client):
    from fastapi.testclient import TestClient

    assert client.get("/api/health").status_code == 200
    anon = TestClient(client.app, base_url="http://127.0.0.1")
    assert anon.get("/api/health").status_code == 401
    assert anon.get("/api/health?token=wrong").status_code == 401
    evil = TestClient(client.app, base_url="http://attacker.example")
    assert evil.get(f"/api/health?token={TOKEN}").status_code == 403


def test_import_two_speakers_mixed_english_hindi(client):
    meta = json.loads((DATA / "two_speaker_en_hi.json").read_text(encoding="utf-8"))
    r = client.post("/api/sessions/import", json={"paths": [str(DATA / "two_speaker_en_hi.wav")]}).json()
    assert "errors" in r, r
    assert not r["errors"] and len(r["created"]) == 1
    sid = r["created"][0]
    s = wait_done(client, sid)
    assert s["status"] == "done", s["error_message"]
    data = client.get(f"/api/sessions/{sid}").json()
    segs, speakers = data["segments"], data["speakers"]
    assert len(speakers) == 2, [sp["display_name"] for sp in speakers]
    assert set(s["detected_languages"]) == {"en", "hi"}
    # every expected turn is covered by segments of one consistent speaker, and the two people differ
    turn_spk = []
    for t in meta["turns"]:
        inside = [g for g in segs if g["start_sec"] < t["end"] and g["end_sec"] > t["start"]]
        assert inside, f"no transcript for turn {t}"
        dur: dict = {}
        for g in inside:
            ov = min(g["end_sec"], t["end"]) - max(g["start_sec"], t["start"])
            dur[g["speaker_id"]] = dur.get(g["speaker_id"], 0) + ov
        turn_spk.append(max(dur, key=dur.get))
        assert all(g["language"] == t["language"] for g in inside if
                   min(g["end_sec"], t["end"]) - max(g["start_sec"], t["start"]) > 1.0)
    a1, b1, a2, b2 = turn_spk
    assert a1 == a2 and b1 == b2 and a1 != b1, turn_spk
    english = " ".join(g["display_text"] for g in segs if g["language"] == "en").lower()
    assert "budget" in english and "friday" in english
    hindi = " ".join(g["display_text"] for g in segs if g["language"] == "hi")
    assert sum("ऀ" <= ch <= "ॿ" for ch in hindi) > 50, "Hindi must come out in Devanagari"
    assert all(w["start"] <= w["end"] for g in segs for w in g["words"])
    # timeline data the UI needs
    assert client.get(f"/api/sessions/{sid}/peaks").status_code == 200
    audio = client.get(f"/api/sessions/{sid}/audio", headers={"Range": "bytes=0-99"})
    assert audio.status_code == 206 and len(audio.content) == 100
    # rename once, every segment follows; search finds Hindi and English; export keeps Hindi
    spk = speakers[0]
    assert client.patch(f"/api/speakers/{spk['id']}", json={"display_name": "Rahul Sharma"}).status_code == 200
    again = client.get(f"/api/sessions/{sid}").json()
    names = {sp["id"]: sp["display_name"] for sp in again["speakers"]}
    assert all(names[g["speaker_id"]] == "Rahul Sharma" for g in again["segments"] if g["speaker_id"] == spk["id"])
    assert client.get("/api/search", params={"q": "budget"}).json()
    word = next(w for w in hindi.split() if len(w) >= 4)
    assert client.get("/api/search", params={"q": word}).json(), f"Hindi search for {word}"


def test_recover_crashed_two_track_recording(client, tmp_path):
    from sabhalekh import config

    meta = json.loads((DATA / "two_speaker_en_hi.json").read_text(encoding="utf-8"))
    audio, sr = sf.read(DATA / "two_speaker_en_hi.wav", dtype="int16")
    mic, system = np.zeros_like(audio), np.zeros_like(audio)
    for t in meta["turns"]:
        a, b = int(t["start"] * sr), int(t["end"] * sr)
        (mic if t["speaker"] == "Speaker A" else system)[a:b] = audio[a:b]
    d = config.RECORDING_TMP_DIR / "20260101-120000-crash1"
    d.mkdir(parents=True, exist_ok=True)
    for name, track in (("mic", mic), ("system", system)):
        # what a crash leaves behind: a header that still says 0 bytes, followed by the streamed samples
        from sabhalekh.audio.recorder import _wav_header

        (d / f"{name}_16k.wav").write_bytes(_wav_header(0) + track.astype("<i2").tobytes())
    (d / "state.json").write_text(json.dumps({"title": "Crashed standup", "started_at": 1767268800}),
                                  encoding="utf-8")
    rec = client.get("/api/recording/recoverable").json()
    assert any(r["id"] == d.name and abs(r["duration"] - len(audio) / sr) < 0.1 for r in rec)
    s = client.post(f"/api/recording/recover/{d.name}").json()
    assert s["title"] == "Crashed standup" and s["source_type"] == "recorded"
    assert not d.exists()
    s = wait_done(client, s["id"])
    assert s["status"] == "done", s["error_message"]
    data = client.get(f"/api/sessions/{s['id']}").json()
    by_id = {sp["id"]: sp for sp in data["speakers"]}
    you = [sp for sp in data["speakers"] if sp["is_self"]]
    assert len(you) == 1 and you[0]["display_name"] == "You"
    for g in data["segments"]:
        if g["language"] == "hi":
            assert by_id[g["speaker_id"]]["is_self"], "the mic track (Hindi speaker) must be 'You'"
        else:
            assert not by_id[g["speaker_id"]]["is_self"]
    assert Path(s["audio_path"]).name == "playback.ogg"


def test_session_records_engines_used(client):
    s = next(x for x in client.get("/api/sessions").json() if x["title"] == "two_speaker_en_hi")
    assert s["diarization_engine"].startswith("nemotron-3-diarization")
    assert s["asr_model"] == "nemotron-3.5-asr-0.6b"  # the default on every device, Accuracy pack or not
    assert s["profile_used"]
