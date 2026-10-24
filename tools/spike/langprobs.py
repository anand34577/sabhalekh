"""Milestone 0: per-file English/Hindi language probabilities from a Whisper model (routing diagnostics)."""
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
from faster_whisper import WhisperModel  # noqa: E402
from faster_whisper.audio import pad_or_trim  # noqa: E402

from sabhalekh.audio.media import Wav16k  # noqa: E402
from sabhalekh.hardware import _add_cuda_dll_dirs  # noqa: E402

_add_cuda_dll_dirs()
m = WhisperModel(sys.argv[1], device="cuda", compute_type="int8_float16")
for f in sys.argv[2:]:
    for path in sorted(glob.glob(f)):
        w = Wav16k(path)
        feats = pad_or_trim(m.feature_extractor(w.read(0, min(w.duration, 30)))[..., :-1])[None]
        p = {t[2:-2]: v for t, v in m.model.detect_language(m.encode(feats))[0]}
        top = sorted(p.items(), key=lambda kv: -kv[1])[:3]
        print(f"{os.path.basename(path)}: en={p.get('en', 0):.2f} hi={p.get('hi', 0):.2f} ur={p.get('ur', 0):.2f} "
              f"top={[(k, round(v, 2)) for k, v in top]}")
