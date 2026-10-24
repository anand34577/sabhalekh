# Third-party licenses

Sabhalekh bundles the models, libraries and fonts below so that it runs fully offline. Each is used under its own
license; full texts are in [`licenses/`](licenses/) and are installed next to the app. Versions are the ones the
installer was built and tested with.

## Models

| Component | Version | License | Notes |
|---|---|---|---|
| NVIDIA **Nemotron-3-Diarization** (`nvidia/Nemotron-3-Diarization`) | snapshot f667ed7 | **OpenMDW-1.1** ([text](licenses/OpenMDW-1.1.txt)) | Bundled as a derived ONNX export (encoder + classifier, dynamically int8-quantized) plus the feature-stacking weights in `frontend.npz`. OpenMDW-1.1 allows commercial and non-commercial use, modification and redistribution; this notice and the license text must accompany redistributed model materials. The *preview* repository (`Nemotron-3-Diarization-preview`) has evaluation-only terms and is **not** used. |
| NVIDIA **Nemotron 3.5 ASR Streaming 0.6B** (`nvidia/nemotron-3.5-asr-streaming-0.6b`), default speech recognition | GGUF Q8_0 from `handy-computer/nemotron-3.5-asr-streaming-0.6b-gguf` | **OpenMDW-1.1** ([text](licenses/OpenMDW-1.1.txt)) | Bundled as the transcribe.cpp GGUF conversion (Q8_0 quantization), unmodified. Same license and notice obligations as Nemotron-3-Diarization. |
| OpenAI **Whisper large-v3-turbo** weights (optional, no longer bundled) | openai/whisper-large-v3-turbo | MIT | Converted to CTranslate2 int8 (`ct2-transformers-converter --quantization int8_float16`). |
| OpenAI **Whisper large-v3** weights (Accuracy model pack) | openai/whisper-large-v3 | MIT | Same conversion. |
| **Silero VAD** v6 (ONNX, shipped inside faster-whisper) | 6 | MIT | |

## Runtime libraries (Python backend)

| Component | Version | License |
|---|---|---|
| CPython | 3.12 | PSF-2.0 |
| transcribe.cpp (`transcribe.dll`) and its Python bindings `transcribe-cpp` (handy-computer) | 0.4.0 (commit b61b7f9) | MIT ([text](licenses/transcribe.cpp-MIT.txt)) |
| ggml (`ggml.dll`, `ggml-base.dll`, `ggml-cpu.dll`, `ggml-vulkan.dll`, vendored in transcribe.cpp) | transcribe.cpp 0.4.0 | MIT ([text](licenses/ggml-MIT.txt)) |
| faster-whisper (SYSTRAN) | 1.2.1 | MIT |
| CTranslate2 (OpenNMT) | 4.8.3 | MIT |
| ONNX Runtime (Microsoft) | 1.31.0 | MIT |
| PyAV | 19.0.1 | BSD-3-Clause |
| FFmpeg libraries (shipped inside the PyAV wheel) | libavcodec 63 / libavformat 63 | LGPL-2.1-or-later **plus GPL-2.0-or-later components** (see below) |
| NumPy | 2.5.4 | BSD-3-Clause |
| tokenizers (Hugging Face) | 0.23.3 | Apache-2.0 |
| huggingface_hub (imported by faster-whisper; never contacts the network, offline mode is forced) | 2.2.0 | Apache-2.0 |
| FastAPI | 0.143.2 | MIT |
| Starlette | 1.8.0 | BSD-3-Clause |
| Uvicorn | 0.54.0 | BSD-3-Clause |
| websockets | 17.2 | BSD-3-Clause |
| Pydantic / pydantic-core | 2.14.1 / 2.50.1 | MIT |
| anyio, h11, annotated-types | | MIT |
| click, idna | | BSD-3-Clause |
| typing_extensions | | PSF-2.0 |
| PyAudioWPatch (PortAudio with WASAPI loopback) | 0.2.12.9 | Apache-2.0 (PortAudio: MIT) |
| psutil | 7.2.2 | BSD-3-Clause |
| nvidia-ml-py (NVML bindings; NVML itself ships with the NVIDIA driver) | 13.615.71 | BSD-3-Clause |
| python-docx | 1.2.0 | MIT |
| lxml (used by python-docx) | 6.1.3 | BSD-3-Clause (libxml2/libxslt: MIT) |
| fpdf2 | 2.8.9 | **LGPL-3.0-or-later** (used unmodified as a dynamically imported library) |
| uharfbuzz / HarfBuzz | 0.56.3 | Apache-2.0 / MIT ("Old MIT") |
| fontTools | 4.67.0 | MIT |
| tqdm (imported by faster-whisper) | 4.70.1 | MPL-2.0 AND MIT |
| PyInstaller bootloader | 6.x | GPL-2.0 with the PyInstaller bootloader exception (allows distributing frozen apps under any license) |

