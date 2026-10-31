"""Udgam Labs Shruti (55M, Hindi / English / Hinglish) on the Cactus "needle" engine.

Shruti is a Whistle model retrained on Indian speech: one 29.5 MB `shruti.cact` file, run by `needle.Whistle` through
the native engine library (`libneedle`). Both ship with the app (`models/asr/shruti`, `bin/needle`); nothing is
fetched at run time, and the package's anonymous usage statistics are switched off before it is imported.

What the model gives, and what is done with it here:
- Hindi comes out in Devanagari and English words in lowercase Latin, so Hinglish needs no script handling. The
  "Roman" script setting is applied afterwards by the pipeline (Devanagari -> Roman); "Devanagari" cannot turn
  English words into Devanagari, they stay English.
- No punctuation or capitals, numbers as words: that is how the model was trained.
- Language: auto-detected per chunk (as good as forcing Hindi on Hinglish). English is set only when the user picks
  "English", which helps Indian-accented English.
- Custom vocabulary (the "names and terms" setting) becomes the model's keyword list.
- Word timings come from the engine; if it returns none, the words are spread evenly over the chunk.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from .. import config
from .. import text as textutil
from .base import ASROptions, ASRSegment, AudioReader, Chunk, OutOfMemory, Word

log = logging.getLogger("sabhalekh.asr")

LIB_NAME = config.NEEDLE_LIB_NAME
LANGS = ("hi", "en")
SAMPLE_RATE = 16000
MIN_SAMPLES = 1600  # < 0.1 s of 16 kHz audio: nothing to decode
TAIL_MIN_SEC = 2.0  # decoding that stops this far before the chunk ends is checked for dropped speech
TAIL_RMS = 0.004  # about -48 dBFS: below this the remainder is silence or room noise
TAIL_PASSES = 3
_lock = threading.Lock()  # the engine keeps one model per process and is not thread-safe


def library_path() -> Path:
    """The native engine library: NEEDLE3_LIB_PATH if set, else the one shipped in <app>/bin/needle."""
    return Path(os.environ.get("NEEDLE3_LIB_PATH") or config.NEEDLE_LIB_DIR / LIB_NAME)


def runtime_installed() -> bool:
    import importlib.util

    return library_path().is_file() and importlib.util.find_spec("needle") is not None


def _prepare_runtime() -> None:
    """Point the package at the shipped library (its default would download one) and turn its statistics off."""
    os.environ["NEEDLE_TELEMETRY"] = "0"
    os.environ["DO_NOT_TRACK"] = "1"
    lib = library_path()
    if not lib.is_file():
        raise RuntimeError(f"the Shruti runtime ({LIB_NAME}) is missing from {lib.parent}; reinstall Sabhalekh")
    os.environ["NEEDLE3_LIB_PATH"] = str(lib)
    try:
        os.add_dll_directory(str(lib.parent))
    except (OSError, AttributeError):
        pass


def keywords_from_prompt(prompt: str) -> list[str]:
    """The names-and-terms setting (free text, usually comma or line separated) as a keyword list."""
    seen: dict[str, None] = {}
    for k in re.split(r"[,;\n।]+", prompt or ""):
        k = " ".join(k.split())
        if k:
            seen.setdefault(k)
    return list(seen)[:64]


def chunk_language(detected: str | None, text: str) -> str:
    """Hindi or English for one decoded chunk: the engine's answer when it is one of the two, else the script."""
    if detected in LANGS:
        return detected
    return "hi" if textutil.script_language(text) in ("hi", "mixed") else "en"


def _rms(pcm: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(pcm)))) if len(pcm) else 0.0


PRONOUN_I = re.compile(r"^i(?=$|['’])", re.IGNORECASE)


def _word_text(w: dict) -> str:
    """The word as written. The model writes everything lowercase; the English pronoun "i" (i, i'm, i'll...) is
    always a capital, so that one case is restored."""
    t = str(w.get("word") if w.get("word") is not None else w.get("text") or "").strip()
    return PRONOUN_I.sub("I", t)


def _seconds(values: list[float], duration: float) -> float:
    """Scale to convert the engine's word times to seconds: 1 if they fit the chunk as seconds, else 1/1000."""
    return 1.0 if not values or max(values) <= duration * 1.5 + 1.0 else 0.001


