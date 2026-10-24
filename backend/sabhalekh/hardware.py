"""HardwareManager: detect GPU/CPU/RAM/disk, pick a processing profile, and step down on CUDA out-of-memory.

Profiles (auto-selected; the user can override in Settings):
    gpu_high  discrete GPU with >= 6 GB VRAM   Whisper: cuda, float16, batch 8
    gpu_low   discrete GPU with <  6 GB VRAM   Whisper: cuda, int8_float16, batch 4, ASR model freed after use
    igpu      integrated GPU, no discrete one  Nemotron on the iGPU (shared memory); Whisper on the CPU
    cpu       no usable GPU                    cpu, int8, threads = physical cores
    cpu_fast  "Fast CPU Mode"                  cpu, int8, lighter model, greedy decoding
`accel` is where Nemotron ASR (transcribe.cpp) runs: "gpu" (Vulkan on any discrete GPU, CUDA not needed), "igpu" or
"cpu"; `device` is where Whisper (CTranslate2) runs: "cuda" only with a working CUDA + cuBLAS, else "cpu".
Diarization (Nemotron-3, ONNX int8) always runs on the CPU: ~40x real time, and it leaves all VRAM to ASR.
"""
from __future__ import annotations

import ctypes
import logging
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import config

log = logging.getLogger("sabhalekh.hardware")

HIGH_VRAM_MB = 6 * 1024
PROFILE_ORDER = ["gpu_high", "gpu_low", "igpu", "cpu", "cpu_fast"]


@dataclass
class Profile:
    name: str
    label: str
    device: str  # cuda | cpu
    compute_type: str
    batch_size: int
    beam_size: int
    threads: int
    free_between_stages: bool
    prefer_light_model: bool = False
    accel: str = "cpu"  # gpu | igpu | cpu: where transcribe.cpp (Nemotron ASR) runs

    def badge(self, info: dict) -> str:
        """Where speech recognition runs, in words a user recognises ("GPU Mode: GTX 1650")."""
        if self.accel in ("gpu", "igpu"):
            gpu = accel_name(info, self.accel).replace("NVIDIA ", "").replace("GeForce ", "").replace("(TM)", "")
            return f"{'GPU' if self.accel == 'gpu' else 'iGPU'} Mode: {gpu}"
        fast = "Fast " if self.prefer_light_model else ""
        return f"{fast}CPU Mode ({self.threads} threads)"


@dataclass
class HardwareInfo:
    cuda_available: bool = False
    cuda_error: str | None = None
    gpu_name: str | None = None
    vram_mb: int | None = None
    vram_free_mb: int | None = None
    compute_capability: str | None = None
    cpu_name: str | None = None
    cpu_cores: int = 1
    cpu_threads: int = 1
    ram_mb: int = 0
    ram_available_mb: int = 0
    free_disk_mb: int = 0
    accel_devices: list[dict] = field(default_factory=list)  # GPUs/iGPUs transcribe.cpp can use (Vulkan)
    accel_error: str | None = None
    warnings: list[str] = field(default_factory=list)


CUBLAS_MISSING = (f"Not set up (optional, only Whisper model packs use it). To run them on this GPU, install the "
                  f"NVIDIA CUDA 12 Toolkit or copy cublas64_12.dll and cublasLt64_12.dll into {config.USER_CUDA_DIR}")


def _add_cuda_dll_dirs() -> None:
    """CTranslate2 needs cuBLAS 12 (cublas64_12.dll, cublasLt64_12.dll) to run Whisper on an NVIDIA GPU.

    cuBLAS is NVIDIA's proprietary library, so the installer does not ship it. It is picked up from, in order:
    %APPDATA%/Sabhalekh/cuda (copied there by the user), <app>/bin/cuda (self-built installers), an installed
    CUDA 12 Toolkit (CUDA_PATH*), and pip's nvidia-cublas-cu12 in development. Without it Whisper runs on the CPU;
    the bundled Nemotron ASR never needs it (it uses Vulkan)."""
    cands = [config.USER_CUDA_DIR, config.APP_DIR / "bin" / "cuda"]
    for k, v in sorted(os.environ.items(), reverse=True):
        if k.upper() == "CUDA_PATH" or k.upper().startswith("CUDA_PATH_V12"):
            cands.append(Path(v) / "bin")
            cands.append(Path(v) / "bin" / "x64")
    for p in sys.path:
        cands.append(Path(p) / "nvidia" / "cublas" / "bin")
    if getattr(sys, "frozen", False):
        cands.append(Path(getattr(sys, "_MEIPASS", "")) / "nvidia" / "cublas" / "bin")
    for d in cands:
        if d.is_dir():
            try:
                os.add_dll_directory(str(d))
            except (OSError, AttributeError):
                pass
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")


