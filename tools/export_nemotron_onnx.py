"""Build-time tool: export the Nemotron-3-Diarization encoder step to a fixed-shape ONNX graph (fp32).

    python tools/export_nemotron_onnx.py --out build-models/nemotron3_encoder_fp32.onnx
    python tools/quantize_nemotron.py build-models/nemotron3_encoder_fp32.onnx models/diarization/nemotron3/encoder_int8.onnx
    python tools/export_nemotron_frontend.py --out models/diarization/nemotron3/frontend.npz

Needs torch + transformers >= 5.19 (build environment only; the app never imports them). The graph is the 31-layer
encoder + projection + sub-pixel upsampler + classifier for one offline step of 684 encoder frames
(speaker cache 264 + FIFO 40 + chunk 340 + look-ahead 40), padded and masked; everything else (features, feature
stacking, Arrival-Order Speaker Cache) is reimplemented in numpy in backend/sabhalekh/diarization/nemotron_onnx.py.
Adapted from the export in the user's nemotron-diarization project (Apache-2.0).
"""
import argparse
import os

import torch
from torch import nn
from transformers import AutoModelForAudioFrameClassification

MODEL_ID = "nvidia/Nemotron-3-Diarization"
MASK_VALUE = -10000.0


class EncoderClassifier(nn.Module):
    def __init__(self, model, length: int):
        super().__init__()
        tower = model.model.audio_tower
        self.input_layer_norm = tower.input_layer_norm
        self.layers = tower.layers
        self.layer_norm = tower.layer_norm
        self.proj = model.model.proj
        self.upsampler = model.model.upsampler
        self.classifier = model.classifier
        cos, sin = tower.rotary_emb(torch.zeros(1, dtype=torch.float32), torch.arange(length)[None])
        self.register_buffer("cos", cos, persistent=False)
        self.register_buffer("sin", sin, persistent=False)

    def forward(self, inputs_embeds, valid):
        bias = ((1.0 - valid) * MASK_VALUE)[:, None, None, :]
        hidden = self.input_layer_norm(inputs_embeds)
        for layer in self.layers:
            hidden = layer(hidden, attention_mask=bias, position_embeddings=(self.cos, self.sin))
        hidden = self.proj(self.layer_norm(hidden)) * valid[..., None]
        return self.classifier(self.upsampler(hidden))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    model = AutoModelForAudioFrameClassification.from_pretrained(MODEL_ID, attn_implementation="eager").eval()
    c = model.config
    length = c.streaming_config.speaker_cache_length + c.fifo_length + c.chunk_length + c.chunk_right_context
    hidden = c.audio_config.hidden_size
    block = EncoderClassifier(model, length).eval()
    with torch.no_grad():  # padded graph == original unpadded step
        n = 420
        e = torch.randn(1, n, hidden)
        ref = model.classifier(model.model(inputs_embeds=e, position_ids=torch.arange(n)[None]).last_hidden_state)
        x = torch.zeros(1, length, hidden)
        x[:, :n] = e
        v = torch.zeros(1, length)
        v[:, :n] = 1
        diff = (block(x, v)[:, : n * 8] - ref).abs().max().item()
    assert diff < 1e-3, f"padded graph diverges ({diff})"
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    torch.onnx.export(block, (torch.zeros(1, length, hidden), torch.ones(1, length)), args.out,
                      input_names=["inputs_embeds", "valid"], output_names=["logits"], opset_version=17,
                      do_constant_folding=True, dynamo=False)
    print(f"wrote {args.out} ({os.path.getsize(args.out) / 1e6:.0f} MB), max |dlogit| vs reference {diff:.1e}")


if __name__ == "__main__":
    main()
