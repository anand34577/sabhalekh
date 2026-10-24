"""NVIDIA Nemotron-3-Diarization without PyTorch.

The offline forward of the transformers implementation is reproduced here in numpy:

* log-mel features (pre-emphasis, Hann STFT, slaney mel, log) computed lazily per chunk, so a 3 h recording never
  holds its full spectrogram in memory;
* feature stacking (8 mel frames -> one 1024-d vector -> linear projection to 512);
* the Arrival-Order Speaker Cache + FIFO queue that every chunk attends to;

and only the heavy step (31-layer transformer encoder + projection + upsampler + classifier, ~99M params) runs in
onnxruntime as one fixed-shape graph of 684 encoder frames (speaker cache 264 + FIFO 40 + chunk 340 + look-ahead 40),
padded and masked. Output: per-speaker activity probabilities every 10 ms for up to 8 speakers, in arrival order.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Callable

import numpy as np

SAMPLE_RATE = 16000
LOG_ZERO_GUARD = 2.0 ** -24
ENCODER_FILES = ("encoder_int8.onnx", "encoder_fp16.onnx", "encoder_fp32.onnx")


@dataclass
class _Front:
    mel: np.ndarray  # (128, 257)
    proj_t: np.ndarray  # (1024, 512)
    silence: np.ndarray  # (512,)
    meta: dict


def load_frontend(path: str) -> _Front:
    with np.load(path) as z:
        return _Front(z["mel_filters"], np.ascontiguousarray(z["projection"].T), z["silence_embeds"],
                      json.loads(str(z["meta"])))


class _Features:
    """Lazy, block-wise log-mel features equal to torch.stft(center=True, pad_mode='constant'), plus stacking."""

    def __init__(self, audio: np.ndarray, front: _Front):
        m = front.meta
        self.audio = audio  # int16 or float32, 16 kHz mono (may be a memmap)
        self.scale = 1.0 / 32768.0 if audio.dtype == np.int16 else 1.0
        self.n = len(audio)
        self.hop, self.n_fft, self.pre = m["hop_length"], m["n_fft"], m["preemphasis"]
        self.sub = m["subsampling_factor"]
        win = m["win_length"]
        hann = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(win) / (win - 1))  # periodic=False
        self.window = np.zeros(self.n_fft, np.float32)
        left = (self.n_fft - win) // 2
        self.window[left:left + win] = hann
        self.front = front
        self.num_mel = 1 + self.n // self.hop  # frames of a centered STFT
        self.valid_mel = self.n // self.hop  # the processor's attention mask: frames < this are valid
        self.num_embeds = -(-self.num_mel // self.sub)

    def _samples(self, a: int, b: int) -> np.ndarray:
        """Pre-emphasized samples [a, b) of the zero-extended signal."""
        out = np.zeros(b - a, np.float32)
        lo, hi = max(a, 0), min(b, self.n)
        if hi <= lo:
            return out
        seg = np.asarray(self.audio[lo:hi], dtype=np.float32) * self.scale
        emph = np.empty_like(seg)
        emph[1:] = seg[1:] - self.pre * seg[:-1]
        emph[0] = seg[0] if lo == 0 else seg[0] - self.pre * float(self.audio[lo - 1]) * self.scale
        out[lo - a:hi - a] = emph
        return out

    def mel(self, f0: int, f1: int) -> np.ndarray:
        """Log-mel frames [f0, f1) as (f1 - f0, 128); frames past the audio are zero (masked) like the original."""
        f1c = min(f1, self.num_mel)
        out = np.zeros((f1 - f0, self.front.mel.shape[0]), np.float32)
        if f1c <= f0:
            return out
        half = self.n_fft // 2
        sig = self._samples(f0 * self.hop - half, (f1c - 1) * self.hop + half)
        frames = np.lib.stride_tricks.sliding_window_view(sig, self.n_fft)[:: self.hop][: f1c - f0]
        spec = np.fft.rfft(frames * self.window, axis=1)
        power = (spec.real ** 2 + spec.imag ** 2).astype(np.float32)
        logmel = np.log(power @ self.front.mel.T + LOG_ZERO_GUARD)
        valid = np.arange(f0, f1c) < self.valid_mel
        out[: f1c - f0] = logmel * valid[:, None]
        return out

    def embeds(self, e0: int, e1: int) -> tuple[np.ndarray, np.ndarray]:
        """Encoder inputs [e0, e1) as (n, 512) and their validity (n,) = attention_mask[::8]."""
        mel = self.mel(e0 * self.sub, e1 * self.sub)
        stacked = mel.reshape(e1 - e0, -1)
        valid = (np.arange(e0, e1) * self.sub < self.valid_mel).astype(np.float32)
        return stacked @ self.front.proj_t, valid


class _SpeakerCache:
    """numpy port of transformers' Nemotron3DiarizationSpeakerCache (batch size 1)."""

    def __init__(self, cfg: dict, fifo_length: int, update_period: int, hidden: int):
        self.fifo_length = fifo_length
        self.update_period = update_period
        self.cache_length = cfg["speaker_cache_length"]
        self.num_silence = cfg["speaker_cache_silence_frames_per_speaker"]
        self.score_threshold = cfg["prediction_score_threshold"]
        self.latest_boost = cfg["latest_frames_score_boost"]
        self.num_speakers = cfg["num_speakers"]
        self.sub = cfg["subsampling_factor"]
        budget = self.cache_length // self.num_speakers - self.num_silence
        self.min_positive = math.floor(budget * cfg["min_positive_scores_rate"])
        self.n_strong = math.floor(budget * cfg["strong_boost_rate"])
        self.n_weak = math.floor(budget * cfg["weak_boost_rate"])
        self.embeds = np.zeros((0, hidden), np.float32)
        self.probs = np.zeros((0, self.num_speakers), np.float32)
        self.fifo = np.zeros((0, hidden), np.float32)
        self.compressed = False

    def get_embeds(self) -> np.ndarray:
        return np.concatenate([self.embeds, self.fifo], axis=0)

    def _pool(self, logits: np.ndarray, mask: np.ndarray) -> np.ndarray:
        p = 1.0 / (1.0 + np.exp(-logits))
        p = p.reshape(-1, self.sub, p.shape[1]).mean(axis=1)
        return (p * mask[:, None]).astype(np.float32)

    def update(self, step_embeds, step_logits, silence, num_chunk_frames, mask):
        ncache, nfifo = len(self.embeds), len(self.fifo)
        probs = self._pool(step_logits, mask)
        start = ncache + nfifo
        fifo = np.concatenate([self.fifo, step_embeds[start:start + num_chunk_frames]], axis=0)
        popped = 0
        if len(fifo) > self.fifo_length:
            popped = min(max(self.update_period, len(fifo) - self.fifo_length), len(fifo))
        if popped:
            fifo_probs = probs[ncache:ncache + len(fifo)]
            stored = self.probs if self.compressed else probs[:ncache]
            cache_e = np.concatenate([self.embeds, fifo[:popped]], axis=0)
            cache_p = np.concatenate([stored, fifo_probs[:popped]], axis=0)
            fifo = fifo[popped:]
            if len(cache_e) > self.cache_length:
                cache_e, cache_p = self._compress(cache_e, cache_p, silence)
                self.compressed = True
            self.embeds, self.probs = cache_e, cache_p
        self.fifo = fifo

    def _scores(self, probs):
        lp = np.log(np.maximum(probs, self.score_threshold))
        lc = np.log(np.maximum(1.0 - probs, self.score_threshold))
        s = lp - lc + lc.sum(axis=1, keepdims=True) - math.log(0.5)
        speech = probs > 0.5
        s = np.where(speech, s, -np.inf)
        pos = s > 0
        enough = pos.sum(axis=0, keepdims=True) >= self.min_positive
        return np.where(~pos & speech & enough, -np.inf, s)

    @staticmethod
    def _boost(s, k, boost):
        k = min(k, s.shape[0])
        idx = np.argpartition(-s, k - 1, axis=0)[:k]  # top-k frames per speaker
        cols = np.broadcast_to(np.arange(s.shape[1]), idx.shape)
        np.add.at(s, (idx, cols), boost)
        return s

    def _compress(self, embeds, probs, silence):
        n, S = probs.shape
        s = self._scores(probs).astype(np.float32)
        s[self.cache_length:] += self.latest_boost
        s = self._boost(s, self.n_strong, np.float32(-2.0 * math.log(0.5)))
        s = self._boost(s, self.n_weak, np.float32(-math.log(0.5)))
        s = np.concatenate([s, np.full((self.num_silence, S), np.inf, np.float32)], axis=0)
        embeds = np.concatenate([embeds, silence[None, :].astype(np.float32)], axis=0)
        probs = np.concatenate([probs, np.zeros((1, S), np.float32)], axis=0)
        scored = n + self.num_silence
        sentinel = scored * S
        flat = s.T.reshape(-1)
        top = np.argpartition(-flat, self.cache_length - 1)[: self.cache_length]
        top = np.where(flat[top] == -np.inf, sentinel, top)
        top.sort()
        frames = np.where(top == sentinel, n, np.minimum(top % scored, n))
        return embeds[frames], probs[frames]


