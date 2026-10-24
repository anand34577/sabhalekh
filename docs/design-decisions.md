# Design decisions

Why Sabhalekh is built the way it is: every non-obvious choice, with the reason and the numbers behind it.
Measurements were taken on the reference laptop: Windows 11, AMD Ryzen 5 5600H (6 cores / 12 threads), 23 GB RAM, **NVIDIA GTX 1650, 4 GB VRAM** (Turing,
compute capability 7.5). Details: [feasibility-report.md](feasibility-report.md).

## D1. No PyTorch at runtime: Nemotron-3-Diarization runs as ONNX + numpy
Nemotron officially targets Linux + Ampere-or-newer GPUs through NeMo/PyTorch; a CUDA build of PyTorch alone is ~2.5 GB.
The heavy step (31-layer encoder + head, 99M params) was exported to a fixed-shape ONNX graph (684 encoder frames,
padded and masked) and everything around it (log-mel features, feature stacking, the Arrival-Order Speaker Cache) was
reimplemented in ~250 lines of numpy (`backend/sabhalekh/diarization/nemotron_onnx.py`). Against the GPU/PyTorch
reference: **100.000 % / 99.999 %** of 10 ms speaker decisions identical (fp32), same speaker count.
The same pluggable `DiarizationEngine` interface would accept other engines; none is needed because ONNX Runtime runs on
every Windows CPU. If the model files are missing or corrupt, a clearly labelled single-speaker fallback is used and the
session shows a warning: diarization is never skipped silently.

## D2. Diarization on the CPU, dynamically int8-quantized
fp32 ONNX: 417 MB, 22× real time. Dynamic int8 (per-channel weights, `onnxruntime.quantization.quantize_dynamic`):
**122 MB, 41–43× real time**, 99.98 % frame agreement, identical speaker counts. A 60-minute file takes **83 s with
481 MB peak RAM**. Running it on the CPU also leaves all 4 GB of VRAM to Whisper, so "low-VRAM sequential offloading"
needs no model swapping at all. (Static int8 was rejected: the same project's RKNN static-int8 attempt found 7 speakers
instead of 2 on a real recording; dynamic quantization keeps activation scales per call.)

## D18. ASR default since 1.1: NVIDIA Nemotron 3.5 ASR on transcribe.cpp (supersedes D3)
Measured on the GTX 1650 laptop (Radeon iGPU, Ryzen 5 5600H), Nemotron 3.5 ASR Streaming 0.6B GGUF Q8_0:

| | Hindi WER / CER (FLEURS, 12 utt.) | Speed, 129 s Hinglish meeting | Memory |
|---|---|---|---|
| Nemotron on GTX 1650 (Vulkan) | **19.2 % / 10.2 %** | **18× RT** | 0.73 GB VRAM, +140 MB RAM |
| Nemotron on Radeon iGPU (Vulkan) | same | 19× RT | ~0.95 GB shared RAM |
| Nemotron on CPU (6 threads) | same | 8× RT | +1.1 GB RAM |
| Whisper large-v3-turbo (D3) | 26.8 % / 11.6 % | 8.5× RT | 1.9 GB VRAM |
| Whisper large-v3 (D3) | 23.0 % / 8.8 % | 3.4× RT | 3.3 GB VRAM |

* **Engine**: transcribe.cpp (ggml) through its ctypes Python bindings, in-process: audio stays in memory, no
  subprocess or temp WAVs, and the model is freed after every job (it reloads in ~1 s). Only the CPU and **Vulkan**
  ggml backends ship (~45 MB). Vulkan drives NVIDIA GPUs at the same speed as CUDA here and also AMD/Intel and
  integrated GPUs, so ggml-cuda (200 MB) is not bundled, and loading it would also reorder the Vulkan devices.
* **Devices**: matched by type and name, never by index; Vulkan's numbering differs between processes (in the CLI
  with CUDA loaded, `--device 2` was the iGPU; in the backend, Vulkan1 is the GTX). Auto order: discrete GPU (its
  own VRAM leaves system RAM to the meeting apps) when ≥ 1.2 GB is free → iGPU → CPU, via the existing OOM step-down.
* **Language**: Nemotron needs no 30 s window and detects the language itself. In Auto mode each chunk (one speaker
  turn, D6 cuts) is decoded without a language; English chunks end in `<en-US>`, Hindi ones get no tag, so tag, else
  script, decides. Decoding a whole mixed clip as Hindi dropped an English sentence; per-turn decoding did not.
* **Batching**: `run_batch()` was slower than one `run()` per chunk on both GPUs (7.2 vs 6.9 s), so chunks run in turn.
* **Kept from Whisper**: Translate Hindi to English (Nemotron cannot translate) and custom vocabulary (Nemotron has
  no prompt input) need a Whisper model from an Offline Model Pack; Whisper uses CUDA when cuBLAS is available (D19).

