"""Pluggable ASR interface. An engine turns speech chunks of a 16 kHz track into timed segments with words.

To add an engine (e.g. an Indic-tuned Whisper or a NeMo/ONNX checkpoint), implement `ASREngine` and register a
factory in `sabhalekh.asr.ENGINES`; tools/benchmark_wer.py can then compare it with the bundled models.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence

import numpy as np


class OutOfMemory(RuntimeError):
    """The engine ran out of (GPU) memory; the caller should retry with a lighter profile."""


@dataclass
class ASROptions:
    language_mode: str = "auto"  # auto | en | hi | translate
    script_mode: str = "as_spoken"  # as_spoken | devanagari | roman
    initial_prompt: str = ""  # custom vocabulary / names / jargon
    beam_size: int = 5
    batch_size: int = 4


@dataclass
class Word:
    start: float
    end: float
    text: str
    confidence: float


@dataclass
class ASRSegment:
    start: float
    end: float
    text: str
    language: str
    words: list[Word] = field(default_factory=list)
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0
    compression_ratio: float = 1.0

    @property
    def confidence(self) -> float:
        if self.words:
            return float(np.mean([w.confidence for w in self.words]))
        return float(np.exp(self.avg_logprob))


Chunk = tuple[float, float]  # (start_sec, end_sec), each <= 30 s
AudioReader = Callable[[float, float], np.ndarray]  # (start_sec, end_sec) -> float32 16 kHz mono


class ASREngine(Protocol):
    name: str
    model_id: str

    def load(self) -> None: ...

    def unload(self) -> None: ...

    def transcribe(self, read: AudioReader, chunks: Sequence[Chunk], options: ASROptions,
                   progress: Callable[[float], None] | None = None,
                   cancelled: Callable[[], bool] | None = None) -> list[ASRSegment]: ...
