"""Milestone 0: Whisper speed and peak VRAM on a long mixed file, per model / compute type / batch size.

    python tools/spike/asr_speed.py LONG_WAV MODEL_DIR COMPUTE BATCH [DEVICE]
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
from sabhalekh.asr import ASROptions, WhisperCT2Engine  # noqa: E402
from sabhalekh.audio.media import Wav16k  # noqa: E402
from sabhalekh.hardware import _add_cuda_dll_dirs  # noqa: E402
from sabhalekh.pipeline.vad import make_chunks, speech_regions  # noqa: E402

wav_path, model_dir, compute, batch = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
device = sys.argv[5] if len(sys.argv) > 5 else "cuda"
_add_cuda_dll_dirs()
peak = [0]
stop = threading.Event()


def poll():
    import pynvml

    pynvml.nvmlInit()
    h = pynvml.nvmlDeviceGetHandleByIndex(0)
    while not stop.is_set():
        peak[0] = max(peak[0], pynvml.nvmlDeviceGetMemoryInfo(h).used // 2 ** 20)
        time.sleep(0.05)


threading.Thread(target=poll, daemon=True).start()
w = Wav16k(wav_path)
t = time.perf_counter()
chunks = make_chunks(speech_regions(w.read, w.duration))
vad_s = time.perf_counter() - t
eng = WhisperCT2Engine(model_dir, os.path.basename(model_dir), device=device, compute_type=compute, threads=6)
eng.load()
t = time.perf_counter()
segs = eng.transcribe(w.read, chunks, ASROptions(language_mode="auto", beam_size=5, batch_size=batch))
dt = time.perf_counter() - t
stop.set()
langs = {}
for s in segs:
    langs[s.language] = langs.get(s.language, 0) + 1
print(f"{os.path.basename(model_dir):30s} {device}/{compute:13s} batch {batch}: {w.duration / 60:.1f} min audio, "
      f"VAD {vad_s:.1f}s, ASR {dt:.1f}s -> {w.duration / dt:.1f}x RT, peak VRAM {peak[0]} MB, {len(chunks)} chunks, "
      f"segments per language {langs}")