## D3. ASR default: Whisper large-v3-turbo (int8) in the installer; large-v3 as an Offline Model Pack
*Superseded by D18 in 1.1; kept for the measurements.*
Measured on the GTX 1650 (10-minute English/Hindi file, batch 4, int8_float16):

| Model | Speed | Peak VRAM | Hindi WER / CER (FLEURS, 12 utt.) | Disk |
|---|---|---|---|---|
| large-v3-turbo | **8.5× RT** | **1.9 GB** | 28.0 % / 11.1 % | 0.78 GB |
| large-v3 | 3.4× RT | 3.3 GB (batch 2) | **24.1 % / 9.1 %** | 1.5 GB |

The goal was a small install that runs well on a 4 GB card: turbo is 2.5× faster, half the size and leaves VRAM
headroom for Teams/browser during processing. large-v3 is ~12 % more accurate on Hindi and is required for
"Translate Hindi to English" (turbo was not trained to translate), so it ships as the **Accuracy** Offline Model Pack,
imported from a folder/USB drive. Once it is installed, "Automatic" uses large-v3 on the GPU for every job: on real
Hinglish meetings it was clearly better than turbo (D17), and importing the pack is an explicit choice for accuracy.
Without the pack, translation is unavailable and the app explains why. Indic fine-tunes can be added through the pluggable ASR
interface and compared with `tools/benchmark_wer.py`.

## D4. GTX 16xx cards never use pure FP16
Measured: turbo float16 = **2.2× RT** vs int8_float16 = 8.5× RT on the GTX 1650 (Turing GTX parts have no tensor
cores). The "High-Performance GPU" profile therefore uses FP16 only on tensor-core GPUs and int8_float16 on GTX/MX parts.

## D5. Whisper on CUDA needs only cuBLAS
CTranslate2 4.8 runs Whisper on CUDA with `cublas64_12.dll` + `cublasLt64_12.dll` alone; cuDNN (~800 MB) and NVRTC are
not needed (verified on the GTX 1650). Since 1.2 cuBLAS is no longer bundled (D19).

## D6. Per-chunk English/Hindi routing instead of Whisper's own language detection
Whisper's detector chooses among 99 languages: Hindi often comes out as Urdu (Perso-Arabic script) and short chunks are
misclassified (one FLEURS clip scored ~0 for both English and Hindi and was *translated* to English). Sabhalekh reuses
the encoder pass of each batch, scores only English vs Hindi (+Urdu probability, same spoken language), lets unclear
chunks follow a confident neighbour, and defaults to Hindi when nothing is known: Hindi decoding of English speech
still yields the English words, while English decoding of Hindi speech silently translates it. For the same reason a
chunk gets the English token only when it is confidently English (p_en > 0.85 and > 4 × p_hi): Hinglish speech often
scores as English, and decoded as English its Hindi words were dropped.

## D7. Chunks never mix languages; skipped speech is re-transcribed
A chunk is decoded with one language token; on an English/Hindi turn-taking clip Whisper silently dropped the
other-language half of mixed chunks. But every chunk costs one 30 s encoder pass (~2 s on a GTX 1650), so cutting at
every speaker change is expensive: on an hour of rapidly alternating speakers it produced **459 chunks instead of 186**
and slowed transcription from 8.5× to 3.5× real time. So chunks are cut only where the language can change:
* English-only / Hindi-only modes: never (the language token is fixed).
* Auto mode: diarization runs first; each speaker's ≤ 3 longest turns get one language-detection pass (no decoding).
  Changes between two speakers of the same single language need no cut; speakers who mix languages, or could not be
  profiled, always get one. Same-speaker speech is merged across pauses (≤ 1.5 s) into chunks of up to 28 s.

A **gap-fill pass** then re-transcribes any VAD speech region the words do not cover (each region with its own language
detection), which also fixes Whisper's general habit of skipping speech in long chunks.

## D8. Tauri 2 instead of Electron
~10 MB shell instead of ~150 MB, native tray/notifications/hotkeys/autostart via official plugins, strict CSP for the
offline guarantee. PDF export uses fpdf2 + HarfBuzz (see D10) instead of Chromium's printToPDF.
**Toolchain note:** on a PC with Visual Studio but without the C++ workload the MSVC Rust toolchain cannot link. The
shell then builds with `stable-x86_64-pc-windows-gnu` + TDM-GCC; `installer/toolchain.ps1` picks MSVC when available and
otherwise applies the two GNU workarounds (empty `libgcc_eh.a` stub, system `dlltool`). `crate-type` is `rlib` only:
the mobile `cdylib` exceeds GNU ld's DLL export-ordinal limit.

## D9. FFmpeg through PyAV instead of a bundled ffmpeg.exe
faster-whisper already depends on PyAV, whose wheel ships the FFmpeg libraries (~65 MB). They decode every required
format (mp3, wav, m4a, aac, flac, ogg, wma, mp4, mkv, mov, avi, webm), resample, and encode the Opus playback copy, so a
separate ~140 MB ffmpeg.exe is unnecessary. Licensing caveat (GPL x264/x265 inside the wheel) is documented in
THIRD_PARTY_LICENSES.md.

