# Offline model packs

The installer already contains everything you need: NVIDIA Nemotron 3.5 ASR for speech recognition and
Nemotron-3-Diarization for telling speakers apart. Model packs are **optional extras** you can add without an internet
connection on the PC that runs Sabhalekh.

## The Accuracy pack

| | |
|---|---|
| **Adds** | OpenAI Whisper large-v3 |
| **Gives you** | **Translate Hindi to English**, and **custom vocabulary** support |
| **Size** | about 1.5 GB |
| **Download** | `Sabhalekh-ModelPack-Accuracy.zip` on the [releases page](https://github.com/anand34577/sabhalekh/releases/latest) |

You only need it for translation. For normal English, Hindi and Hinglish transcripts, the built-in Nemotron model is
more accurate on Hindi and several times faster.

## Installing a pack

1. Download `Sabhalekh-ModelPack-Accuracy.zip`. You can download it on any computer and carry it over on a USB drive.
2. Right-click the zip → **Extract All…** You get a folder called `Sabhalekh-ModelPack-Accuracy`.
3. In Sabhalekh, open **Settings → Models** and click **Import Offline Model Pack…**
4. Choose the extracted **folder** (not the zip) and click **Select Folder**.
5. Sabhalekh checks every file against its checksum and copies it into `%APPDATA%\Sabhalekh\models`. That takes a
   minute or two. When it's done, Whisper large-v3 shows as installed.

You can delete the zip and the extracted folder afterwards.

To use translation, set **Settings → Transcription → Language** to **Translate Hindi to English**, or pick it for one
meeting with **⋯ → Re-process…**

## Making Whisper fast on an NVIDIA graphics card (optional)

Whisper is a large model. On the CPU, translating an hour-long meeting can take a long time. On an NVIDIA graphics card
it's many times faster, but that needs a library from NVIDIA called **cuBLAS**, which Sabhalekh can't include in its
installer for licensing reasons.

You can check whether it's set up in **Settings → Hardware → NVIDIA CUDA (Whisper packs)**. If it says *Available*,
you're done. If not, pick **one** of these:

**Option A: install the CUDA Toolkit (simplest).**
Download the **CUDA Toolkit 12.x** for Windows from [NVIDIA's website](https://developer.nvidia.com/cuda-12-9-0-download-archive)
and install it with the default options. Restart Sabhalekh. (Version 12 is needed; 13 won't work.)

**Option B: copy just the two files you need (smaller).**
If you already have them from another program, or download NVIDIA's cuBLAS 12 redistributable, copy
`cublas64_12.dll` and `cublasLt64_12.dll` into this folder (create it if it doesn't exist):

```
%APPDATA%\Sabhalekh\cuda
```

Restart Sabhalekh, then click **Settings → Hardware → Re-detect**.

The built-in Nemotron model **never** needs cuBLAS. It uses your graphics card through Vulkan, which comes with every
modern graphics driver.

## Making your own pack

Developers can bundle their own models, for example a fine-tuned Nemotron or another Whisper size, with
`tools\make_manifest.py`. See [Building from source](Building-from-Source#making-an-offline-model-pack).
