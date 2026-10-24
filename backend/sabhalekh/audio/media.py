"""Media I/O with the FFmpeg libraries bundled in PyAV (no ffmpeg.exe needed).

* probe(): duration / streams of any audio or video file
* to_wav16k(): decode + resample to 16 kHz mono 16-bit WAV (the pipeline format), streaming, constant memory
* make_playback(): Opus/Ogg copy for the player (small, seekable, plays in WebView2)
* Wav16k: random access to a 16 kHz WAV via memmap, float32 slices on demand
* compute_peaks(): min/max waveform peaks for the scrubber
"""
from __future__ import annotations

import json
import logging
import wave
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger("sabhalekh.media")

SR = 16000
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
SUPPORTED_EXT = AUDIO_EXT | VIDEO_EXT


class MediaError(RuntimeError):
    pass


def probe(path: str | Path) -> dict:
    import av

    try:
        with av.open(str(path)) as c:
            audio = [s for s in c.streams if s.type == "audio"]
            video = [s for s in c.streams if s.type == "video"]
            if not audio:
                raise MediaError("the file has no audio track")
            dur = None
            if c.duration:
                dur = c.duration / 1_000_000
            elif audio[0].duration and audio[0].time_base:
                dur = float(audio[0].duration * audio[0].time_base)
            return {"duration": dur or 0.0, "has_video": bool(video), "codec": audio[0].codec_context.name,
                    "sample_rate": audio[0].codec_context.sample_rate, "channels": audio[0].codec_context.channels}
    except MediaError:
        raise
    except Exception as e:  # noqa: BLE001
        raise MediaError(f"cannot read media file: {e}") from e


