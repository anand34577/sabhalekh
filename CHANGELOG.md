# Changelog

All notable changes to Sabhalekh are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]

## [1.2.0] - 2026-10-24

First public release.

### What Sabhalekh does
- Records a Teams, Zoom or Meet call (your microphone and the other participants, as two tracks) or imports audio and
  video files, and turns them into a transcript with speaker names and timestamps.
- English, Hindi and Hinglish in the same meeting. Hindi can be shown as spoken, in Devanagari, or in Roman letters.
- Speech recognition with NVIDIA Nemotron 3.5 ASR on any graphics card (through Vulkan), on built-in graphics or on the
  CPU. Speaker detection with NVIDIA Nemotron-3-Diarization, up to 8 speakers.
- Click any word to play from there; rename speakers everywhere at once; edit, merge, split and undo lines.
- Search across all meetings, including romanised Hindi (`kya` finds `क्या`).
- Export to Word, PDF report, text, Markdown, SRT, VTT, JSON and CSV, one meeting or many at once.
- Fully offline: no account, no cloud, no telemetry, no update checks. Network access is blocked in code.

### Changed since the pre-release builds
- The app is now called **Sabhalekh**. The pre-release builds were called MeetScribe, a name already used by other
  products. Your meetings, settings and recordings move to the new data folder (`%APPDATA%\Sabhalekh`)
  automatically the first time you open Sabhalekh, and playback keeps working for every old meeting.
- The installer is about a third smaller (about 850 MB instead of 1.3 GB). It no longer includes NVIDIA's cuBLAS
  library, which only the optional Whisper model packs used. Whisper packs still use an NVIDIA graphics card if the
  CUDA 12 Toolkit is installed, or if you copy the two cuBLAS files into `%APPDATA%\Sabhalekh\cuda`; otherwise they run
  on the CPU. The built-in Nemotron speech recognition is not affected.
- The hardware badge says where speech recognition runs ("GPU Mode: GTX 1650") without technical precision labels.
- Settings → About has links to the user guide, the issue tracker and the source code. They open in your browser.

### Fixed
- The welcome guide said "Everything will run on the CPU" on PCs where the graphics card does the speech recognition
  through Vulkan (any PC without NVIDIA's CUDA libraries). It now names the device that is actually used.
- AMD and Intel graphics cards showed as "No NVIDIA GPU" in the welcome guide and the sidebar.
- The microphone and speaker test in the welcome guide left a temporary file behind, which then appeared as an
  "unfinished recording" to recover.
- Talk-time percentages could add up to 101 % (for example 75 % + 26 %). They now always add up to 100 %, in the app
  and in every export.
- A missing space in the audio test instructions.

## Pre-release builds (as MeetScribe)

These versions were tested privately before the public release and were never published.

- **1.1.0** (2026-10-17): NVIDIA Nemotron 3.5 ASR replaced Whisper large-v3-turbo as the default speech recognizer
  (Hindi word error rate 19 % instead of 27 %, about twice as fast, under half the graphics memory). Added the
  integrated-GPU profile.
- **1.0.2** (2026-10-16): better Hinglish with Whisper (English words stay in English), fewer hallucinated phrases.
- **1.0.1** (2026-10-16): fixed "Unable to open file 'model.bin'" in the installed app.
- **1.0.0** (2026-10-16): first build: recording, import, transcription, speaker detection, editor, search and
  exports.

[Unreleased]: https://github.com/anand34577/sabhalekh/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/anand34577/sabhalekh/releases/tag/v1.2.0
