# PyInstaller spec for the Sabhalekh backend sidecar (onedir: fast start, no temp extraction).
#   pyinstaller backend/sabhalekh-backend.spec --distpath build --workpath build/pyinstaller-work -y
# Models, fonts and native runtimes are NOT bundled here; the installer places them in <app>/models, <app>/fonts,
# <app>/bin/transcribe (transcribe.cpp + ggml, Nemotron ASR) and <app>/bin/needle (Shruti ASR), where sabhalekh.config finds them.
# NVIDIA cuBLAS is never bundled (proprietary); see sabhalekh.hardware._add_cuda_dll_dirs.
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

here = os.path.abspath(SPECPATH)

datas = []
datas += collect_data_files("faster_whisper")          # assets/silero_vad_v6.onnx
datas += collect_data_files("docx")                    # python-docx default template
datas += collect_data_files("fpdf")
binaries = []
binaries += collect_dynamic_libs("ctranslate2")
binaries += collect_dynamic_libs("onnxruntime")
binaries += collect_dynamic_libs("pyaudiowpatch")

hidden = [
    "uvicorn.protocols.http.h11_impl", "uvicorn.protocols.websockets.websockets_sansio_impl", "uvicorn.lifespan.on",
    "uvicorn.loops.asyncio", "pynvml", "uharfbuzz", "fontTools.ttLib", "transcribe_cpp",
    "needle", "needle.agent.whistle",
]

excludes = [
    "tkinter", "unittest", "pydoc", "doctest", "IPython", "matplotlib", "pandas", "scipy", "torch", "transformers",
    "sherpa_onnx", "pytest", "PIL", "pypdfium2", "soundfile", "httptools", "uvloop", "watchfiles", "yaml",
    "nvidia", "hf_xet",
]

a = Analysis(
    [os.path.join(here, "run_backend.py")],
    pathex=[here],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="sabhalekh-backend",
    console=True,          # the shell starts it with CREATE_NO_WINDOW; a console app keeps stdout for the handshake
    icon=os.path.join(here, "..", "app", "src-tauri", "icons", "icon.ico"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="backend", upx=False)
