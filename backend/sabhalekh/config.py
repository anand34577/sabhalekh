"""Filesystem layout. Everything the app reads ships in the app directory; everything it writes lives in DATA_DIR.

App directory (read-only at runtime):
    models/   ASR, VAD and diarization models + models/manifest.json (sha256 of every file)
    fonts/    Noto Sans + Noto Sans Devanagari (PDF/DOCX export)
    bin/      transcribe/ (transcribe.cpp + ggml for Nemotron ASR)
Data directory (%APPDATA%/Sabhalekh by default):
    sabhalekh.db, sessions/<id>/..., recordings-in-progress/, logs/, models/ (imported Offline Model Packs),
    cuda/ (optional: NVIDIA cuBLAS, lets Whisper model packs use an NVIDIA GPU)
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

APP_NAME = "Sabhalekh"
LEGACY_APP_NAME = "MeetScribe"  # name of the pre-release builds; their data folder is moved on first start


def plain_path(p: str | os.PathLike) -> Path:
    r"""Drop the Windows verbatim prefix (\\?\C:\... from Rust canonicalize / Tauri resource_dir).

    Native libraries such as CTranslate2 join "dir/model.bin" with a forward slash, which Windows does not
    translate inside verbatim paths, so the file is reported missing."""
    s = os.fspath(p)
    if s.startswith("\\\\?\\UNC\\"):
        s = "\\\\" + s[8:]
    elif s.startswith("\\\\?\\"):
        s = s[4:]
    return Path(s)


def _app_dir() -> Path:
    env = os.environ.get("SABHALEKH_APP_DIR")
    if env:
        return plain_path(plain_path(env).resolve())
    if getattr(sys, "frozen", False):
        # PyInstaller onedir: <install>/backend/sabhalekh-backend.exe, resources next to it in <install>/
        exe_dir = plain_path(Path(sys.executable).resolve()).parent
        for cand in (exe_dir, exe_dir.parent, exe_dir.parent / "resources"):
            if (cand / "models").is_dir():
                return cand
        return exe_dir.parent
    return Path(__file__).resolve().parents[2]  # repo root in development


def _data_dir() -> Path:
    env = os.environ.get("SABHALEKH_DATA_DIR")
    if env:
        return plain_path(plain_path(env).resolve())
    base = Path(os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming"))
    return _adopt_legacy_data(base / LEGACY_APP_NAME, base / APP_NAME)


def _adopt_legacy_data(old: Path, new: Path) -> Path:
    """Move the data folder of a pre-release build (MeetScribe) to the new name, once.

    If the move fails (the old app is still running and holds the database open), the old folder is used as is
    for this run, so recordings and transcripts never seem to disappear; the move is retried on the next start."""
    if new.exists() or not old.is_dir():
        return new
    try:
        old.rename(new)
    except OSError as e:
        logging.getLogger("sabhalekh").warning("could not move %s to %s (%s); using the old folder", old, new, e)
        return old
    for suffix in ("", "-wal", "-shm"):
        legacy_db = new / f"meetscribe.db{suffix}"
        if legacy_db.exists():
            legacy_db.rename(new / f"sabhalekh.db{suffix}")
    return new


APP_DIR = _app_dir()
MODELS_DIR = APP_DIR / "models"
FONTS_DIR = APP_DIR / "fonts"
TRANSCRIBE_LIB_DIR = APP_DIR / "bin" / "transcribe"  # transcribe.dll + ggml (CPU, Vulkan) for Nemotron ASR
DATA_DIR = _data_dir()
DB_PATH = DATA_DIR / "sabhalekh.db"
SESSIONS_DIR = DATA_DIR / "sessions"
RECORDING_TMP_DIR = DATA_DIR / "recordings-in-progress"
LOGS_DIR = DATA_DIR / "logs"
USER_MODELS_DIR = DATA_DIR / "models"
USER_CUDA_DIR = DATA_DIR / "cuda"


def ensure_dirs() -> None:
    for d in (DATA_DIR, SESSIONS_DIR, RECORDING_TMP_DIR, LOGS_DIR, USER_MODELS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def session_dir(session_id: int) -> Path:
    d = SESSIONS_DIR / str(session_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def model_search_dirs() -> list[Path]:
    """Imported model packs override bundled models with the same name."""
    return [USER_MODELS_DIR, MODELS_DIR]