## D10. PDF via fpdf2 + HarfBuzz (uharfbuzz); DOCX with a complex-script font
fpdf2's text shaping uses HarfBuzz, so Devanagari conjuncts, reph and matras render correctly (golden-image test,
`tests/data/golden/report_hindi_page1.png`). DOCX runs set `w:cs="Noto Sans Devanagari"` and `w:lang w:bidi="hi-IN"`.

## D11. Python 3.12 (not 3.11)
3.11 is not installed here; every dependency supports 3.12, and PyInstaller freezes the interpreter anyway.

## D12. Storage layout
SQLite (WAL) with numbered migrations; audio per session under `%APPDATA%\Sabhalekh\sessions\<id>\`:
`audio_16k.wav` (pipeline), `mic_16k.wav` + `system_16k.wav` (recordings), `playback.ogg` (Opus; stereo for
mic + system recordings) and `peaks.json` (waveform). Imports are never copied or modified: the original file is
read once during extraction, and only the extracted audio is kept as a playback copy.

## D13. Offline guarantee enforced in code, not just promised
The backend installs a socket guard (`netguard.py`) before anything else is imported: every non-loopback connect,
send and DNS lookup raises, and `huggingface_hub` is forced into offline mode. The webview runs under a CSP that allows
only bundled files and `http/ws://127.0.0.1`, and WebView2's background networking (SmartScreen, translation,
component updates) is switched off. There is no updater. `tests/test_offline.py` fails if any of this regresses,
including a scan of the built UI bundle for remote assets. The only way to reach the internet is a link the user
clicks in Settings → About, which opens in their own browser.

## D14. Two-track recordings: the microphone is "You"
The microphone and the system output (WASAPI loopback) are recorded as two 16 kHz WAV files that are flushed
continuously, so a crash loses at most the last ~2 s and the recording can be recovered on the next start. The
microphone track is transcribed as **"You"** and never diarized; only the system track (the other participants) goes
through Nemotron. Without headphones the microphone also hears the loudspeakers, so microphone segments that repeat
what was played at the same time (text similarity ≥ 0.6, overlapping in time) are dropped as echo. If the PC played
nothing (an in-person meeting), the microphone track is diarized instead.

## D15. One heavy job at a time, persisted
Transcription saturates the GPU or CPU, so jobs run strictly one after another from a queue stored in SQLite. A job
interrupted by closing the app is resumed on the next start; failed jobs keep a plain-language reason ("The disk is
full. Free some space and retry.") and can be retried with one click.

## D16. Search: FTS5 trigram index plus Roman transliteration
SQLite's `unicode61` tokenizer splits Hindi words inside conjuncts, so search uses an FTS5 **trigram** index over
NFC-normalized text, with a LIKE fallback for 1–2 character queries that trigrams cannot match. Each segment is also
indexed in a Roman transliteration, so `kya` finds `क्या`. Transliteration is rule-based: common words match, but
spellings that differ from the scheme (for example `iran` for `ईरान`) do not.

## D17. Whisper on Hinglish: a mixed-script style prompt
Found on the first real recorded meetings: without a prompt, Whisper writes the English words of Hinglish speech as
phonetic Devanagari, inconsistently ("कोश्चिन", "पॉसिटिव"), while one sentence later "questions" comes out in Latin
letters. Whisper copies the writing style of its prompt, so Hindi chunks are decoded with a short mixed-script prompt
(Devanagari for Hindi, Latin for English words, or all-Devanagari in Devanagari mode), followed by the custom
vocabulary. English chunks get only the vocabulary (a Hindi prompt pushed them into Devanagari). On unclear audio
Whisper sometimes writes the prompt instead of the speech; output that repeats a run of four prompt words is detected
and the chunk is decoded again without the prompt. (Nemotron, the default since 1.1, takes no prompt; this applies to
Whisper model packs.)

## D19. NVIDIA cuBLAS is not bundled
cuBLAS is proprietary (CUDA EULA), and it would share a process with the GPL-licensed FFmpeg libraries from the PyAV
wheel; it was also 736 MB of a 1.3 GB installer. The bundled Nemotron ASR runs on GPUs through Vulkan and never needs
it, so the installer leaves it out. Whisper model packs use an NVIDIA GPU only when cuBLAS 12 is available from an
installed CUDA 12 Toolkit or from DLLs the user copies into `%APPDATA%\Sabhalekh\cuda`; otherwise they run on the CPU.

## Considered and not done
* **MarbleNet VAD**: Silero VAD v6 (bundled in faster-whisper) is used; it is small, accurate and already shipped.
* **"Minimum speakers"** cannot force Nemotron to find more voices; Sabhalekh lowers the activity threshold instead,
  which helps quiet speakers but cannot separate voices the model merges.
* **Voice enrollment** (recognising the same person across meetings) is not implemented: speaker names are per
  meeting.
