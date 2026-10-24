"""The onboarding device test must not leave files behind: a left-over folder in recordings-in-progress shows up as an
"unfinished recording" to recover on the next start (seen on Windows, where a memory-mapped WAV cannot be deleted)."""
from types import SimpleNamespace

import numpy as np
import soundfile as sf

TOKEN = "device-test-token-0123456789"


class FakeRecorder:
    def __init__(self, emit):
        self.dir = None

    def start(self, title, mic_device=None, loopback_device=None):
        from sabhalekh import config

        self.dir = config.RECORDING_TMP_DIR / "20260101-000000"
        self.dir.mkdir(parents=True, exist_ok=True)

    def stop(self):
        tracks = {}
        for kind, amp in (("mic", 0.2), ("system", 0.0)):
            path = self.dir / f"{kind}_16k.wav"
            sf.write(path, (amp * np.sin(np.arange(16000) / 5)).astype("float32"), 16000, subtype="PCM_16")
            tracks[kind] = str(path)
        return {"dir": str(self.dir), "tracks": tracks}


def test_device_test_cleans_up(db, monkeypatch):
    from fastapi.testclient import TestClient

    from sabhalekh import api, config
    from sabhalekh.audio import recorder as rec

    config.ensure_dirs()
    monkeypatch.setattr(rec, "Recorder", FakeRecorder)
    monkeypatch.setattr(api.time, "sleep", lambda s: None)
    state = api.App(db, None, None, None, None, SimpleNamespace(active=False), TOKEN)
    client = TestClient(api.create_app(state), base_url="http://127.0.0.1")
    r = client.post("/api/recording/test", json={}, headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.json()["tracks"]["mic"]["ok"] and not r.json()["tracks"]["system"]["ok"]
    assert rec.recoverable() == []
    assert not (config.RECORDING_TMP_DIR / "20260101-000000").exists()
