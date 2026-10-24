"""ASR engines. ENGINES maps an engine name (models/catalog.json "engine") to a factory taking the hardware profile."""
from __future__ import annotations

from .base import ASREngine, ASROptions, ASRSegment, OutOfMemory, Word  # noqa: F401
from .transcribe_cpp import TranscribeCppEngine
from .whisper_ct2 import WhisperCT2Engine


def _whisper(model_path: str, model_id: str, profile) -> ASREngine:
    return WhisperCT2Engine(model_path, model_id, device=profile.device, compute_type=profile.compute_type,
                            threads=profile.threads)


def _transcribe_cpp(model_path: str, model_id: str, profile) -> ASREngine:
    return TranscribeCppEngine(model_path, model_id, accel=profile.accel, threads=profile.threads)


ENGINES = {"faster-whisper": _whisper, "transcribe-cpp": _transcribe_cpp}
