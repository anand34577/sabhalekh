"""Compare ASR engines/models on Hindi, Hinglish or English audio: WER, CER and speed.

    python tools/benchmark_wer.py --manifest tests/data/hindi/manifest.jsonl \
        --model models/asr/nemotron-3.5-asr-0.6b --model models/asr/whisper-large-v3-int8 \
        [--device cuda --compute int8_float16] [--accel gpu|igpu|cpu] [--language auto|hi|en] [--beam 5] [--batch 4]

A --model holding a .gguf file (or a .gguf path, e.g. your own fine-tune) runs on transcribe.cpp on --accel;
a CTranslate2 directory runs Whisper on --device/--compute.

manifest.jsonl: one {"audio": "file.wav", "text": "reference transcript", "language": "hi"} per line; audio paths
are relative to the manifest. Any format the app imports works (decoded with the bundled FFmpeg libraries).
Normalization before scoring: Unicode NFC, lower-case, punctuation (incl. danda) removed, nukta dropped,
chandrabindu -> anusvara, whitespace collapsed. Runs fully offline.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from sabhalekh import netguard  # noqa: E402

netguard.install()

from sabhalekh.asr import ASROptions, TranscribeCppEngine, WhisperCT2Engine  # noqa: E402
from sabhalekh.audio.media import Wav16k, to_wav16k  # noqa: E402
from sabhalekh.hardware import _add_cuda_dll_dirs  # noqa: E402
from sabhalekh.pipeline.vad import make_chunks, speech_regions  # noqa: E402

_PUNCT = re.compile(r"[।॥.,!?;:\"'“”‘’()\[\]{}\-–—…/\\|]")


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFC", s).lower().replace("़", "").replace("ँ", "ं")
    s = _PUNCT.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def edit_distance(a: list, b: list) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
        prev = cur
    return prev[-1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--model", action="append", required=True,
                    help="CTranslate2 Whisper model directory, or a transcribe.cpp .gguf file / directory")
    ap.add_argument("--accel", default="gpu", choices=["gpu", "igpu", "cpu"], help="transcribe.cpp device")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute", default="int8_float16")
    ap.add_argument("--language", default="auto", choices=["auto", "en", "hi"])
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--threads", type=int, default=os.cpu_count() // 2 or 1)
    ap.add_argument("--show", action="store_true", help="print every hypothesis")
    args = ap.parse_args()
    if args.device == "cuda":
        _add_cuda_dll_dirs()

    base = os.path.dirname(os.path.abspath(args.manifest))
    items = [json.loads(l) for l in open(args.manifest, encoding="utf-8") if l.strip()]
    tmp = tempfile.mkdtemp(prefix="msbench_")
    wavs = []
    for i, it in enumerate(items):
        src = os.path.join(base, it["audio"])
        dst = os.path.join(tmp, f"{i}.wav")
        to_wav16k(src, dst)
        wavs.append(Wav16k(dst))
    audio_sec = sum(w.duration for w in wavs)

    print(f"{len(items)} files, {audio_sec:.0f} s of audio, language={args.language}, device={args.device}/"
          f"{args.compute}, beam={args.beam}, batch={args.batch}\n")
    rows = []
    for model_dir in args.model:
        name = os.path.basename(os.path.normpath(model_dir))
        if model_dir.endswith(".gguf") or any(f.endswith(".gguf") for f in os.listdir(model_dir)):
            eng = TranscribeCppEngine(model_dir, name, accel=args.accel, threads=args.threads)
        else:
            eng = WhisperCT2Engine(model_dir, name, device=args.device, compute_type=args.compute,
                                   threads=args.threads)
        t0 = time.perf_counter()
        eng.load()
        load_s = time.perf_counter() - t0
        opts = ASROptions(language_mode=args.language, beam_size=args.beam, batch_size=args.batch)
        we = wn = ce = cn = 0
        t0 = time.perf_counter()
        for it, w in zip(items, wavs):
            chunks = make_chunks(speech_regions(w.read, w.duration))
            segs = eng.transcribe(w.read, chunks, opts)
            hyp = normalize(" ".join(s.text for s in segs))
            ref = normalize(it["text"])
            we += edit_distance(ref.split(), hyp.split())
            wn += len(ref.split())
            ce += edit_distance(list(ref.replace(" ", "")), list(hyp.replace(" ", "")))
            cn += len(ref.replace(" ", ""))
            if args.show:
                print(f"  REF {ref}\n  HYP {hyp}\n")
        dt = time.perf_counter() - t0
        eng.unload()
        rows.append((name, 100 * we / max(1, wn), 100 * ce / max(1, cn), audio_sec / dt, load_s))
    print(f"{'model':40s} {'WER%':>6s} {'CER%':>6s} {'xRT':>6s} {'load s':>7s}")
    for name, wer, cer, xrt, load_s in rows:
        print(f"{name:40s} {wer:6.1f} {cer:6.1f} {xrt:6.1f} {load_s:7.1f}")


if __name__ == "__main__":
    main()