def probe() -> HardwareInfo:
    import psutil

    info = HardwareInfo()
    info.cpu_cores = psutil.cpu_count(logical=False) or 1
    info.cpu_threads = psutil.cpu_count(logical=True) or info.cpu_cores
    vm = psutil.virtual_memory()
    info.ram_mb = vm.total // (1024 * 1024)
    info.ram_available_mb = vm.available // (1024 * 1024)
    try:
        config.ensure_dirs()
        info.free_disk_mb = shutil.disk_usage(config.DATA_DIR).free // (1024 * 1024)
    except OSError:
        pass
    try:
        import platform

        info.cpu_name = platform.processor() or None
        if sys.platform == "win32":
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                info.cpu_name = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
    except OSError:
        pass

    # GPU: NVML (ships with the NVIDIA driver) for name/VRAM, then make sure CTranslate2 can really use CUDA
    try:
        import pynvml

        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(h)
        info.gpu_name = name.decode() if isinstance(name, bytes) else name
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        info.vram_mb = int(mem.total // (1024 * 1024))
        info.vram_free_mb = int(mem.free // (1024 * 1024))
        major, minor = pynvml.nvmlDeviceGetCudaComputeCapability(h)
        info.compute_capability = f"{major}.{minor}"
        pynvml.nvmlShutdown()
    except Exception as e:  # noqa: BLE001 - no NVIDIA driver is a normal situation
        log.info("no NVIDIA GPU via NVML (%s)", e)
    if info.gpu_name:
        _add_cuda_dll_dirs()
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() < 1:
                raise RuntimeError("CTranslate2 sees no CUDA device")
            if sys.platform == "win32":
                try:
                    ctypes.WinDLL("cublas64_12.dll")
                    ctypes.WinDLL("cublasLt64_12.dll")
                except OSError:
                    info.cuda_error = CUBLAS_MISSING
                    raise
            info.cuda_available = True
        except Exception as e:  # noqa: BLE001
            info.cuda_error = info.cuda_error or f"{type(e).__name__}: {e}"
            log.info("Whisper cannot use CUDA: %s", info.cuda_error)

    # every GPU transcribe.cpp can drive (Vulkan: NVIDIA without CUDA, AMD, Intel, integrated)
    try:
        from .asr.transcribe_cpp import list_devices

        info.accel_devices = list_devices()
    except Exception as e:  # noqa: BLE001
        info.accel_error = f"{type(e).__name__}: {e}"
        log.warning("transcribe.cpp unavailable: %s", info.accel_error)
    dgpu = next((d for d in info.accel_devices if d["type"] == "gpu"), None)
    if dgpu and not info.vram_mb:
        info.vram_mb, info.vram_free_mb = dgpu["memory_mb"], dgpu["memory_free_mb"]
        info.gpu_name = info.gpu_name or dgpu["description"]

    if info.ram_mb and info.ram_mb < 8 * 1024:
        info.warnings.append(f"Only {info.ram_mb // 1024} GB of RAM: long recordings will process slowly.")
    if info.ram_available_mb and info.ram_available_mb < 2048:
        info.warnings.append(f"Low free memory ({info.ram_available_mb} MB available). Close other apps.")
    if info.free_disk_mb and info.free_disk_mb < 2048:
        info.warnings.append(f"Low disk space ({info.free_disk_mb} MB free) in {config.DATA_DIR}.")
    if info.accel_error:
        info.warnings.append("The Nemotron speech engine (transcribe.cpp) could not start; using Whisper if installed.")
    elif info.gpu_name and not has_dgpu(asdict(info)):
        info.warnings.append(f"{info.gpu_name} found but neither Vulkan nor CUDA could use it, running on the CPU.")
    return info


def has_dgpu(info: dict) -> bool:
    return bool(info.get("cuda_available")) or any(d.get("type") == "gpu" for d in info.get("accel_devices") or [])


def has_igpu(info: dict) -> bool:
    return any(d.get("type") == "igpu" for d in info.get("accel_devices") or [])


def accel_name(info: dict, accel: str) -> str:
    dev = next((d for d in info.get("accel_devices") or [] if d.get("type") == accel), None)
    if accel == "gpu":
        return info.get("gpu_name") or (dev or {}).get("description") or "NVIDIA GPU"
    return (dev or {}).get("description") or "integrated GPU"


def has_fast_fp16(info: dict) -> bool:
    """Tensor cores (Volta+ except the GTX 16xx Turing parts). Measured on a GTX 1650: float16 is 4x slower than
    int8_float16 (2.2x vs 8.5x real time), so GTX cards use int8_float16 even with plenty of VRAM."""
    name = (info.get("gpu_name") or "").upper()
    try:
        cc = float(info.get("compute_capability") or 0)
    except ValueError:
        cc = 0.0
    return cc >= 7.0 and "GTX" not in name and "MX" not in name


def make_profile(name: str, info: dict) -> Profile:
    threads = max(1, int(info.get("cpu_cores") or 1))
    if name in ("gpu_high", "gpu_low") and not info.get("cuda_available"):
        # Vulkan-only GPU: Nemotron runs on it, Whisper (CUDA only) on the CPU
        return Profile(name, "GPU (Vulkan)", "cpu", "int8", 4, 3, threads, True, accel="gpu")
    if name == "gpu_high":
        ct = "float16" if has_fast_fp16(info) else "int8_float16"
        return Profile(name, "High-Performance GPU", "cuda", ct, 8, 5, threads, False, accel="gpu")
    if name == "gpu_low":
        return Profile(name, "Low-VRAM GPU", "cuda", "int8_float16", 4, 5, threads, True, accel="gpu")
    if name == "igpu":
        return Profile(name, "Integrated GPU", "cpu", "int8", 4, 3, threads, True, accel="igpu")
    if name == "cpu":
        return Profile(name, "CPU", "cpu", "int8", 4, 3, threads, False)
    if name == "cpu_fast":
        return Profile(name, "Fast CPU", "cpu", "int8", 4, 1, threads, False, prefer_light_model=True)
    raise ValueError(f"unknown profile {name!r}")


def select_profile_name(info: dict, override: str | None = None) -> str:
    """Auto selection, honouring a user override only when the hardware can run it."""
    gpu_ok = has_dgpu(info)
    if override and override != "auto":
        if (override.startswith("gpu") and not gpu_ok) or (override == "igpu" and not has_igpu(info)):
            log.warning("profile %s requested but that device is not usable, using CPU", override)
            return "cpu"
        return override
    # a discrete GPU first: as fast as the iGPU (measured), and its own VRAM leaves the system RAM to other apps
    if gpu_ok:
        return "gpu_high" if (info.get("vram_mb") or 0) >= HIGH_VRAM_MB else "gpu_low"
    if has_igpu(info):
        return "igpu"
    return "cpu"


def next_lighter(name: str) -> str | None:
    i = PROFILE_ORDER.index(name)
    return PROFILE_ORDER[i + 1] if i + 1 < len(PROFILE_ORDER) else None


def is_oom_error(exc: BaseException) -> bool:
    s = f"{type(exc).__name__}: {exc}".lower()
    return any(k in s for k in ("out of memory", "cuda_error_out_of_memory", "cublas_status_alloc_failed",
                                "cudnn_status_alloc_failed", "failed to allocate", "outofmemory"))


def is_cuda_error(exc: BaseException) -> bool:
    s = f"{type(exc).__name__}: {exc}".lower()
    return is_oom_error(exc) or any(k in s for k in ("cuda", "cublas", "cudnn", "nvrtc"))


class HardwareManager:
    def __init__(self, prober: Callable[[], HardwareInfo] = probe):
        self._prober = prober
        self.info: dict = {}
        self.refresh()

    def refresh(self) -> dict:
        self.info = asdict(self._prober())
        return self.info

    def profile(self, override: str | None = None) -> Profile:
        return make_profile(select_profile_name(self.info, override), self.info)

    def downgrade(self, profile: Profile) -> Profile | None:
        nxt = next_lighter(profile.name)
        while nxt and ((nxt.startswith("gpu") and not has_dgpu(self.info))
                       or (nxt == "igpu" and not has_igpu(self.info))):
            nxt = next_lighter(nxt)
        return make_profile(nxt, self.info) if nxt else None

    def status(self, override: str | None = None) -> dict:
        p = self.profile(override)
        return {"info": self.info, "profile": asdict(p), "badge": p.badge(self.info),
                "warnings": self.info.get("warnings", [])}


def free_gpu_memory() -> None:
    """Release GPU memory between stages: CTranslate2 frees VRAM when its model is unloaded and collected."""
    import gc

    gc.collect()
    gc.collect()
