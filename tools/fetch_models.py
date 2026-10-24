"""Build-time tool (needs internet ONCE, on the build machine): produce every model the app ships, from source.

    py -3.12 -m venv .buildenv
    .buildenv\\Scripts\\pip install -r tools\\requirements-build-models.txt
    .buildenv\\Scripts\\python tools\\fetch_models.py [--with-large-v3] [--with-turbo] [--with-small]

Creates under models/:
    asr/nemotron-3.5-asr-0.6b/         default model, GGUF Q8_0 (bundled in the installer)   ~0.75 GB
    asr/whisper-large-v3-int8/         --with-large-v3 (Accuracy model pack, translation)    ~1.5 GB
    asr/whisper-large-v3-turbo-int8/   --with-turbo (optional fallback)                      ~0.8 GB
    asr/whisper-small-int8/            --with-small (optional)                                ~0.25 GB
    diarization/nemotron3/encoder_int8.onnx + frontend.npz                                   ~0.12 GB
Nemotron 3.5 ASR comes pre-converted from handy-computer/nemotron-3.5-asr-streaming-0.6b-gguf (transcribe.cpp).
The app itself never downloads anything.
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def run(*args):
    print(">", " ".join(args), flush=True)
    subprocess.run(args, check=True, cwd=ROOT)


def whisper(name: str):
    out = os.path.join(ROOT, "models", "asr", f"whisper-{name}-int8")
    if os.path.exists(os.path.join(out, "model.bin")):
        print(f"{out} exists, skipping")
        return
    conv = os.path.join(os.path.dirname(PY), "ct2-transformers-converter")
    run(conv, "--model", f"openai/whisper-{name}", "--output_dir", out, "--quantization", "int8_float16",
        "--copy_files", "tokenizer.json", "preprocessor_config.json", "--force")


NEMOTRON_REPO = "handy-computer/nemotron-3.5-asr-streaming-0.6b-gguf"
NEMOTRON_FILE = "nemotron-3.5-asr-streaming-0.6b-Q8_0.gguf"  # Q8_0: LibriSpeech WER 3.05 % vs 3.04 % for F32


def nemotron_asr():
    out = os.path.join(ROOT, "models", "asr", "nemotron-3.5-asr-0.6b")
    if os.path.exists(os.path.join(out, NEMOTRON_FILE)):
        print(f"{out} exists, skipping")
        return
    from huggingface_hub import hf_hub_download

    os.makedirs(out, exist_ok=True)
    hf_hub_download(NEMOTRON_REPO, NEMOTRON_FILE, local_dir=out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-large-v3", action="store_true")
    ap.add_argument("--with-turbo", action="store_true")
    ap.add_argument("--with-small", action="store_true")
    a = ap.parse_args()
    nemotron_asr()
    if a.with_turbo:
        whisper("large-v3-turbo")
    if a.with_large_v3:
        whisper("large-v3")
    if a.with_small:
        whisper("small")
    nem = os.path.join(ROOT, "models", "diarization", "nemotron3")
    os.makedirs(nem, exist_ok=True)
    if not os.path.exists(os.path.join(nem, "encoder_int8.onnx")):
        fp32 = os.path.join(ROOT, "build", "nemotron3_encoder_fp32.onnx")
        run(PY, "tools/export_nemotron_onnx.py", "--out", fp32)
        run(PY, "tools/quantize_nemotron.py", fp32, os.path.join(nem, "encoder_int8.onnx"))
    if not os.path.exists(os.path.join(nem, "frontend.npz")):
        run(PY, "tools/export_nemotron_frontend.py", "--out", os.path.join(nem, "frontend.npz"))
    print("models ready")


if __name__ == "__main__":
    main()
