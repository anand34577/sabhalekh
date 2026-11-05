"""Hima-ASR (Prahaladha, 0.46B; 11 Indian languages and English) on ONNX Runtime, without PyTorch.

Hima is a Qwen3-ASR audio encoder feeding a Gemma-3-270M text decoder. The authors publish ONNX exports
(`Prahaladha/hima-asr-ONNX`: Apache-2.0 for their parts, Gemma Terms of Use for the decoder). This module runs
them directly; the front end and the greedy decoding loop follow the authors' reference `hima_onnx.py`.

Folder layout (what `tools/fetch_models.py --with-hima` creates, and what an Offline Model Pack carries):
    onnx/encoder_model_q4.onnx(+_data)    4-bit encoder (214 MB)   default: as accurate as int8, smaller, faster
    onnx/encoder_model_int8.onnx(+_data)  8-bit encoder (342 MB)   optional
    onnx/decoder_model_int8.onnx(+_data)  8-bit decoder (145 MB)   always
    embed.npy  keep_ids.json  start_of_text.npy  mel_filters.npy  tokenizer.json
Measured on the 12 FLEURS Hindi test clips (Ryzen laptop, ORT 1.31, CPU): q4 and int8 both 9.2 % WER; q4 8.5x and
int8 7.2x real time. The authors' fp32 export (1.8 GB, four times the size) is not supported.

Where it runs: the decoder always on the CPU. It writes one piece at a time, and each step is too small for a GPU:
on DirectML it measured ten times slower on both a GTX 1650 and a Radeon iGPU. The encoder, one large pass per
clip, runs on the profile's GPU or iGPU through DirectML when onnxruntime has it (onnxruntime-directml): on the
GTX 1650 it is twice as fast as on the CPU (whole model 9.8x instead of 7.1x real time); on the iGPU it is as fast
as the CPU and leaves the CPU free. DirectML works on any DirectX 12 GPU (NVIDIA, AMD, Intel) and needs no CUDA.
If the GPU fails to start or fails mid-run, the encoder moves to the CPU and the clip is decoded again.

What the model gives, and what is done with it here:
- A transcript without punctuation or capitals (lowercased, symbols stripped). There are no word timings or per-word
  probabilities, so the words are spread over the part of the chunk that holds speech, in proportion to their length.
- Language: detected by the model when "Automatic"; "English only" and "Hindi only" are passed through. The language
  label of a segment comes from the script it was written in when the model chose it.
- Style: "Devanagari" asks for the native script; "As spoken" and "Roman" ask for the *mixed* style (Indian words in
  their own script, English words in Latin letters), which keeps Hinglish readable and transliterates cleanly.
- Custom vocabulary is not supported by the model. It cannot translate.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from .base import ASROptions, ASRSegment, AudioReader, Chunk, OutOfMemory, Word

log = logging.getLogger("sabhalekh.asr")

SAMPLE_RATE = 16000
MAX_CHUNK_SEC = 30.0  # the model is trained on clips of 1 to 30 seconds
MIN_SAMPLES = 1600  # < 0.1 s: nothing to decode
SILENCE_RMS = 1e-4  # digital silence: the model would invent text for it
N_FFT, HOP, N_MELS = 400, 160, 128
MEL_BLOCK = 100  # the encoder takes mel frames in blocks of 100 (1 s)
LAYERS_KV = (18, 1, 0, 256)  # decoder key/value cache: layers, batch, past length, head width
BOS, EOS = 2, 1  # Gemma token ids
LANGUAGE_NAMES = {"as": "assamese", "bn": "bengali", "en": "english", "gu": "gujarati", "hi": "hindi",
                  "kn": "kannada", "ml": "malayalam", "mr": "marathi", "or": "odia", "pa": "punjabi",
                  "ta": "tamil", "te": "telugu"}
SHARED_FILES = ("tokenizer.json", "embed.npy", "keep_ids.json", "start_of_text.npy", "mel_filters.npy")
# encoder precision -> (encoder, decoder), in the order they are preferred
VARIANTS = {"q4": ("encoder_model_q4.onnx", "decoder_model_int8.onnx"),
            "int8": ("encoder_model_int8.onnx", "decoder_model_int8.onnx")}
# Only what the transcript needs: the encoder's per-layer states and the decoder's hidden states feed the authors'
# decision head, which is not used here, and leaving them out spares a 25 x frames x 1024 copy per clip.
DECODER_OUT = ["logits", "present_k", "present_v"]
DML = "DmlExecutionProvider"  # onnxruntime-directml; official wheels have no Vulkan or CUDA-free GPU provider

# Script blocks -> language, to label a segment when the model chose the language itself. Bengali and Assamese share
# a script; Devanagari is Hindi (Marathi uses it too, but Hindi is the product's language).
SCRIPTS = (("ऀ", "ॿ", "hi"), ("ঀ", "৿", "bn"), ("਀", "੿", "pa"),
           ("઀", "૿", "gu"), ("଀", "୿", "or"), ("஀", "௿", "ta"),
           ("ఀ", "౿", "te"), ("ಀ", "೿", "kn"), ("ഀ", "ൿ", "ml"))
PRONOUN_I = re.compile(r"^i(?=$|['’])", re.IGNORECASE)


# ---------------------------------------------------------------------------------------------------------- files
def find_variants(path: str | Path) -> list[str]:
    """Precisions that are completely installed in `path` (both graphs and their external weights)."""
    onnx = Path(path) / "onnx"
    found = []
    for name, files in VARIANTS.items():
        if all((onnx / f).is_file() and (onnx / (f + "_data")).is_file() for f in files):
            found.append(name)
    return found


def missing_files(path: str | Path) -> list[str]:
    """What keeps the model from loading: the shared files, or every encoder/decoder pair."""
    p = Path(path)
    missing = [f for f in SHARED_FILES if not (p / f).is_file()]
    if not find_variants(p):
        missing.append("onnx/encoder_model_q4.onnx + decoder_model_int8.onnx")
    return missing


def runtime_installed() -> bool:
    import importlib.util

    return all(importlib.util.find_spec(m) is not None for m in ("onnxruntime", "tokenizers"))


# ------------------------------------------------------------------------------------------------------ text
_JOINERS = {"‌", "‍"}
_TAG = re.compile(r"<[^>]*>|\[[^\]]*\]")
_CHILLU_OF = {"ണ": "ൺ", "ന": "ൻ", "ര": "ർ", "ല": "ൽ", "ള": "ൾ", "ക": "ൿ"}
_CHILLU = re.compile("(?<!്)([ണനരലളക])്‍?(?![ഀ-ൿ])")


def clean_text(text: str) -> str:
    """The model's output as the product shows it: NFC, Malayalam chillus restored, tags and symbols removed,
    lowercase, single spaces. Apostrophes inside words (don't) stay."""
    text = unicodedata.normalize("NFC", text or "")
    text = _CHILLU.sub(lambda m: _CHILLU_OF[m.group(1)], text)
    text = _TAG.sub(" ", text)
    out = []
    for i, ch in enumerate(text):
        kind = unicodedata.category(ch)[0]
        if ch in _JOINERS:
            out.append(ch)
        elif ch in "'’" and 0 < i < len(text) - 1 and text[i - 1].isalpha() and text[i + 1].isalpha():
            out.append("'")
        elif kind in "LMN":
            out.append(ch)
        else:
            out.append(" ")
    return " ".join("".join(out).lower().split())


def _loop_length(p: list[int]) -> int:
    """Length of the unit the piece list ends in when it repeats (a stuck decoder), else 0."""
    for size in range(1, 9):
        times = 6 if size == 1 else 4
        if len(p) >= size * times and p[-size * times:] == p[-size:] * times:
            return size
    for size in range(9, 81):
        if len(p) >= size * 3 and p[-size * 3:] == p[-size:] * 3:
            return size
    return 0


def _cut_loop(p: list[int]) -> list[int]:
    size = _loop_length(p)
    if size == 0:
        return p
    unit = p[-size:]
    while len(p) >= 2 * size and p[-2 * size:] == unit * 2:
        p = p[:-size]
    return p


def text_language(text: str) -> str:
    """Language of a decoded chunk from its script: the dominant Indian script, else English. Devanagari with
    English words in it counts as Hindi (Hinglish)."""
    counts = {code: 0 for _, _, code in SCRIPTS}
    latin = 0
    for ch in text:
        if ch.isalpha():
            if ch < "ɐ":
                latin += 1
                continue
            for lo, hi, code in SCRIPTS:
                if lo <= ch <= hi:
                    counts[code] += 1
                    break
    best = max(counts, key=counts.get)
    if counts[best] == 0 or (latin > 4 * counts[best]):
        return "en"
    return best


# ---------------------------------------------------------------------------------------------------- audio
def log_mel(x: np.ndarray, filters: np.ndarray) -> tuple[np.ndarray, int]:
    """Log-mel features as Qwen3ASRFeatureExtractor computes them: (128, T) padded to a multiple of 100 frames,
    and the number of real frames. Clips under 0.5 s are zero-padded to 0.5 s."""
    if len(x) < 8000:
        x = np.pad(x, (0, 8000 - len(x)))
    xp = np.pad(x, (N_FFT // 2, N_FFT // 2), mode="reflect")
    n_frames = 1 + (len(xp) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    win = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N_FFT) / N_FFT)).astype(np.float32)  # periodic Hann
    spec = np.fft.rfft(xp[idx] * win, axis=1)
    mag = (spec.real ** 2 + spec.imag ** 2).astype(np.float32)[:-1].T  # (201, frames - 1)
    log = np.log10(np.maximum(filters.T @ mag, 1e-10))
    log = np.maximum(log, log.max() - 8.0)
    log = ((log + 4.0) / 4.0).astype(np.float32)
    n_valid = log.shape[1]
    return np.pad(log, ((0, 0), (0, (-n_valid) % MEL_BLOCK))), n_valid


def _encoder_frames(n_mel: int) -> int:
    """Encoder output frames for n_mel valid mel frames: three stride-2 convolutions per 100-frame block."""
    def post(n: int) -> int:
        for _ in range(3):
            n = (n - 1) // 2 + 1 if n > 0 else 0
        return n

    blocks = -(-n_mel // MEL_BLOCK)
    return sum(post(min(MEL_BLOCK, n_mel - i * MEL_BLOCK)) for i in range(blocks))


def speech_clock(pcm: np.ndarray, frame: int = 320) -> tuple[np.ndarray, np.ndarray]:
    """(frame times in seconds, cumulative speech seconds) for 20 ms frames of `pcm`. A frame is speech when its
    level is within about 20 dB of the loud frames (floor: about -60 dBFS). Used to place words, which the model
    does not time: pauses and silent edges of the chunk then take no words."""
    n = len(pcm) // frame
    if n == 0:
        return np.zeros(1), np.zeros(1)
    rms = np.sqrt(np.mean(np.square(pcm[:n * frame].reshape(n, frame)), axis=1))
    floor = max(1e-3, 0.1 * float(np.percentile(rms, 90)))
    active = (rms >= floor).astype(np.float64)
    if active.sum() == 0:
        active[:] = 1.0
    cum = np.concatenate([[0.0], np.cumsum(active)]) * frame / SAMPLE_RATE
    times = np.arange(n + 1) * frame / SAMPLE_RATE
    return times, cum


def place_words(words: list[str], pcm: np.ndarray, start: float, end: float) -> list[Word]:
    """Spread `words` over the speech of the chunk [start, end] in proportion to their length."""
    times, cum = speech_clock(pcm)
    weights = np.array([len(w) + 1.0 for w in words])
    edges = np.concatenate([[0.0], np.cumsum(weights)]) / weights.sum() * cum[-1]
    # A word starts where the speech clock leaves its start edge and ends where it reaches its end edge, so a
    # pause between two words (or silence at the chunk's edges) belongs to neither.
    begin = times[np.clip(np.searchsorted(cum, edges[:-1], side="right") - 1, 0, len(times) - 1)]
    finish = times[np.clip(np.searchsorted(cum, edges[1:], side="left"), 0, len(times) - 1)]
    begin, finish = np.clip(begin + start, start, end), np.clip(finish + start, start, end)
    return [Word(float(begin[i]), float(max(begin[i], finish[i])), " " + w, 1.0) for i, w in enumerate(words)]


# ----------------------------------------------------------------------------------------------------- engine
def providers_for(accel: str, available: list[str]) -> list:
    """ONNX Runtime providers for the encoder on a GPU: DirectML on the discrete GPU for accel "gpu" (high
    performance) or the integrated one for "igpu" (low power), the CPU last. Empty when the profile is CPU-only or
    this onnxruntime has no DirectML."""
    if accel not in ("gpu", "igpu") or DML not in available:
        return []
    pref = "high_performance" if accel == "gpu" else "minimum_power"
    return [(DML, {"performance_preference": pref}), "CPUExecutionProvider"]


class HimaEngine:
    name = "hima-onnx"
    release_after_job = True  # about 0.5 GB of memory: freed before the next stage, reloaded in ~4 s

    def __init__(self, model_path: str, model_id: str, threads: int = 4, accel: str = "cpu",
                 precision: str | None = None):
        self.model_path, self.model_id = Path(model_path), model_id
        self.threads, self.accel = max(1, threads), accel
        self.precision = precision  # encoder precision; None = the first installed one in VARIANTS
        self.enc = self.dec = self.tok = None
        self.used = "CPU"  # where the encoder runs: CPU | GPU | iGPU (the decoder is always on the CPU)

    # -------------------------------------------------------------------------------------------- lifecycle
    def _session(self, name: str, providers: list):
        import onnxruntime as ort

        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        so.intra_op_num_threads = self.threads
        if any((p[0] if isinstance(p, tuple) else p) == DML for p in providers):
            so.enable_mem_pattern = False  # DirectML requires both, and runs most nodes on the CPU without them
            so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        return ort.InferenceSession(str(self.model_path / "onnx" / name), so, providers=providers)

    def _encoder_on_cpu(self) -> None:
        self.enc = self._session(VARIANTS[self.precision][0], ["CPUExecutionProvider"])
        self.used = "CPU"

    def load(self) -> None:
        if self.enc is not None:
            return
        import onnxruntime as ort
        from tokenizers import Tokenizer

        have = find_variants(self.model_path)
        if not have:
            raise RuntimeError(f"no complete Hima ONNX model in {self.model_path} "
                               f"(need {missing_files(self.model_path)})")
        self.precision = self.precision if self.precision in have else have[0]
        enc, dec = VARIANTS[self.precision]
        try:
            self.dec = self._session(dec, ["CPUExecutionProvider"])
            gpu = providers_for(self.accel, ort.get_available_providers())
            if gpu:
                try:
                    self.enc = self._session(enc, gpu)
                    self.used = "iGPU" if self.accel == "igpu" else "GPU"
                except Exception as e:  # noqa: BLE001 - the GPU could not start: the CPU does the job
                    log.warning("Hima encoder on DirectML failed (%s); using the CPU", e)
            if self.enc is None:
                self._encoder_on_cpu()
        except MemoryError as e:
            self.enc = self.dec = None
            raise OutOfMemory(str(e)) from e
        p = self.model_path
        self.embed = np.load(p / "embed.npy").astype(np.float32)  # rows of the kept pieces, already scaled
        self.keep = np.array(json.loads((p / "keep_ids.json").read_text(encoding="utf-8")))
        self.row = {int(t): i for i, t in enumerate(self.keep)}
        self.sot = np.load(p / "start_of_text.npy").astype(np.float32)
        self.filters = np.load(p / "mel_filters.npy")
        self.tok = Tokenizer.from_file(str(p / "tokenizer.json"))
        log.info("loaded %s (%s encoder on the %s, decoder on the CPU)", self.model_id, self.precision, self.used)

    def unload(self) -> None:
        self.enc = self.dec = self.tok = None

    @property
    def translate_ok(self) -> bool:
        return False

    # ----------------------------------------------------------------------------------------------- model
    def _listen(self, pcm: np.ndarray) -> np.ndarray:
        """Encoder output for one clip: (frames, 640) float32."""
        mel, n_valid = log_mel(pcm, self.filters)
        n = _encoder_frames(n_valid)
        sound = self.enc.run(["sound"], {"mel": mel[None], "n_frames": np.array(n, dtype=np.int64)})[0]
        return sound[:n]

    def _write(self, sound: np.ndarray, language: str | None, style: str,
               max_pieces: int = 512) -> tuple[str, float]:
        """Greedy decoding. Returns the cleaned text and the mean log-probability of the pieces written."""
        parts = [self.embed[[self.row[BOS]]], sound, self.sot[None]]
        if language is not None:
            ids = self.tok.encode(f"<{LANGUAGE_NAMES[language]} {style}>", add_special_tokens=False).ids
            parts.append(self.embed[[self.row[i] for i in ids]])
        x = np.concatenate(parts).astype(np.float32)
        pk = pv = np.zeros(LAYERS_KV, np.float32)
        pos, out, logps = 0, [], []
        limit = min(max_pieces, int(1.5 * sound.shape[0]) + 8)
        for _ in range(limit + 1):
            logits, pk, pv = self.dec.run(DECODER_OUT, {"x": x, "pos0": np.array(pos, dtype=np.int64),
                                                          "past_k": pk, "past_v": pv})
            pos += x.shape[0]
            z = np.asarray(logits, dtype=np.float32).reshape(-1)
            j = int(np.argmax(z))
            tok = int(self.keep[j])
            if tok == EOS:
                break
            out.append(tok)
            logps.append(float(z[j] - (z.max() + np.log(np.exp(z - z.max()).sum()))))
            if len(out) >= limit:
                break
            if _loop_length(out) > 0:
                out = _cut_loop(out)
                logps = logps[:len(out)]
                break
            x = self.embed[[j]]
        text = clean_text(self.tok.decode(out, skip_special_tokens=False))
        return text, (float(np.mean(logps)) if logps else 0.0)

    # ---------------------------------------------------------------------------------------------- results
    def _segment(self, text: str, logp: float, pcm: np.ndarray, start: float, end: float,
                 language: str | None) -> ASRSegment | None:
        tokens = [PRONOUN_I.sub("I", t) for t in text.split()]
        if not tokens:
            return None
        conf = float(np.exp(logp))
        words = place_words(tokens, pcm, start, end)
        for w in words:
            w.confidence = conf
        return ASRSegment(start=words[0].start, end=words[-1].end, text=" ".join(tokens),
                          language=language or text_language(text), words=words, avg_logprob=logp,
                          no_speech_prob=0.0, compression_ratio=1.0)

    def _decode(self, pcm: np.ndarray, start: float, language: str | None, style: str) -> ASRSegment | None:
        try:
            text, logp = self._write(self._listen(pcm), language, style)
        except Exception as e:  # noqa: BLE001 - a GPU that fails mid-run (driver, memory): redo this clip on the CPU
            if self.used == "CPU":
                raise
            log.warning("Hima encoder on the %s failed (%s); continuing on the CPU", self.used, e)
            self._encoder_on_cpu()
            text, logp = self._write(self._listen(pcm), language, style)
        return self._segment(text, logp, pcm, start, start + len(pcm) / SAMPLE_RATE, language)

    def transcribe(self, read: AudioReader, chunks: Sequence[Chunk], options: ASROptions,
                   progress: Callable[[float], None] | None = None,
                   cancelled: Callable[[], bool] | None = None) -> list[ASRSegment]:
        if options.language_mode == "translate":
            raise RuntimeError(f"{self.model_id} cannot translate; use a Whisper model from the Accuracy pack")
        self.load()
        language = options.language_mode if options.language_mode in LANGUAGE_NAMES else None
        style = "native" if options.script_mode == "devanagari" else "mixed"
        results: list[ASRSegment] = []
        for i, (s, e) in enumerate(chunks):
            if cancelled and cancelled():
                raise InterruptedError("cancelled")
            pcm = np.ascontiguousarray(read(s, e), dtype=np.float32)
            step = int(MAX_CHUNK_SEC * SAMPLE_RATE)  # chunks are <= 30 s; a longer one is cut rather than refused
            for a in range(0, len(pcm), step):
                part = pcm[a:a + step]
                if len(part) < MIN_SAMPLES or float(np.sqrt(np.mean(np.square(part)))) < SILENCE_RMS:
                    continue
                seg = self._decode(part, s + a / SAMPLE_RATE, language, style)
                if seg:
                    results.append(seg)
            if progress:
                progress((i + 1) / max(1, len(chunks)))
        return results
