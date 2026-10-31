"""NVIDIA Nemotron 3.5 ASR (and any other transcribe.cpp GGUF model) on ggml: Vulkan GPU / iGPU or CPU.

Measured on a GTX 1650 + Radeon iGPU + Ryzen 5 5600H laptop, 129 s Hinglish meeting audio in 28 s chunks
(Nemotron 3.5 ASR 0.6B Q8_0):
    GTX 1650 (Vulkan)   18x real time   +140 MB RAM, 730 MB VRAM
    Radeon iGPU         19x real time   +950 MB RAM (shared memory)
    CPU, 6 threads       8x real time   +1.1 GB RAM
against Whisper large-v3-turbo's ~8x on the same GPU at up to 1.9 GB VRAM. tools/benchmark_wer.py on the 12 FLEURS
Hindi test clips: WER 19.2 % (large-v3-turbo 26.8 %, large-v3 23.0 %), 18x real time (turbo 2.1x, large-v3 0.7x).

Language: in Auto mode each chunk is decoded with the model's own language detection. Nemotron appends a locale tag
(`<en-US>`) after non-Hindi sentences and none after Hindi ones, so the tag decides when present and the script
(Devanagari or not) otherwise. One chunk = one speaker turn (the pipeline cuts at speaker changes), so a chunk
rarely mixes languages. run_batch() is not used: measured slower than one run() per chunk on both GPUs.

The model loads in ~1 s, so it is freed after every job (`release_after_job`) instead of holding VRAM/RAM while idle.
"""
from __future__ import annotations

import logging
import math
import os
import re
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from .. import config
from .. import text as textutil
from .base import ASROptions, ASRSegment, AudioReader, Chunk, OutOfMemory, Word

log = logging.getLogger("sabhalekh.asr")

TAG = re.compile(r"<([a-z]{2,3})(?:-[A-Za-z]{2,4})?>")
LOCALES = {"en": "en-US", "hi": "hi-IN"}
MIN_FREE_VRAM_MB = 1200  # measured peak ~740 MB for a 28 s chunk, plus headroom for other apps
_lib_ready = False


def _library():
    """Import transcribe_cpp with the bundled native library (<app>/bin/transcribe) unless one is configured."""
    global _lib_ready
    if not _lib_ready:
        bundled = config.TRANSCRIBE_LIB_DIR / config.TRANSCRIBE_LIB_NAME
        if not os.environ.get("TRANSCRIBE_LIBRARY") and bundled.exists():
            os.environ["TRANSCRIBE_LIBRARY"] = str(bundled)
        if config.TRANSCRIBE_LIB_DIR.is_dir():
            try:
                os.add_dll_directory(str(config.TRANSCRIBE_LIB_DIR))  # ggml*.dll next to transcribe.dll
            except (OSError, AttributeError):
                pass
    import transcribe_cpp

    if not _lib_ready:
        transcribe_cpp.set_log_callback(lambda level, msg: log.debug("transcribe.cpp: %s", msg.rstrip()))
        _lib_ready = True
    return transcribe_cpp


