"""Build-time tool: dynamic int8 quantization of the Nemotron-3-Diarization ONNX encoder (417 MB -> 122 MB).

    python tools/quantize_nemotron.py SRC_FP32_ONNX models/diarization/nemotron3/encoder_int8.onnx

The fp32 graph comes from the encoder export (see docs in README "Rebuilding the models"). Measured against the
GPU reference on two recordings: 99.98% of 10 ms speaker decisions identical, same speaker count, ~41x real time on
a 6-core CPU (fp32: 22x). Needs `onnx`, `onnxruntime` (build environment only).
"""
import sys

from onnxruntime.quantization import QuantType, quantize_dynamic

src, dst = sys.argv[1], sys.argv[2]
quantize_dynamic(src, dst, weight_type=QuantType.QInt8, per_channel=True)
print("wrote", dst)
