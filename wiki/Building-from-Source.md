# Building from source

This page is for developers. To simply use Sabhalekh, download the installer from the
[releases page](https://github.com/anand34577/sabhalekh/releases/latest).

## Project layout

```
app/            Desktop shell: Tauri 2 (src-tauri/, Rust) and the React + TypeScript UI (src/)
backend/        Python 3.12 engine: sabhalekh/ (api, db, pipeline, asr, diarization, audio, export, hardware, netguard)
fonts/          Noto Sans and Noto Sans Devanagari (SIL OFL), used in the UI and in PDF/DOCX exports
installer/      build.ps1 (installer), dev.ps1 (development window), toolchain.ps1 (Rust toolchain selection)
licenses/       License texts of bundled third-party components
models/         Converted models (not in git; produced by tools\fetch_models.py)
tests/          pytest suite and fixtures
tools/          Model conversion, WER benchmark, model packs, icons, brand images, research scripts
docs/           Design decisions, feasibility report, images
wiki/           This user guide (published to the GitHub wiki by CI)
```

How the parts fit together, and why they were chosen, is in
[docs/design-decisions.md](https://github.com/anand34577/sabhalekh/blob/main/docs/design-decisions.md).

## Prerequisites

- Windows 10 or 11
- [Python 3.12](https://www.python.org/downloads/)
- [Node.js 20 or newer](https://nodejs.org/)
- [Rust](https://rustup.rs/), plus **either** Visual Studio Build Tools with *Desktop development with C++* **or** a
  MinGW-w64 GCC such as TDM-GCC-64 with `rustup toolchain install stable-x86_64-pc-windows-gnu`.
  `installer\toolchain.ps1` picks whichever is available.
- For the models (once): about 10 GB of free disk space and an internet connection on the build machine.
- For the transcribe.cpp runtime (once): [CMake](https://cmake.org/) and the [Vulkan SDK](https://vulkan.lunarg.com/).

## 1. Backend and tests

```powershell
git clone https://github.com/anand34577/sabhalekh.git
cd sabhalekh
py -3.12 -m venv .venv
.venv\Scripts\pip install -r backend\requirements-dev.txt
.venv\Scripts\python -m pytest tests -q
```

Without models the integration tests are skipped; everything else runs. To let Whisper use an NVIDIA GPU while you
develop, also install `backend\requirements-gpu.txt` (NVIDIA cuBLAS; never shipped).

## 2. The UI

```powershell
cd app
npm ci
npm test
npm run build
```

For quick UI work in a normal browser, start the engine and the dev server:

```powershell
.venv\Scripts\python backend\run_backend.py --token devtoken0123456789 --port 8791
cd app; npm run dev
```

Then open `http://localhost:1420/?port=8791&token=devtoken0123456789`. Native features (file dialogs, tray, hotkey)
only work in the desktop window.

## 3. The models (once)

The app ships converted models. Producing them needs internet, but only on the build machine:

```powershell
py -3.12 -m venv .buildenv
.buildenv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cpu
.buildenv\Scripts\pip install -r tools\requirements-build-models.txt
.buildenv\Scripts\python tools\fetch_models.py --with-large-v3
```

This downloads NVIDIA Nemotron 3.5 ASR (GGUF Q8_0 from `handy-computer/nemotron-3.5-asr-streaming-0.6b-gguf`), exports
the Nemotron-3-Diarization encoder to ONNX and quantizes it to int8, extracts its small front-end weights, and, with
`--with-large-v3`, converts Whisper large-v3 to CTranslate2 int8 for the Accuracy pack.

## 4. The transcribe.cpp runtime (once)

Build [transcribe.cpp](https://github.com/handy-computer/transcribe.cpp) as a shared library with the Vulkan backend:

```powershell
git clone https://github.com/handy-computer/transcribe.cpp C:\tc
cd C:\tc
cmake -B build-dl -DTRANSCRIBE_BUILD_SHARED=ON -DGGML_VULKAN=ON
cmake --build build-dl --config Release
```

Copy `transcribe.dll`, `ggml.dll`, `ggml-base.dll`, `ggml-cpu.dll` and `ggml-vulkan.dll` into `bin\transcribe\` in the
Sabhalekh folder. `installer\build.ps1` installs the Python bindings from `C:\tc` (or `-TranscribeCpp <path>`).

## 5. Run the desktop app

```powershell
powershell -ExecutionPolicy Bypass -File installer\dev.ps1
```

This opens the Tauri window with a hot-reloading UI and the engine running from `.venv`.

## 6. Build the installer

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

It runs the tests, freezes the engine with PyInstaller and smoke-tests it, stages the models with a SHA-256 manifest,
builds the Tauri shell and the NSIS installer, and writes to `dist\`:

| File | Contents |
|---|---|
| `Sabhalekh-Setup-<version>.exe` | App, Nemotron ASR, Nemotron diarization, transcribe.cpp (CPU + Vulkan) |
| `Sabhalekh-ModelPack-Accuracy\` and `.zip` | Whisper large-v3 (only if `models\asr\whisper-large-v3-int8` exists) |
| `SHA256SUMS.txt` | Checksums of the files above |

Options: `-SkipTests`, `-NoModelPack`, `-TranscribeCpp <path>`.

## Making an offline model pack

```powershell
.venv\Scripts\python tools\make_manifest.py pack OUT_DIR NAME MODEL_ID:SOURCE_DIR ...
```

Model IDs are listed in `backend/sabhalekh/models.py`. A pack's `sabhalekh-pack.json` may also list your own
transcribe.cpp model (engine `transcribe-cpp`, a folder with one `.gguf`), for example a Hinglish fine-tune of Nemotron.

## Comparing speech models

```powershell
.venv\Scripts\python tools\benchmark_wer.py --manifest my.jsonl --model models\asr\nemotron-3.5-asr-0.6b --model models\asr\whisper-large-v3-int8
```

A `.gguf` model runs on transcribe.cpp (`--accel gpu|igpu|cpu`); a CTranslate2 folder runs on Whisper.

## Releasing

1. Update the version in `backend/sabhalekh/__init__.py`, `app/package.json`, `app/src-tauri/tauri.conf.json` and
   `app/src-tauri/Cargo.toml`, and move the **Unreleased** notes in `CHANGELOG.md` under the new version.
2. Merge to `main` through a pull request; CI must pass.
3. Build with `installer\build.ps1` on a machine that has the models.
4. Tag and publish:

   ```powershell
   git tag -a v1.2.0 -m "Sabhalekh 1.2.0"
   git push origin v1.2.0
   gh release create v1.2.0 dist\Sabhalekh-Setup-1.2.0.exe dist\Sabhalekh-ModelPack-Accuracy.zip dist\SHA256SUMS.txt --title "Sabhalekh 1.2.0" --notes-file notes.md
   ```

### Releasing with GitHub Actions

The **Release** workflow does steps 3 and 4 for Windows, macOS and Linux. Push the tag (`git tag -a v1.4.0 -m
"Sabhalekh 1.4.0"` then `git push origin v1.4.0`), or open *Actions → Release → Run workflow* and enter an existing
tag to attach the files to that release. Leave the tag empty to only test the build; the installers are then kept as
workflow artifacts for a week.

It converts the models once (cached), downloads the prebuilt transcribe.cpp runtime for each platform, freezes and
smoke-tests the backend, builds the Tauri installer and uploads these files with a combined `SHA256SUMS.txt`:

| File | Platform |
|---|---|
| `Sabhalekh-Setup-<version>.exe` | Windows 10/11, 64-bit |
| `Sabhalekh-<version>-macos-arm64.dmg` | macOS, Apple silicon (no Intel build) |
| `Sabhalekh-<version>-linux-x86_64.deb` | Linux, 64-bit (Debian, Ubuntu) |
| `Sabhalekh-ModelPack-Accuracy.zip` | Optional model pack |

The tag must match the version in `tauri.conf.json`. Recording meetings is Windows-only; macOS and Linux import
audio and video. The macOS and Windows builds are not code-signed yet.

Building locally with `installeruild.ps1` still works; the checksums in `SHA256SUMS.txt` let anyone verify what they
download.
