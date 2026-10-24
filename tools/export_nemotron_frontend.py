"""Build-time tool: extract the small non-encoder parts of Nemotron-3-Diarization into a .npz.

Run with an environment that has torch + transformers + librosa (only needed once, at build time):

    python tools/export_nemotron_frontend.py --out models/diarization/nemotron3/frontend.npz

The app itself never imports torch: it reads this .npz (mel filters, feature-stacking projection, silence embedding,
speaker-cache config) and runs the encoder from the exported ONNX graph.
"""
import argparse
import json

import librosa
import numpy as np
from huggingface_hub import hf_hub_download
from safetensors.numpy import load_file

MODEL_ID = "nvidia/Nemotron-3-Diarization"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    cfg = json.load(open(hf_hub_download(MODEL_ID, "config.json"), encoding="utf-8"))
    pcfg = json.load(open(hf_hub_download(MODEL_ID, "processor_config.json"), encoding="utf-8"))["feature_extractor"]
    weights = load_file(hf_hub_download(MODEL_ID, "model.safetensors"))
    proj = weights["model.audio_tower.embedder.projection.weight"].astype(np.float32)  # (512, 1024)
    silence = weights["silence_embeds"].astype(np.float32)  # (512,)
    mel = librosa.filters.mel(sr=pcfg["sampling_rate"], n_fft=pcfg["n_fft"], n_mels=pcfg["feature_size"],
                              fmin=0.0, fmax=pcfg["sampling_rate"] / 2, norm="slaney").astype(np.float32)
    meta = {
        "sampling_rate": pcfg["sampling_rate"], "n_fft": pcfg["n_fft"], "hop_length": pcfg["hop_length"],
        "win_length": pcfg["win_length"], "preemphasis": pcfg["preemphasis"],
        "subsampling_factor": cfg["audio_config"]["subsampling_factor"],
        "chunk_length": cfg["chunk_length"], "chunk_right_context": cfg["chunk_right_context"],
        "fifo_length": cfg["fifo_length"], "speaker_cache_update_period": cfg["speaker_cache_update_period"],
        "streaming": cfg["streaming_config"],
    }
    np.savez(args.out, mel_filters=mel, projection=proj, silence_embeds=silence, meta=json.dumps(meta))
    print("wrote", args.out, {k: v.shape for k, v in {"mel": mel, "proj": proj, "silence": silence}.items()})


if __name__ == "__main__":
    main()