def to_wav16k(src: str | Path, dst: str | Path, progress: Callable[[float], None] | None = None,
              cancelled: Callable[[], bool] | None = None) -> float:
    """Decode the first audio stream to 16 kHz mono s16 WAV. Returns the duration in seconds."""
    import av

    total = probe(src)["duration"] or 0.0
    written = 0
    dst = Path(dst)
    tmp = dst.with_suffix(".part")
    try:
        with av.open(str(src)) as c, wave.open(str(tmp), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            stream = next(s for s in c.streams if s.type == "audio")
            stream.thread_type = "AUTO"
            res = av.AudioResampler(format="s16", layout="mono", rate=SR)
            for i, frame in enumerate(c.decode(stream)):
                for f in res.resample(frame):
                    a = f.to_ndarray().reshape(-1)
                    w.writeframes(a.astype("<i2").tobytes())
                    written += len(a)
                if i % 200 == 0:
                    if cancelled and cancelled():
                        raise InterruptedError("cancelled")
                    if progress and total:
                        progress(min(1.0, written / SR / total))
            for f in res.resample(None):
                a = f.to_ndarray().reshape(-1)
                w.writeframes(a.astype("<i2").tobytes())
                written += len(a)
    except (InterruptedError, MediaError):
        tmp.unlink(missing_ok=True)
        raise
    except Exception as e:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        raise MediaError(f"could not decode audio: {e}") from e
    if written == 0:
        tmp.unlink(missing_ok=True)
        raise MediaError("the audio track is empty")
    tmp.replace(dst)
    return written / SR


def make_playback(src: str | Path, dst: str | Path, bitrate: int = 64000, stereo: bool = False,
                  cancelled: Callable[[], bool] | None = None) -> None:
    """Opus in Ogg at 48 kHz, mono (imports) or stereo (recordings: left = mic, right = system)."""
    import av

    dst = Path(dst)
    tmp = dst.with_name(dst.stem + ".part.ogg")
    layout = "stereo" if stereo else "mono"
    try:
        with av.open(str(src)) as c, av.open(str(tmp), "w", format="ogg") as out:
            ins = next(s for s in c.streams if s.type == "audio")
            os_ = out.add_stream("libopus", rate=48000)
            os_.bit_rate = bitrate
            os_.layout = layout
            res = av.AudioResampler(format="s16", layout=layout, rate=48000)
            for i, frame in enumerate(c.decode(ins)):
                frame.pts = None
                for f in res.resample(frame):
                    for p in os_.encode(f):
                        out.mux(p)
                if cancelled and i % 500 == 0 and cancelled():
                    raise InterruptedError("cancelled")
            for f in res.resample(None):
                for p in os_.encode(f):
                    out.mux(p)
            for p in os_.encode(None):
                out.mux(p)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(dst)


def write_stereo_wav(left: str | Path, right: str | Path, dst: str | Path) -> None:
    """Interleave two 16 kHz mono WAVs (mic, system) into one stereo WAV, block by block."""
    a, b = Wav16k(left), Wav16k(right)
    n = max(a.frames, b.frames)
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        step = SR * 60
        for s in range(0, n, step):
            la = np.zeros(min(step, n - s), np.int16)
            lb = np.zeros_like(la)
            pa = a.int16(s, s + len(la))
            pb = b.int16(s, s + len(la))
            la[:len(pa)] = pa
            lb[:len(pb)] = pb
            w.writeframes(np.stack([la, lb], 1).astype("<i2").tobytes())


def mix_wavs(paths: list[str | Path], dst: str | Path) -> float:
    """Average several 16 kHz mono WAVs into one (soft-clipped), block by block. Returns the duration."""
    srcs = [Wav16k(p) for p in paths]
    n = max(s.frames for s in srcs)
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        step = SR * 60
        for s in range(0, n, step):
            m = min(step, n - s)
            acc = np.zeros(m, np.float32)
            for src in srcs:
                p = src.int16(s, s + m).astype(np.float32)
                acc[:len(p)] += p
            w.writeframes(np.clip(acc, -32768, 32767).astype("<i2").tobytes())
    return n / SR


class Wav16k:
    """Random access to a 16 kHz mono (or the first channel of a) 16-bit WAV without loading it."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        with wave.open(self.path, "rb") as w:
            if w.getsampwidth() != 2 or w.getframerate() != SR:
                raise MediaError(f"{path}: expected 16 kHz 16-bit WAV")
            self.channels = w.getnchannels()
            self.frames = w.getnframes()
        self.offset = _data_offset(self.path)
        self._mm = None

    @property
    def mm(self) -> np.ndarray:
        if self._mm is None:
            if self.frames == 0:
                self._mm = np.zeros(0, np.int16)
            else:
                m = np.memmap(self.path, dtype="<i2", mode="r", offset=self.offset,
                              shape=(self.frames * self.channels,))
                self._mm = m[:: self.channels] if self.channels > 1 else m
        return self._mm

    @property
    def duration(self) -> float:
        return self.frames / SR

    def int16(self, s: int, e: int) -> np.ndarray:
        return np.asarray(self.mm[max(0, s):max(0, min(e, self.frames))])

    def read(self, start_sec: float, end_sec: float) -> np.ndarray:
        return self.int16(int(start_sec * SR), int(end_sec * SR)).astype(np.float32) / 32768.0

    def close(self) -> None:
        self._mm = None


def _data_offset(path: str) -> int:
    with open(path, "rb") as f:
        if f.read(4) != b"RIFF":
            raise MediaError(f"{path}: not a WAV file")
        f.read(8)
        while True:
            hdr = f.read(8)
            if len(hdr) < 8:
                raise MediaError(f"{path}: no data chunk")
            cid, size = hdr[:4], int.from_bytes(hdr[4:], "little")
            if cid == b"data":
                return f.tell()
            f.seek(size + (size & 1), 1)


def compute_peaks(wav: str | Path, dst: str | Path, buckets_per_sec: int = 20) -> dict:
    """Peaks (max |amplitude| per 50 ms, 0..255) for the waveform scrubber, saved as JSON."""
    w = Wav16k(wav)
    step = SR // buckets_per_sec
    n = w.frames // step
    peaks = np.zeros(n, np.uint8)
    block = step * buckets_per_sec * 60
    for s in range(0, n * step, block):
        a = np.abs(w.int16(s, min(s + block, n * step)).astype(np.int32))
        k = len(a) // step
        if k:
            p = a[:k * step].reshape(k, step).max(1)
            peaks[s // step:s // step + k] = np.minimum(255, np.sqrt(p / 32768.0) * 255).astype(np.uint8)
    data = {"rate": buckets_per_sec, "duration": w.duration, "peaks": peaks.tolist()}
    Path(dst).write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return data
