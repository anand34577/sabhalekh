"""Milestone 0: Nemotron (ONNX int8, CPU) on a long file: wall time, real-time factor, peak process memory."""
import os
import sys
import threading
import time

import psutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
from sabhalekh.audio.media import Wav16k  # noqa: E402
from sabhalekh.diarization.nemotron_onnx import NemotronOnnxDiarizer  # noqa: E402
from sabhalekh.pipeline.align import activity_from_probs  # noqa: E402

proc = psutil.Process()
peak = [0]
stop = threading.Event()


def poll():
    while not stop.is_set():
        peak[0] = max(peak[0], proc.memory_info().rss)
        time.sleep(0.1)


threading.Thread(target=poll, daemon=True).start()
w = Wav16k(sys.argv[1])
base = proc.memory_info().rss
d = NemotronOnnxDiarizer(sys.argv[2], threads=psutil.cpu_count(logical=False))
t = time.perf_counter()
p = d.probabilities(w.mm)
dt = time.perf_counter() - t
stop.set()
act = activity_from_probs(p)
print(f"{w.duration / 60:.0f} min audio: {dt:.0f} s -> {w.duration / dt:.0f}x real time | peak RSS "
      f"{peak[0] / 2 ** 20:.0f} MB (before model {base / 2 ** 20:.0f} MB) | speakers {act.speakers_present()}")