class ShrutiEngine:
    name = "needle-whistle"
    release_after_job = True

    def __init__(self, model_path: str, model_id: str, threads: int = 4):
        self.model_path, self.model_id = model_path, model_id
        self.threads = threads
        self.model = None

    # ------------------------------------------------------------------ lifecycle
    def _weights(self) -> str:
        p = Path(self.model_path)
        if p.is_file():
            return str(p)
        files = sorted(p.glob("*.cact"))
        if not files:
            raise RuntimeError(f"no .cact model file in {p}")
        return str(files[0])

    def load(self) -> None:
        if self.model is not None:
            return
        _prepare_runtime()
        from needle import Whistle

        try:
            self.model = Whistle(self._weights())
        except MemoryError as e:
            raise OutOfMemory(str(e)) from e
        log.info("loaded %s (needle engine, CPU)", self.model_id)

    def unload(self) -> None:
        self.model = None  # the library keeps its copy of the weights until the process ends (29.5 MB)

    @property
    def translate_ok(self) -> bool:
        return False

    # ------------------------------------------------------------------ results
    def _segment(self, r: dict, start: float, end: float, language: str | None = None) -> ASRSegment | None:
        text = " ".join(str(r.get("text") or "").split())
        if not text:
            return None
        text = " ".join(PRONOUN_I.sub("I", t) for t in text.split())
        lang = language or chunk_language(r.get("language"), text)
        raw = [w for w in (r.get("words") or []) if _word_text(w)]
        duration = max(1e-3, end - start)
        words: list[Word] = []
        if raw:
            scale = _seconds([float(w.get("end") or 0.0) for w in raw], duration)
            prev_end = start
            for w in raw:
                p = w.get("probability")
                t0 = max(start + float(w.get("start") or 0.0) * scale, prev_end)
                t1 = max(t0, min(end, start + float(w.get("end") or 0.0) * scale))
                prev_end = t1
                words.append(Word(t0, t1, " " + _word_text(w), float(p) if p is not None and p == p else 1.0))
        else:  # no timings from the engine: even spread, so click-to-play still lands inside the chunk
            toks = text.split()
            step = duration / len(toks)
            words = [Word(start + i * step, start + (i + 1) * step, " " + t, 1.0) for i, t in enumerate(toks)]
        confs = [w.confidence for w in words]
        logp = float(np.mean(np.log(np.clip(confs, 1e-6, 1.0))))
        return ASRSegment(start=words[0].start, end=words[-1].end, text="".join(w.text for w in words).strip(),
                          language=lang, words=words, avg_logprob=logp, no_speech_prob=0.0, compression_ratio=1.0)

    # ------------------------------------------------------------------ transcription
    def _decode_chunk(self, pcm: np.ndarray, start: float, end: float, forced: str | None,
                      keywords: list[str] | None) -> list[ASRSegment]:
        """Decode one chunk, then the rest of it if the model stopped early.

        In auto mode a chunk that switches language (a Hinglish speaker, or English followed by Hindi) is
        often decoded only up to the switch; the speech after it is dropped without a trace. When decoding ends well
        before the chunk does and the remainder is audible, the remainder is decoded as a chunk of its own."""
        out: list[ASRSegment] = []
        pos = start
        for _ in range(TAIL_PASSES + 1):
            part = pcm[int(round((pos - start) * SAMPLE_RATE)):]
            if len(part) < MIN_SAMPLES:
                break
            with _lock:
                r = self.model.transcribe(part, language=forced, keywords=keywords, word_timestamps=True)
            seg = self._segment(r, pos, end, forced)
            if seg is None:
                break
            out.append(seg)
            tail = pcm[int(round((seg.end - start) * SAMPLE_RATE)):]
            if end - seg.end < TAIL_MIN_SEC or seg.end <= pos + 0.2 or _rms(tail) < TAIL_RMS:
                break
            pos = seg.end
        return out

    def transcribe(self, read: AudioReader, chunks: Sequence[Chunk], options: ASROptions,
                   progress: Callable[[float], None] | None = None,
                   cancelled: Callable[[], bool] | None = None) -> list[ASRSegment]:
        if options.language_mode == "translate":
            raise RuntimeError(f"{self.model_id} cannot translate; use a Whisper model from the Accuracy pack")
        self.load()
        forced = options.language_mode if options.language_mode in LANGS else None  # None = detect per chunk
        keywords = keywords_from_prompt(options.initial_prompt) or None
        results: list[ASRSegment] = []
        for i, (s, e) in enumerate(chunks):
            if cancelled and cancelled():
                raise InterruptedError("cancelled")
            pcm = np.ascontiguousarray(read(s, e), dtype=np.float32)
            if len(pcm) >= MIN_SAMPLES:
                results.extend(self._decode_chunk(pcm, s, e, forced, keywords))
            if progress:
                progress((i + 1) / max(1, len(chunks)))
        return results
