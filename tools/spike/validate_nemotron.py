"""Milestone 0: compare the torch-free Nemotron engine with the GPU reference probabilities and time it.

    python tools/spike/validate_nemotron.py MODEL_DIR SAMPLES_DIR [ENCODER_FILE]
"""
import os
import sys
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
from sabhalekh.diarization.nemotron_onnx import NemotronOnnxDiarizer  # noqa: E402

model_dir, samples = sys.argv[1], sys.argv[2]
enc = sys.argv[3] if len(sys.argv) > 3 else None
d = NemotronOnnxDiarizer(model_dir, threads=6, encoder_file=enc)
print("encoder:", d.encoder_file, f"{os.path.getsize(os.path.join(model_dir, d.encoder_file)) / 1e6:.0f} MB")
for name in ("meeting", "long"):
    audio, sr = sf.read(os.path.join(samples, name + ".wav"), dtype="int16")
    assert sr == 16000 and audio.ndim == 1
    ref = np.load(os.path.join(samples, name + "_ref.npy"))
    d.probabilities(audio[:16000])  # warm-up
    t = time.perf_counter()
    p = d.probabilities(audio)
    dt = time.perf_counter() - t
    agree = ((p > 0.5) == (ref > 0.5)).mean()
    spk = lambda a: int(((a > 0.5).sum(0) > 50).sum())  # noqa: E731
    print(f"{name}: {len(audio) / sr:.1f}s audio, {dt:.2f}s -> {len(audio) / sr / dt:.0f}x RT | shape {p.shape} "
          f"vs {ref.shape} | max|dp| {np.abs(p - ref).max():.2e} | frame agreement {agree * 100:.3f}% "
          f"| speakers {spk(p)} vs ref {spk(ref)}")
