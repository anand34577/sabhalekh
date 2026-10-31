"""Model catalog, checksum verification and Offline Model Pack import.

Bundled models live in <app>/models with <app>/models/manifest.json ({relative path: {sha256, size}}).
Every file is hashed once (in the background at startup); later startups re-hash only files whose size or mtime
changed. A file that fails its checksum makes its model unavailable, with the reason shown in the UI.

An Offline Model Pack is a folder (or USB drive) holding `sabhalekh-pack.json`:
    {"name": "...", "models": [{"id", "kind": "asr"|"diarization", "engine", "label", "dir", "translate"}],
     "files": {"<dir>/<file>": {"sha256": "...", "size": 123}}}
next to the model directories. Importing verifies every file, then copies it to %APPDATA%/Sabhalekh/models.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import threading
from pathlib import Path
from typing import Callable

from . import config

log = logging.getLogger("sabhalekh.models")

BUILTIN = [
    {"id": "nemotron-3.5-asr-0.6b", "kind": "asr", "engine": "transcribe-cpp", "translate": False,
     "label": "NVIDIA Nemotron 3.5 ASR (0.6B)", "dir": "asr/nemotron-3.5-asr-0.6b",
     "notes": "Default. Lowest Hindi word error rate, punctuated output, ~18x real time on a GTX 1650 with "
              "0.7 GB VRAM. Runs on any Vulkan GPU, an integrated GPU or the CPU. Cannot translate."},
    {"id": "shruti-55m", "kind": "asr", "engine": "needle-whistle", "translate": False,
     "label": "Udgam Labs Shruti (55M)", "dir": "asr/shruti",
     "notes": "Tiny (30 MB) Hindi, English and Hinglish model, CPU only. Best open model on Hinglish; Hindi in "
              "Devanagari, English words in Latin. No punctuation or capitals. Cannot translate."},
    {"id": "whisper-large-v3-turbo-int8", "kind": "asr", "engine": "faster-whisper", "translate": False,
     "label": "Whisper large-v3-turbo", "dir": "asr/whisper-large-v3-turbo-int8",
     "notes": "Fast multilingual model. Not used for 'Translate to English' (it was not trained for translation)."},
    {"id": "whisper-large-v3-int8", "kind": "asr", "engine": "faster-whisper", "translate": True,
     "label": "Whisper large-v3", "dir": "asr/whisper-large-v3-int8",
     "notes": "Most accurate for Hindi; supports Translate to English. About 3x slower than turbo."},
    {"id": "whisper-medium-int8", "kind": "asr", "engine": "faster-whisper", "translate": True,
     "label": "Whisper medium", "dir": "asr/whisper-medium-int8",
     "notes": "Lighter model for CPU-only machines; supports translation."},
    {"id": "whisper-small-int8", "kind": "asr", "engine": "faster-whisper", "translate": True,
     "label": "Whisper small", "dir": "asr/whisper-small-int8", "notes": "Fast CPU Mode."},
    {"id": "nemotron3-diarization", "kind": "diarization", "engine": "nemotron-onnx", "translate": False,
     "label": "NVIDIA Nemotron-3-Diarization (ONNX)", "dir": "diarization/nemotron3",
     "notes": "Up to 8 speakers, arrival order, 10 ms resolution. Runs on the CPU."},
]
REQUIRED_FILES = {"faster-whisper": ["model.bin", "config.json", "tokenizer.json"],
                  "nemotron-onnx": ["frontend.npz"]}


def _transcribe_cpp_installed() -> bool:
    import importlib.util
    import os

    lib = os.environ.get("TRANSCRIBE_LIBRARY") or str(config.TRANSCRIBE_LIB_DIR / "transcribe.dll")
    return Path(lib).is_file() and importlib.util.find_spec("transcribe_cpp") is not None


def _needle_installed() -> bool:
    from .asr.shruti import runtime_installed

    return runtime_installed()


def _sha256(path: Path, chunk: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


class ModelRegistry:
    def __init__(self):
        self.lock = threading.Lock()
        self.verify_state = "pending"  # pending | running | ok | failed
        self.bad_files: dict[str, str] = {}
        self._cache_path = config.DATA_DIR / "model_checksums.json"

    # ------------------------------------------------------------------ catalog
    def catalog(self) -> list[dict]:
        models = [dict(m, source="bundled") for m in BUILTIN]
        for pack_file in config.USER_MODELS_DIR.glob("*/sabhalekh-pack.json"):
            try:
                pack = json.loads(pack_file.read_text(encoding="utf-8"))
                for m in pack.get("models", []):
                    m = dict(m, source=f"pack:{pack.get('name', pack_file.parent.name)}",
                             dir=str(Path(pack_file.parent.name) / m["dir"]))
                    models = [x for x in models if x["id"] != m["id"]] + [m]
            except (OSError, json.JSONDecodeError, KeyError) as e:
                log.warning("ignoring broken model pack %s: %s", pack_file, e)
        for m in models:
            m["path"] = self._resolve(m)
            m["available"], m["problem"] = self._check(m)
        return models

    def _resolve(self, m: dict) -> str | None:
        for base in config.model_search_dirs():
            p = base / m["dir"]
            if p.is_dir():
                return str(p)
        return None

    def _check(self, m: dict) -> tuple[bool, str | None]:
        if not m["path"]:
            return False, "not installed (import an Offline Model Pack to add it)"
        p = Path(m["path"])
        need = REQUIRED_FILES.get(m["engine"], [])
        missing = [f for f in need if not (p / f).exists()]
        if m["engine"] == "nemotron-onnx" and not any(p.glob("encoder_*.onnx")):
            missing.append("encoder_*.onnx")
        if m["engine"] == "transcribe-cpp" and not any(p.glob("*.gguf")):
            missing.append("*.gguf")
        if m["engine"] == "needle-whistle" and not any(p.glob("*.cact")):
            missing.append("*.cact")
        if missing:
            return False, f"missing files: {', '.join(missing)}"
        if m["engine"] == "needle-whistle" and not _needle_installed():
            return False, "the Shruti runtime (bin/needle/libneedle.dll) is missing; reinstall Sabhalekh"
        if m["engine"] == "transcribe-cpp" and not _transcribe_cpp_installed():
            return False, "the transcribe.cpp runtime (bin/transcribe/transcribe.dll) is missing; reinstall Sabhalekh"
        bad = [f for f in self.bad_files if f.startswith(m["dir"].replace("\\", "/") + "/")]
        if bad:
            return False, f"checksum mismatch: {', '.join(bad)} (reinstall or re-import the model pack)"
        return True, None

    def get(self, model_id: str) -> dict | None:
        return next((m for m in self.catalog() if m["id"] == model_id), None)

    def available(self, kind: str) -> list[dict]:
        return [m for m in self.catalog() if m["kind"] == kind and m["available"]]

    def choose_asr(self, requested: str | None, translate: bool, prefer_light: bool, device: str) -> dict:
        """Requested model if usable; otherwise the best installed one for the task and hardware."""
        avail = {m["id"]: m for m in self.available("asr")}
        if not avail:
            raise RuntimeError("No speech recognition model is installed. Import an Offline Model Pack in Settings.")
        if requested and requested != "auto" and requested in avail:
            m = avail[requested]
            if not translate or m.get("translate"):
                return m
        if translate:
            order = ["whisper-large-v3-int8", "whisper-medium-int8", "whisper-small-int8"]
        else:
            # Nemotron 3.5 ASR beats every Whisper on Hindi (FLEURS test clips: WER 19 % vs 23 % for large-v3,
            # 27 % for turbo) and is the fastest and lightest on GPU, iGPU and CPU alike; Whisper remains the
            # fallback and the translator
            order = ["nemotron-3.5-asr-0.6b"]
            if prefer_light:
                order += ["shruti-55m", "whisper-small-int8", "whisper-medium-int8", "whisper-large-v3-turbo-int8"]
            elif device == "cuda":
                order += ["whisper-large-v3-int8", "whisper-large-v3-turbo-int8", "whisper-medium-int8"]
            else:
                order += ["whisper-large-v3-turbo-int8", "whisper-medium-int8", "whisper-small-int8",
                          "whisper-large-v3-int8"]
        for mid in order:
            if mid in avail and (not translate or avail[mid].get("translate")):
                return avail[mid]
        if translate:
            raise RuntimeError("Translate to English needs Whisper large-v3, medium or small (large-v3-turbo cannot "
                               "translate). Import the model pack that contains one.")
        return next(iter(avail.values()))

    # ------------------------------------------------------------------ checksums
    def verify(self, progress: Callable[[float], None] | None = None) -> None:
        """Check every file listed in the bundled manifest and every imported pack against its sha256."""
        with self.lock:
            self.verify_state = "running"
        try:
            cache = {}
            if self._cache_path.exists():
                cache = json.loads(self._cache_path.read_text(encoding="utf-8"))
            entries: list[tuple[str, Path, dict]] = []
            man = config.MODELS_DIR / "manifest.json"
            if man.exists():
                for rel, meta in json.loads(man.read_text(encoding="utf-8")).get("files", {}).items():
                    entries.append((rel, config.MODELS_DIR / rel, meta))
            for pack_file in config.USER_MODELS_DIR.glob("*/sabhalekh-pack.json"):
                pack = json.loads(pack_file.read_text(encoding="utf-8"))
                for rel, meta in pack.get("files", {}).items():
                    entries.append((f"{pack_file.parent.name}/{rel}", pack_file.parent / rel, meta))
            bad: dict[str, str] = {}
            total = sum(int(m.get("size", 0)) for _, _, m in entries) or 1
            done = 0
            for rel, path, meta in entries:
                if not path.exists():
                    bad[rel] = "missing"
                    continue
                st = path.stat()
                key = str(path)
                c = cache.get(key)
                if c and c["size"] == st.st_size and c["mtime"] == st.st_mtime and c["sha256"] == meta["sha256"]:
                    digest = c["sha256"]
                else:
                    digest = _sha256(path)
                    cache[key] = {"size": st.st_size, "mtime": st.st_mtime, "sha256": digest}
                if digest != meta["sha256"]:
                    bad[rel] = "checksum mismatch"
                    cache.pop(key, None)
                done += int(meta.get("size", 0))
                if progress:
                    progress(done / total)
            self._cache_path.write_text(json.dumps(cache), encoding="utf-8")
            with self.lock:
                self.bad_files = bad
                self.verify_state = "failed" if bad else "ok"
            if bad:
                log.error("model files failed verification: %s", bad)
            else:
                log.info("all %d model files verified", len(entries))
        except Exception as e:  # noqa: BLE001
            log.exception("model verification error")
            with self.lock:
                self.verify_state = f"failed: {e}"

    # ------------------------------------------------------------------ model packs
    def import_pack(self, src: str, progress: Callable[[float], None] | None = None) -> dict:
        src_dir = Path(src)
        pack_file = src_dir / "sabhalekh-pack.json"
        if not pack_file.exists():
            raise ValueError(f"{src} is not an Offline Model Pack (sabhalekh-pack.json not found)")
        pack = json.loads(pack_file.read_text(encoding="utf-8"))
        files = pack.get("files", {})
        if not files or not pack.get("models"):
            raise ValueError("the model pack lists no models or files")
        total = sum(int(m.get("size", 0)) for m in files.values()) or 1
        need = total * 1.05 / (1024 * 1024)
        free = shutil.disk_usage(config.USER_MODELS_DIR).free / (1024 * 1024)
        if free < need:
            raise ValueError(f"not enough disk space: {need:.0f} MB needed, {free:.0f} MB free")
        done = 0
        for rel, meta in files.items():
            p = src_dir / rel
            if not p.exists():
                raise ValueError(f"model pack file missing: {rel}")
            if _sha256(p) != meta["sha256"]:
                raise ValueError(f"model pack file is corrupt (checksum mismatch): {rel}")
            done += int(meta.get("size", 0))
            if progress:
                progress(0.5 * done / total)
        name = "".join(ch for ch in pack.get("name", src_dir.name) if ch.isalnum() or ch in "-_.") or "pack"
        dst = config.USER_MODELS_DIR / name
        tmp = dst.with_name(name + ".importing")
        shutil.rmtree(tmp, ignore_errors=True)
        done = 0
        for rel, meta in files.items():
            out = tmp / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_dir / rel, out)
            done += int(meta.get("size", 0))
            if progress:
                progress(0.5 + 0.5 * done / total)
        shutil.copy2(pack_file, tmp / "sabhalekh-pack.json")
        shutil.rmtree(dst, ignore_errors=True)
        tmp.rename(dst)
        log.info("imported model pack %s (%d files)", name, len(files))
        return {"name": name, "models": [m["id"] for m in pack["models"]]}