### FFmpeg and GPL components

The prebuilt PyAV wheel for Windows ships FFmpeg 8 shared libraries configured with `--enable-version3` and with
**libx264** and **libx265** (GPL-2.0-or-later) and SVT-AV1, libvpx, libdav1d, libopus, libmp3lame, libwebp, libvmaf,
zlib (BSD/MIT/LGPL-compatible). Sabhalekh only decodes audio and encodes Opus audio; it never encodes video, but the
DLLs are present, so the combined FFmpeg binaries are distributed under the terms of the **GPL-2.0-or-later** (and
LGPL-3.0 for the version-3 parts). Corresponding source code: <https://ffmpeg.org/download.html>,
<https://code.videolan.org/videolan/x264>, <https://bitbucket.org/multicoreware/x265_git>, and PyAV's build scripts at
<https://github.com/PyAV-Org/PyAV> (tag v19.0.1). Sabhalekh's own source code is MIT licensed and published in full at
<https://github.com/anand34577/sabhalekh>, so the complete corresponding source of the distributed program is
available. On request (open an issue in the repository) we will also provide the exact FFmpeg, x264 and x265 source
archives used for a given release for at least three years after that release. Anyone redistributing Sabhalekh in a
closed-source product should
rebuild PyAV against an LGPL-only FFmpeg (`--disable-gpl`, without libx264/libx265); Sabhalekh needs only the
audio decoders, the resampler and the libopus encoder.

### Not bundled: NVIDIA cuBLAS

Earlier pre-release builds shipped NVIDIA cuBLAS (`cublas64_12.dll`, `cublasLt64_12.dll`) for Whisper on CUDA. Sabhalekh
no longer distributes it: it is proprietary software under the NVIDIA CUDA Toolkit EULA and it is not needed by the
default speech engine. If you want Whisper model packs to use an NVIDIA GPU, install the
[CUDA 12 Toolkit](https://developer.nvidia.com/cuda-downloads) or obtain cuBLAS 12 from NVIDIA yourself and copy the
two DLLs into `%APPDATA%\Sabhalekh\cuda`. Your use of cuBLAS is then governed by NVIDIA's license, which is between you
and NVIDIA.

## Desktop shell

| Component | License |
|---|---|
| Tauri 2 (+ plugins: dialog, notification, global-shortcut, autostart, opener, single-instance) and its Rust dependency tree | MIT OR Apache-2.0 (dependencies: MIT / Apache-2.0 / BSD / ISC / Zlib / Unicode-3.0) |
| Microsoft Edge WebView2 Runtime | Part of Windows 10/11; not redistributed by Sabhalekh |
| React, React DOM | MIT |
| zustand | MIT |
| lucide-react | ISC |
| clsx | MIT |
| Tailwind CSS (build time; only generated CSS is shipped) | MIT |

## Fonts

| Font | License |
|---|---|
| Noto Sans (Regular, Medium, Bold) | SIL Open Font License 1.1 ([text](licenses/OFL-1.1-Noto.txt)) |
| Noto Sans Devanagari (Regular, Medium, Bold) | SIL Open Font License 1.1 |

## Test data (repository only, not installed)

| Data | License |
|---|---|
| `tests/data/hindi/*.wav`, Hindi part of `tests/data/two_speaker_en_hi.wav`: Google **FLEURS** `hi_in` dev split | CC-BY-4.0 (Conneau et al., 2022) |
| English part of `tests/data/two_speaker_en_hi.wav`: synthesized with the Windows SAPI voice "Microsoft Zira Desktop" | Generated audio, used for testing only |

## Build-time only (not shipped)

PyTorch, transformers, librosa, safetensors (Nemotron frontend export), `onnx` / `onnxruntime.quantization`
(int8 quantization), `ctranslate2` converter, pytest, pypdfium2, Pillow, Vite, TypeScript, Vitest.
