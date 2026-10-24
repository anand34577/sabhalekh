# Feasibility report

**Question:** can NVIDIA Nemotron-3-Diarization run (a) natively on Windows inside the packaged Python sidecar, without
WSL2 or Docker, (b) on the GPU and on the CPU, (c) on a 60-minute file with acceptable speed and memory? And which
speech recognition setup fits a 4 GB GTX 1650?

**Answer: yes on all three**, without NeMo and without PyTorch, on this exact machine.

## Test machine

| | |
|---|---|
| OS | Windows 11 Home Single Language, build 26300 |
| CPU | AMD Ryzen 5 5600H, 6 cores / 12 threads |
| RAM | 23.3 GB |
| GPU | NVIDIA GeForce **GTX 1650, 4 GB** (Turing, compute capability 7.5, no tensor cores), driver 592.82 (CUDA 13.1) |
| Python | 3.12 (venv), onnxruntime 1.31.0, CTranslate2 4.8.3, faster-whisper 1.2.1 |

## 1. Nemotron-3-Diarization

### Starting point
Officially the model is used through NeMo / transformers + PyTorch, documented for Linux and Ampere-or-newer GPUs.
An earlier experiment had already shown that it *runs* on this GTX 1650 (CUDA) and on
the CPU through transformers 5.19 + PyTorch 2.6 (cu124), and exported the encoder step to ONNX. A CUDA PyTorch adds
~2.5 GB to an installer, which conflicts with "it shouldn't be large".

### What was built
The model's offline forward was split into:

* **Heavy part, ONNX** (one fixed-shape graph, 684 encoder frames = speaker cache 264 + FIFO 40 + chunk 340 +
  look-ahead 40, padded and masked): 31-layer transformer encoder, projection, sub-pixel upsampler, classifier.
* **Everything else, numpy** (`backend/sabhalekh/diarization/nemotron_onnx.py`, ~250 lines): pre-emphasis, centered
  Hann STFT (n_fft 512, win 400, hop 160), slaney mel (128), log; feature stacking (8 frames → 1024 → linear 512);
  the Arrival-Order Speaker Cache with FIFO, score boosting and compression, ported line by line from
  `transformers.models.nemotron3_diarization`. Features are computed lazily per chunk, so memory does not grow with
  the recording length.
* The small non-encoder weights (mel filters, 1024×512 projection, silence embedding) are in `frontend.npz` (2 MB).

### Accuracy against the GPU/PyTorch reference
Reference = per-frame speaker probabilities produced by the original model on the GPU through transformers + PyTorch
(10 ms frames, 8 speakers), compared with the ONNX + numpy port on the same audio:

| Variant | Size | Identical 10 ms speaker decisions | Speaker count |
|---|---|---|---|
| ONNX fp32 | 417 MB | 100.000 % / 99.999 % | same |
| ONNX dynamic int8 (shipped) | 122 MB | 99.98 % | same |

Static int8 quantization was rejected: a static-int8 build of the same model on another runtime found 7 speakers
instead of 2 on a real recording. Dynamic quantization keeps activation scales per call and does not have that problem.

### Speed and memory (CPU, 6 cores)

| | fp32 | int8 |
|---|---|---|
| Speed | 22× real time | **41–43× real time** |
| 60-minute file | | **83 s, 481 MB peak RAM** |

Features are computed per chunk, so memory does not grow with the length of the recording.

### GPU or CPU?
* GPU: possible through PyTorch CUDA or onnxruntime-gpu, but both add 1–2.5 GB of CUDA libraries.
* CPU: already faster than speech recognition on the GPU, and it leaves all VRAM to the ASR model. On a 4 GB card this
  removes any model swapping between stages. **Decision: diarization runs on the CPU.**

## 2. Speech recognition on a 4 GB GTX 1650

Whisper through CTranslate2 (10-minute English/Hindi file; Hindi WER/CER on 12 FLEURS `hi_in` clips):

| Model | Speed | Peak VRAM | Hindi WER / CER | Disk |
|---|---|---|---|---|
| large-v3-turbo, int8_float16 | **8.5× RT** | **1.9 GB** | 28.0 % / 11.1 % | 0.78 GB |
| large-v3, int8_float16 | 3.4× RT | 3.3 GB (batch 2) | **24.1 % / 9.1 %** | 1.5 GB |
| large-v3-turbo, float16 | 2.2× RT | | | |

GTX 16xx cards have no tensor cores, so pure FP16 was four times slower than int8_float16. CTranslate2 needs only
cuBLAS for CUDA (no cuDNN, no NVRTC).

These results set the 1.0 defaults (turbo bundled, large-v3 as an Offline Model Pack). Version 1.1 replaced Whisper
with NVIDIA Nemotron 3.5 ASR on transcribe.cpp: 19.2 % Hindi WER at 18× real time with 0.73 GB VRAM on the same card
(see [design-decisions.md](design-decisions.md), D18).

## 3. End to end

Through the HTTP API with the real models (`tests/test_integration.py`):

| Input | Result |
|---|---|
| `meeting.mp4` (52 s, 3 English speakers, from the earlier experiment) | 3 speakers; talk shares 38.3 / 31.7 / 30.0 % (reference: 38.4 % for Speaker 1); turns correct |
| `two_speaker_en_hi.wav` (39 s, Hindi speaker + English speaker alternating) | 2 speakers, all 4 turns attributed correctly, EN/HI detected per segment, Hindi in Devanagari |
| Crash-recovered two-track recording (truncated WAV headers) | recovered; mic track = "You" (Hindi), system track diarized (English) |

## Conclusion
Nemotron-3-Diarization runs natively on Windows inside the packaged sidecar, without WSL, Docker, NeMo or PyTorch,
on any CPU, fast enough for hour-long meetings and within a laptop's memory. Everything else in the app builds on
that result.
