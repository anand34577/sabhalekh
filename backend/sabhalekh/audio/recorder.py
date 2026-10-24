"""Meeting recorder: microphone + system audio (WASAPI loopback) as two separate 16 kHz mono tracks.

Crash safety: each track is a WAV file written incrementally (header first, sizes patched on stop) and flushed +
fsynced every few seconds, with state.json next to it. After a crash, `recoverable()` finds the folder and
`recover()` patches the headers from the file sizes: at most the last ~2 seconds are lost.

Alignment: WASAPI loopback delivers nothing while no sound is playing, and devices drift. Every track is kept on the
wall clock (minus pauses): missing audio is filled with silence, excess (drift) is trimmed. Both tracks therefore
stay sample-aligned over 3+ hour recordings, and memory use is constant.

Device changes: if a stream dies (headset unplugged) or the Windows default device changes while "default" is
selected, the stream is reopened on the new device; the gap is filled with silence and the user is notified.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .. import config

log = logging.getLogger("sabhalekh.recorder")

SR = 16000
FLUSH_SEC = 2.0
LEVEL_HZ = 15


class RecorderError(RuntimeError):
    pass


# ------------------------------------------------------------------ WAV writer that survives crashes
def _wav_header(data_bytes: int, channels: int = 1, rate: int = SR) -> bytes:
    return (b"RIFF" + struct.pack("<I", 36 + data_bytes) + b"WAVE" + b"fmt " +
            struct.pack("<IHHIIHH", 16, 1, channels, rate, rate * channels * 2, channels * 2, 16) +
            b"data" + struct.pack("<I", data_bytes))


def patch_wav_header(path: Path) -> int:
    """Rewrite RIFF/data sizes from the file size (crash recovery). Returns the number of samples."""
    size = path.stat().st_size
    data = max(0, size - 44)
    data -= data % 2
    with open(path, "r+b") as f:
        f.write(_wav_header(data))
        f.truncate(44 + data)
    return data // 2


class TrackWriter:
    def __init__(self, path: Path):
        self.path = path
        self.f = open(path, "wb")
        self.f.write(_wav_header(0))
        self.samples = 0
        self._last_sync = time.monotonic()

    def write(self, pcm: np.ndarray) -> None:
        if len(pcm):
            self.f.write(pcm.astype("<i2").tobytes())
            self.samples += len(pcm)
        now = time.monotonic()
        if now - self._last_sync >= FLUSH_SEC:
            self.f.flush()
            os.fsync(self.f.fileno())
            self._last_sync = now

    def close(self) -> None:
        self.f.flush()
        self.f.seek(0)
        self.f.write(_wav_header(self.samples * 2))
        self.f.close()


# ------------------------------------------------------------------ devices
def list_devices() -> dict:
    import pyaudiowpatch as pyaudio

    p = pyaudio.PyAudio()
    try:
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        mics, loops = [], []
        default_in = wasapi.get("defaultInputDevice", -1)
        default_out = wasapi.get("defaultOutputDevice", -1)
        default_loop = None
        try:
            default_loop = p.get_default_wasapi_loopback()["index"]
        except (OSError, LookupError):
            pass
        for i in range(p.get_device_count()):
            d = p.get_device_info_by_index(i)
            if d["hostApi"] != wasapi["index"]:
                continue
            item = {"index": d["index"], "name": d["name"], "channels": d["maxInputChannels"],
                    "rate": int(d["defaultSampleRate"])}
            if d.get("isLoopbackDevice"):
                item["default"] = d["index"] == default_loop
                loops.append(item)
            elif d["maxInputChannels"] > 0:
                item["default"] = d["index"] == default_in
                mics.append(item)
        return {"microphones": mics, "loopbacks": loops, "default_output": default_out}
    finally:
        p.terminate()


# ------------------------------------------------------------------ one capture stream
class _Capture:
    """A WASAPI input or loopback stream resampled to 16 kHz mono int16, pushed to a queue."""

    def __init__(self, kind: str, device_index: int | None):
        self.kind = kind  # mic | system
        self.requested = device_index  # None = follow the Windows default
        self.q: queue.Queue[np.ndarray] = queue.Queue(maxsize=2000)
        self.stream = None
        self.device_name = None
        self.device_index = None
        self.error: str | None = None
        self.last_data = time.monotonic()
        self._resampler = None
        self._channels = 1

    def _resolve(self, p) -> dict:
        if self.requested is not None:
            return p.get_device_info_by_index(self.requested)
        if self.kind == "system":
            return p.get_default_wasapi_loopback()
        import pyaudiowpatch as pyaudio

        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        return p.get_device_info_by_index(wasapi["defaultInputDevice"])

    def default_changed(self, p) -> bool:
        if self.requested is not None or self.device_index is None:
            return False
        try:
            return self._resolve(p)["index"] != self.device_index
        except Exception:  # noqa: BLE001
            return False

    def open(self, p) -> None:
        import av
        import pyaudiowpatch as pyaudio

        self.close()
        d = self._resolve(p)
        rate = int(d["defaultSampleRate"])
        self._channels = max(1, min(2, int(d["maxInputChannels"]) or 2))
        self._resampler = av.AudioResampler(format="s16", layout="mono", rate=SR)
        self._rate = rate
        self._layout = "stereo" if self._channels == 2 else "mono"

        def callback(in_data, frame_count, time_info, status):
            try:
                a = np.frombuffer(in_data, dtype=np.float32).reshape(-1, self._channels)
                frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(a.T), format="fltp", layout=self._layout)
                frame.sample_rate = self._rate
                out = [f.to_ndarray().reshape(-1) for f in self._resampler.resample(frame)]
                if out:
                    self.q.put_nowait(np.concatenate(out).astype(np.int16))
                self.last_data = time.monotonic()
            except queue.Full:
                pass
            except Exception as e:  # noqa: BLE001
                self.error = str(e)
            return (None, pyaudio.paContinue)

        self.stream = p.open(format=pyaudio.paFloat32, channels=self._channels, rate=rate, input=True,
                             input_device_index=d["index"], frames_per_buffer=int(rate * 0.05),
                             stream_callback=callback)
        self.stream.start_stream()
        self.device_name, self.device_index = d["name"], d["index"]
        self.error = None
        self.last_data = time.monotonic()
        log.info("%s capture on %s (%d Hz, %d ch)", self.kind, d["name"], rate, self._channels)

    def alive(self) -> bool:
        try:
            return self.stream is not None and self.stream.is_active() and self.error is None
        except Exception:  # noqa: BLE001
            return False

    def drain(self) -> np.ndarray:
        parts = []
        while True:
            try:
                parts.append(self.q.get_nowait())
            except queue.Empty:
                break
        return np.concatenate(parts) if parts else np.zeros(0, np.int16)

    def close(self) -> None:
        if self.stream is not None:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:  # noqa: BLE001
                pass
            self.stream = None


# ------------------------------------------------------------------ recorder
@dataclass
class RecState:
    id: str
    started_at: float
    title: str
    dir: str
    paused: bool = False
    paused_total: float = 0.0
    pause_started: float | None = None
    devices: dict = field(default_factory=dict)


class Recorder:
    def __init__(self, on_event: Callable[..., None]):
        self.emit = on_event
        self.state: RecState | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._caps: dict[str, _Capture] = {}
        self._writers: dict[str, TrackWriter] = {}
        self._t0 = 0.0

    @property
    def active(self) -> bool:
        return self.state is not None

    def status(self) -> dict:
        s = self.state
        if s is None:
            return {"active": False}
        return {"active": True, "id": s.id, "title": s.title, "paused": s.paused, "elapsed": self.elapsed(),
                "devices": {k: c.device_name for k, c in self._caps.items()}}

    def elapsed(self) -> float:
        s = self.state
        if s is None:
            return 0.0
        now = time.monotonic()
        paused = s.paused_total + ((now - s.pause_started) if s.pause_started else 0.0)
        return max(0.0, now - self._t0 - paused)

    def start(self, title: str, mic_device: int | None = None, loopback_device: int | None = None,
              capture_mic: bool = True, capture_system: bool = True) -> dict:
        import pyaudiowpatch as pyaudio

        import shutil

        free_mb = shutil.disk_usage(config.RECORDING_TMP_DIR).free // (1024 * 1024)
        if free_mb < 500:
            raise RecorderError(f"only {free_mb} MB of disk space left; free some space before recording")
        with self._lock:
            if self.state is not None:
                raise RecorderError("a recording is already running")
            rid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
            d = config.RECORDING_TMP_DIR / rid
            d.mkdir(parents=True, exist_ok=True)
            self._pa = pyaudio.PyAudio()
            errors = []
            self._caps = {}
            if capture_mic:
                self._caps["mic"] = _Capture("mic", mic_device)
            if capture_system:
                self._caps["system"] = _Capture("system", loopback_device)
            for k, c in list(self._caps.items()):
                try:
                    c.open(self._pa)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{'Microphone' if k == 'mic' else 'System audio'}: {e}")
                    del self._caps[k]
            if not self._caps:
                self._pa.terminate()
                raise RecorderError("no audio device could be opened. " + "; ".join(errors))
            self._writers = {k: TrackWriter(d / f"{k}_16k.wav") for k in self._caps}
            self.state = RecState(id=rid, started_at=time.time(), title=title, dir=str(d),
                                  devices={k: c.device_name for k, c in self._caps.items()})
            self._t0 = time.monotonic()
            self._save_state()
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="recorder", daemon=True)
            self._thread.start()
        for e in errors:
            self.emit("rec_warning", message=f"{e}. Recording continues with the other source.")
        if free_mb < 2048:  # ~1 MB per minute for both tracks: warn well before it matters
            self.emit("rec_warning", message=f"Low disk space ({free_mb} MB free).")
        self.emit("rec_state", **self.status())
        return self.status()

    def pause(self) -> dict:
        s = self.state
        if s and not s.paused:
            s.paused, s.pause_started = True, time.monotonic()
            self._save_state()
        self.emit("rec_state", **self.status())
        return self.status()

    def resume(self) -> dict:
        s = self.state
        if s and s.paused:
            s.paused_total += time.monotonic() - (s.pause_started or time.monotonic())
            s.paused, s.pause_started = False, None
            for c in self._caps.values():
                c.drain()  # discard what arrived during the pause
            self._save_state()
        self.emit("rec_state", **self.status())
        return self.status()

    def stop(self) -> dict:
        """Stop and finalize. Returns {"dir", "title", "tracks": {kind: path}, "duration", "started_at"}."""
        with self._lock:
            s = self.state
            if s is None:
                raise RecorderError("no recording is running")
            self._stop.set()
            if self._thread:
                self._thread.join(timeout=10)
            for c in self._caps.values():
                c.close()
            for w in self._writers.values():
                w.close()
            try:
                self._pa.terminate()
            except Exception:  # noqa: BLE001
                pass
            result = {"dir": s.dir, "title": s.title, "started_at": s.started_at,
                      "tracks": {k: str(w.path) for k, w in self._writers.items()},
                      "duration": max((w.samples for w in self._writers.values()), default=0) / SR}
            self.state = None
            self._caps, self._writers = {}, {}
        self.emit("rec_state", active=False)
        return result

    def _save_state(self) -> None:
        s = self.state
        if s:
            Path(s.dir, "state.json").write_text(json.dumps(s.__dict__), encoding="utf-8")

    # ------------------------------------------------------------------ worker
    def _loop(self) -> None:
        last_level = 0.0
        last_dev_check = time.monotonic()
        tails = {k: np.zeros(0, np.int16) for k in self._caps}
        while not self._stop.is_set():
            time.sleep(0.05)
            s = self.state
            if s is None:
                break
            now = time.monotonic()
            # device health and default-device changes
            if now - last_dev_check > 2.0:
                last_dev_check = now
                for k, c in self._caps.items():
                    if not c.alive() or c.default_changed(self._pa):
                        old = c.device_name
                        try:
                            import pyaudiowpatch as pyaudio

                            for cc in self._caps.values():
                                cc.close()
                            self._pa.terminate()
                            self._pa = pyaudio.PyAudio()  # refresh the device list
                            for cc in self._caps.values():
                                cc.open(self._pa)
                            self.emit("rec_warning", message=f"Audio device changed ({old} → {c.device_name}). "
                                                             "Recording continues.")
                        except Exception as e:  # noqa: BLE001
                            self.emit("rec_warning", message=f"{'Microphone' if k == 'mic' else 'System audio'} "
                                                             f"unavailable ({e}); retrying…")
                        break
            if s.paused:
                for c in self._caps.values():
                    c.drain()
                continue
            target = int(self.elapsed() * SR)
            for k, c in self._caps.items():
                w = self._writers[k]
                data = c.drain()
                if len(data):
                    tails[k] = np.concatenate([tails[k], data])[-2048:]
                lag = target - w.samples
                if len(data) > lag + SR // 2:  # running ahead of the wall clock (drift): trim
                    data = data[:max(0, lag + SR // 4)]
                w.write(data)
                lag = target - w.samples
                if lag > SR // 2 and now - c.last_data > 0.3:  # no data (silent loopback / dead device): pad
                    w.write(np.zeros(lag - SR // 10, np.int16))
            if now - last_level > 1.0 / LEVEL_HZ:
                last_level = now
                self.emit("rec_levels", elapsed=self.elapsed(),
                          **{k: _levels(tails[k] if self._caps[k].last_data > now - 0.3 else np.zeros(0))
                             for k in self._caps})


def _levels(a: np.ndarray, bands: int = 24) -> dict:
    if len(a) < 256:
        return {"rms": 0.0, "peak": 0.0, "bands": [0.0] * bands}
    x = a[-1024:].astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(x ** 2)))
    peak = float(np.abs(x).max())
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    edges = np.unique(np.geomspace(2, len(spec) - 1, bands + 1).astype(int))
    vals = [float(spec[a_:b].mean()) if b > a_ else 0.0 for a_, b in zip(edges[:-1], edges[1:])]
    vals = [min(1.0, max(0.0, (20 * np.log10(v + 1e-6) + 50) / 50)) for v in vals]
    vals += [0.0] * (bands - len(vals))
    return {"rms": min(1.0, rms * 4), "peak": peak, "bands": vals[:bands]}


# ------------------------------------------------------------------ crash recovery
def recoverable(active_id: str | None = None) -> list[dict]:
    out = []
    for d in sorted(config.RECORDING_TMP_DIR.glob("*")):
        if not d.is_dir() or d.name == active_id:
            continue
        tracks = {p.stem.split("_")[0]: p for p in d.glob("*_16k.wav")}
        if not tracks:
            continue
        info = {}
        if (d / "state.json").exists():
            try:
                info = json.loads((d / "state.json").read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        size = max(p.stat().st_size for p in tracks.values())
        out.append({"id": d.name, "title": info.get("title") or f"Recovered recording {d.name[:15]}",
                    "started_at": info.get("started_at") or d.stat().st_mtime,
                    "duration": max(0, size - 44) / 2 / SR, "dir": str(d)})
    return out


def recover(rec_id: str) -> dict:
    d = config.RECORDING_TMP_DIR / rec_id
    if not d.is_dir():
        raise RecorderError("unfinished recording not found")
    tracks = {}
    n = 0
    for p in d.glob("*_16k.wav"):
        n = max(n, patch_wav_header(p))
        tracks[p.stem.split("_")[0]] = str(p)
    info = {}
    if (d / "state.json").exists():
        info = json.loads((d / "state.json").read_text(encoding="utf-8"))
    return {"dir": str(d), "title": info.get("title") or "Recovered recording",
            "started_at": info.get("started_at") or time.time(), "tracks": tracks, "duration": n / SR}
