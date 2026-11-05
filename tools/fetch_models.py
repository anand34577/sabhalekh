"""Build-time tool (needs internet ONCE, on the build machine): produce every model the app ships, from source.

    py -3.12 -m venv .buildenv
    .buildenv\\Scripts\\pip install -r tools\\requirements-build-models.txt
    .buildenv\\Scripts\\python tools\\fetch_models.py [--with-large-v3] [--with-turbo] [--with-small]

Creates under models/:
    asr/nemotron-3.5-asr-0.6b/         default model, GGUF Q8_0 (bundled in the installer)   ~0.75 GB
    asr/whisper-large-v3-int8/         --with-large-v3 (Accuracy model pack, translation)    ~1.5 GB
    asr/whisper-large-v3-turbo-int8/   --with-turbo (optional fallback)                      ~0.8 GB
    asr/whisper-small-int8/            --with-small (optional)                                ~0.25 GB
    asr/shruti/shruti.cact             --with-shruti (Hindi/English/Hinglish; needs cactus-needle)  ~0.03 GB
    asr/hima-asr/                      --with-hima [q4|int8] (11 Indian languages + English, ONNX)  ~0.48 GB
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


SHRUTI_REPO = "udgamlabs/Shruti"


def shruti():
    """Shruti (Hindi/English/Hinglish, 29.5 MB) and the needle engine library that runs it (bin/needle)."""
    out = os.path.join(ROOT, "models", "asr", "shruti")
    if not os.path.exists(os.path.join(out, "shruti.cact")):
        from huggingface_hub import hf_hub_download

        os.makedirs(out, exist_ok=True)
        for name in ("shruti.cact", "NOTICE"):  # the Apache-2.0 NOTICE must ship with the model
            try:
                hf_hub_download(SHRUTI_REPO, name, local_dir=out)
            except Exception as e:  # noqa: BLE001
                if name == "shruti.cact":
                    raise
                print(f"warning: {name} not downloaded ({e}); copy it from the model page before releasing")


HIMA_REPO = "Prahaladha/hima-asr-ONNX"
HIMA_SHARED = ["embed.npy", "keep_ids.json", "start_of_text.npy", "mel_filters.npy", "tokenizer.json",
               "tokenizer_config.json", "LICENSE", "NOTICE"]
HIMA_DECODER = ["onnx/decoder_model_int8.onnx", "onnx/decoder_model_int8.onnx_data"]
HIMA_ENCODERS = {"q4": ["onnx/encoder_model_q4.onnx", "onnx/encoder_model_q4.onnx_data"],
                 "int8": ["onnx/encoder_model_int8.onnx", "onnx/encoder_model_int8.onnx_data"]}


def hima(precision: str = "q4"):
    """Hima-ASR (11 Indian languages + English), the authors' ONNX export: the 4-bit encoder and the 8-bit decoder,
    ~0.48 GB in all. On the Hindi test clips the q4 encoder is as accurate as the int8 one (both 9.2 % WER) and
    faster; "int8" fetches the 8-bit encoder instead (+0.13 GB). The authors' fp32 export (1.8 GB) is not used.
    The LICENSE and NOTICE files carry the Apache-2.0 and Gemma Terms of Use notices and must ship with the model."""
    from huggingface_hub import hf_hub_download

    out = os.path.join(ROOT, "models", "asr", "hima-asr")
    os.makedirs(out, exist_ok=True)
    wanted = HIMA_SHARED + HIMA_DECODER + HIMA_ENCODERS[precision]
    for name in wanted:
        if not os.path.exists(os.path.join(out, name)):
            hf_hub_download(HIMA_REPO, name, local_dir=out)


def needle_engine():
    """The needle engine library for this OS and CPU (bin/needle), the one Shruti runs on."""
    from needle.agent import fetch

    lib_dir = os.path.join(ROOT, "bin", "needle")
    name = fetch.lib_name(generation=3)
    if not os.path.exists(os.path.join(lib_dir, name)):
        os.makedirs(lib_dir, exist_ok=True)
        path = fetch.fetch_library(dest_dir=lib_dir, generation=3)
        print("engine library:", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-shruti", action="store_true", help="also fetch the engine library for this OS")
    ap.add_argument("--no-engine", action="store_true", help="with --with-shruti: the model only, not the engine library")
    ap.add_argument("--with-hima", nargs="?", const="q4", choices=sorted(HIMA_ENCODERS),
                    help="also fetch Hima-ASR (ONNX); optional encoder precision, default q4")
    ap.add_argument("--engine-only", action="store_true", help="only the needle engine library for this OS")
    ap.add_argument("--with-large-v3", action="store_true")
    ap.add_argument("--with-turbo", action="store_true")
    ap.add_argument("--with-small", action="store_true")
    a = ap.parse_args()
    if a.engine_only:
        needle_engine()
        return
    nemotron_asr()
    if a.with_shruti:
        shruti()
        if not a.no_engine:
            needle_engine()
    if a.with_hima:
        hima(a.with_hima)
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
