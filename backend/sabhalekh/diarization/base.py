"""Pluggable diarization interface: an engine returns per-speaker activity probabilities over time."""
from __future__ import annotations

import logging
from typing import Callable, Protocol

import numpy as np

log = logging.getLogger("sabhalekh.diarization")


class DiarizationEngine(Protocol):
    name: str  # stored with the session
    label: str  # shown in the UI
    max_speakers: int
    frame_sec: float

    def probabilities(self, audio: np.ndarray, progress: Callable[[float], None] | None = None,
                      cancelled: Callable[[], bool] | None = None) -> np.ndarray:
        """(frames, speakers) activity probabilities in [0, 1]; `audio` is 16 kHz mono int16 or float32."""
        ...


class NemotronEngine:
    name = "nemotron-3-diarization (onnx int8, cpu)"
    label = "NVIDIA Nemotron-3-Diarization · CPU (ONNX)"

    def __init__(self, model_dir: str, threads: int):
        from .nemotron_onnx import NemotronOnnxDiarizer

        self.impl = NemotronOnnxDiarizer(model_dir, threads=threads)
        self.max_speakers = self.impl.max_speakers
        self.frame_sec = self.impl.frame_sec
        if self.impl.encoder_file != "encoder_int8.onnx":
            self.name = f"nemotron-3-diarization (onnx {self.impl.encoder_file[8:-5]}, cpu)"

    def probabilities(self, audio, progress=None, cancelled=None):
        return self.impl.probabilities(audio, progress=progress, cancelled=cancelled)


class SingleSpeakerFallback:
    """Used only when the diarization model is missing or broken. Never silent: the session gets a warning and the
    UI shows that every voice was attributed to one speaker, and why."""

    name = "single-speaker fallback"
    label = "Diarization unavailable · one speaker"
    max_speakers = 1
    frame_sec = 0.01

    def __init__(self, reason: str):
        self.reason = reason

    def probabilities(self, audio, progress=None, cancelled=None):
        n = len(audio) // 160 + 1
        if progress:
            progress(1.0)
        return np.ones((n, 1), np.float32)
