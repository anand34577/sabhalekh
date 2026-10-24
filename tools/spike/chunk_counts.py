"""Milestone 0: how many Whisper chunks (= 30 s encoder passes) each chunking strategy produces for a recording.

    python tools/spike/chunk_counts.py AUDIO_16K_WAV
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
from sabhalekh.audio.media import Wav16k  # noqa: E402
from sabhalekh.diarization.nemotron_onnx import NemotronOnnxDiarizer  # noqa: E402
from sabhalekh.pipeline import align  # noqa: E402
from sabhalekh.pipeline.vad import make_chunks, speaker_changes, speech_regions  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
w = Wav16k(sys.argv[1])
regions = speech_regions(w.read, w.duration)
d = NemotronOnnxDiarizer(os.path.join(ROOT, "models", "diarization", "nemotron3"), threads=6)
act = align.activity_from_probs(d.probabilities(w.mm))
cuts = speaker_changes(act.active, act.frame_sec)
print(f"{w.duration / 60:.0f} min, {len(regions)} VAD regions, {len(cuts)} speaker changes")
for label, kw in [("merge everything (no speaker cuts)", {}),
                  ("cut at every speaker change", {"split_at": cuts}),
                  ]:
    print(f"  {label:52s} {len(make_chunks(regions, **kw))} chunks")