def list_devices() -> list[dict]:
    """Accelerators transcribe.cpp can use ("gpu" = discrete with its own VRAM, "igpu" = shared memory)."""
    tc = _library()
    return [{"name": d.name, "description": d.description.strip(), "kind": d.kind, "type": d.device_type,
             "device_id": d.device_id, "memory_mb": d.memory_total // (1024 * 1024),
             "memory_free_mb": d.memory_free // (1024 * 1024)}
            for d in tc.backends() if d.device_type in ("gpu", "igpu")]


def _is_oom(e: BaseException) -> bool:
    from ..hardware import is_oom_error

    return type(e).__name__ == "OutOfMemory" or is_oom_error(e)


def chunk_language(raw: str, text: str) -> str:
    """Language of one decoded chunk: the last locale tag, else Hindi when mostly Devanagari, else English."""
    tags = TAG.findall(raw)
    if tags:
        return tags[-1]
    letters = [ch for ch in text if ch.isalpha()]
    deva = sum(textutil.has_devanagari(ch) for ch in letters)
    return "hi" if letters and deva / len(letters) > 0.5 else "en"


class TranscribeCppEngine:
    name = "transcribe-cpp"
    release_after_job = True

    def __init__(self, model_path: str, model_id: str, accel: str = "gpu", threads: int = 4):
        self.model_path, self.model_id = model_path, model_id
        self.accel, self.threads = accel, threads  # accel: gpu | igpu | cpu
        self.model = self.session = None
        self.device_label = "CPU"

    # ------------------------------------------------------------------ lifecycle
    def _gguf(self) -> str:
        p = Path(self.model_path)
        if p.is_file():
            return str(p)
        files = sorted(p.glob("*.gguf"))
        if not files:
            raise RuntimeError(f"no .gguf model file in {p}")
        return str(files[0])

    def _device(self, tc):
        """The device of this profile, never by index: Vulkan numbers devices differently from process to process.
        Discrete GPUs are taken only with enough free VRAM; the caller's OOM handling then steps down to the
        integrated GPU or the CPU."""
        devs = tc.backends()
        if self.accel in ("gpu", "igpu"):
            cands = sorted((d for d in devs if d.device_type == self.accel), key=lambda d: -d.memory_free)
            if not cands:
                raise OutOfMemory(f"no {self.accel} device available to transcribe.cpp")
            d = cands[0]
            if self.accel == "gpu" and d.memory_free and d.memory_free // (1024 * 1024) < MIN_FREE_VRAM_MB:
                raise OutOfMemory(f"only {d.memory_free // (1024 * 1024)} MB VRAM free on {d.description.strip()} "
                                  f"(failed to allocate)")
            return d
        return next(d for d in devs if d.device_type == "cpu")

    def load(self) -> None:
        if self.model is not None:
            return
        tc = _library()
        try:
            dev = self._device(tc)
            self.model = tc.Model(self._gguf(), device=dev)
            self.session = self.model.session(n_threads=self.threads)
        except OutOfMemory:
            self.unload()
            raise
        except Exception as e:  # noqa: BLE001
            self.unload()
            if _is_oom(e):
                raise OutOfMemory(str(e)) from e
            raise
        self.device_label = dev.description.strip()
        log.info("loaded %s on %s (%s, %s)", self.model_id, self.device_label, dev.kind, self.model.variant)

    def unload(self) -> None:
        for h in (self.session, self.model):
            if h is not None:
                try:
                    h.close()
                except Exception:  # noqa: BLE001
                    pass
        self.session = self.model = None

    @property
    def translate_ok(self) -> bool:
        return False

    # ------------------------------------------------------------------ transcription
    def _segment(self, r, start: float, end: float) -> ASRSegment | None:
        text = TAG.sub("", r.text)
        text = " ".join(text.split())
        if not text:
            return None
        lang = chunk_language(r.raw_text or r.text, text)
        words: list[Word] = []
        logps: list[float] = []
        prev_end = start
        for w in r.words:
            wt = TAG.sub("", w.text).strip()
            if not wt:
                continue
            toks = r.tokens[w.first_token:w.first_token + w.n_tokens] if w.n_tokens else ()
            ps = [t.p for t in toks if t.p == t.p and t.p > 0]  # NaN-safe
            conf = float(np.mean(ps)) if ps else 1.0
            logps.extend(math.log(p) for p in ps)
            # token times are 80 ms frames and neighbours can share one: keep them ordered
            t0 = max(start + w.t0_ms / 1000.0, prev_end)
            t1 = max(t0, min(end, start + w.t1_ms / 1000.0))
            prev_end = t1
            words.append(Word(t0, t1, " " + wt, conf))
        if not words:
            return None
        text = "".join(w.text for w in words).strip()
        return ASRSegment(start=words[0].start, end=words[-1].end, text=text, language=lang, words=words,
                          avg_logprob=float(np.mean(logps)) if logps else 0.0, no_speech_prob=0.0,
                          compression_ratio=1.0)

    def transcribe(self, read: AudioReader, chunks: Sequence[Chunk], options: ASROptions,
                   progress: Callable[[float], None] | None = None,
                   cancelled: Callable[[], bool] | None = None) -> list[ASRSegment]:
        if options.language_mode == "translate":
            raise RuntimeError(f"{self.model_id} cannot translate; use a Whisper model from the Accuracy pack")
        self.load()
        language = LOCALES.get(options.language_mode)  # None = the model detects it per chunk
        results: list[ASRSegment] = []
        for i, (s, e) in enumerate(chunks):
            if cancelled and cancelled():
                raise InterruptedError("cancelled")
            pcm = np.ascontiguousarray(read(s, e), dtype=np.float32)
            if len(pcm) >= 1600:  # < 0.1 s: nothing to decode
                try:
                    r = self.session.run(pcm, language=language, timestamps="token", keep_special_tags=True)
                except Exception as ex:  # noqa: BLE001
                    partial = getattr(ex, "partial_result", None)
                    if partial is not None:  # truncated/repetitive output: keep what was decoded
                        log.warning("chunk %.1f-%.1f s: %s; keeping the partial transcript", s, e, ex)
                        r = partial
                    elif _is_oom(ex):
                        raise OutOfMemory(f"{type(ex).__name__}: {ex}") from ex
                    else:
                        raise
                seg = self._segment(r, s, e)
                if seg:
                    if language:
                        seg.language = options.language_mode
                    results.append(seg)
            if progress:
                progress((i + 1) / max(1, len(chunks)))
        return results