class NemotronOnnxDiarizer:
    """Speaker activity probabilities from Nemotron-3-Diarization via onnxruntime."""

    def __init__(self, model_dir: str, threads: int = 0, providers: list[str] | None = None,
                 encoder_file: str | None = None):
        import onnxruntime as ort

        self.front = load_frontend(os.path.join(model_dir, "frontend.npz"))
        enc = encoder_file or next((f for f in ENCODER_FILES if os.path.exists(os.path.join(model_dir, f))), None)
        if enc is None:
            raise FileNotFoundError(f"no Nemotron encoder ({', '.join(ENCODER_FILES)}) in {model_dir}")
        opts = ort.SessionOptions()
        if threads:
            opts.intra_op_num_threads = threads
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(os.path.join(model_dir, enc), opts,
                                            providers=providers or ["CPUExecutionProvider"])
        self.encoder_file = enc
        m = self.front.meta
        self.length = (m["streaming"]["speaker_cache_length"] + m["fifo_length"] + m["chunk_length"]
                       + m["chunk_right_context"])
        self.frame_sec = m["hop_length"] / m["sampling_rate"]
        self.max_speakers = m["streaming"]["num_speakers"]

    def _run(self, x: np.ndarray, valid: np.ndarray) -> np.ndarray:
        n = len(x)
        xx = np.zeros((1, self.length, x.shape[1]), np.float32)
        xx[0, :n] = x
        vv = np.zeros((1, self.length), np.float32)
        vv[0, :n] = valid
        out = self.session.run(None, {"inputs_embeds": xx, "valid": vv})[0][0]
        return out[: n * (out.shape[0] // self.length)].astype(np.float32)

    def probabilities(self, audio: np.ndarray,
                      progress: Callable[[float], None] | None = None,
                      cancelled: Callable[[], bool] | None = None) -> np.ndarray:
        """(num_frames, 8) sigmoid speaker probabilities, one frame per 10 ms. `audio`: 16 kHz mono int16/float32."""
        m = self.front.meta
        feats = _Features(audio, self.front)
        cache = _SpeakerCache(m["streaming"], m["fifo_length"], m["speaker_cache_update_period"],
                              self.front.proj_t.shape[1])
        chunk, right, sub = m["chunk_length"], m["chunk_right_context"], m["subsampling_factor"]
        n = feats.num_embeds
        out = np.zeros((n * sub, self.max_speakers), np.float32)
        for start in range(0, n, chunk):
            if cancelled and cancelled():
                raise InterruptedError("cancelled")
            end = min(start + chunk, n)
            emb, valid = feats.embeds(start, min(end + right, n))
            cached = cache.get_embeds()
            step = np.concatenate([cached, emb], axis=0)
            mask = np.concatenate([np.ones(len(cached), np.float32), valid])
            logits = self._run(step, mask)
            cache.update(step, logits, self.front.silence, end - start, mask)
            out[start * sub:end * sub] = logits[len(cached) * sub:(len(cached) + end - start) * sub]
            if progress:
                progress(end / n)
        out = out[: feats.num_mel]
        return (1.0 / (1.0 + np.exp(-out))).astype(np.float32)
