# Builds dist\Sabhalekh-Setup-<version>.exe, dist\Sabhalekh-ModelPack-Accuracy.zip (when Whisper large-v3 is
# available) and dist\SHA256SUMS.txt. The version comes from app\src-tauri\tauri.conf.json.
#
#   powershell -ExecutionPolicy Bypass -File installer\build.ps1 [-SkipTests] [-NoModelPack]
#
# Prerequisites (build machine only): Python 3.12, Node.js 20+, Rust (see installer\toolchain.ps1), the models
# under models\ (tools\fetch_models.py creates them once; the app itself never downloads anything), and the
# transcribe.cpp runtime for Nemotron ASR in bin\transcribe\ (transcribe.dll + ggml*.dll, CPU + Vulkan backends) with
# its Python bindings from -TranscribeCpp (a transcribe.cpp checkout, default $env:TRANSCRIBE_CPP_DIR or C:\tc).
param([switch]$SkipTests, [switch]$NoModelPack, [string]$TranscribeCpp = $(if ($env:TRANSCRIBE_CPP_DIR) { $env:TRANSCRIBE_CPP_DIR } else { "C:\tc" }))

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$version = (Get-Content "app\src-tauri\tauri.conf.json" -Raw | ConvertFrom-Json).version
$build = Join-Path $root "build"
$dist = Join-Path $root "dist"
New-Item -ItemType Directory -Force $build, $dist | Out-Null

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

# ------------------------------------------------------------------ Python environment
Step "Python environment"
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { py -3.12 -m venv .venv }
& $py -m pip install -q --upgrade pip
& $py -m pip install -q -r backend\requirements-dev.txt
if ($LASTEXITCODE) { throw "pip install failed" }
# transcribe.cpp Python bindings (pure ctypes): --no-deps because the native library is bin\transcribe\transcribe.dll
& $py -c "import importlib.util, sys; sys.exit(importlib.util.find_spec('transcribe_cpp') is None)"
if ($LASTEXITCODE) {
    & $py -m pip install -q --no-deps (Join-Path $TranscribeCpp "bindings\python")
    if ($LASTEXITCODE) { throw "transcribe-cpp bindings not found in $TranscribeCpp\bindings\python (use -TranscribeCpp)" }
}

# ------------------------------------------------------------------ models
Step "Models"
$asr = "models\asr\nemotron-3.5-asr-0.6b"
$nem = "models\diarization\nemotron3\encoder_int8.onnx"
if (-not (Get-ChildItem "$asr\*.gguf" -ErrorAction SilentlyContinue) -or -not (Test-Path $nem)) {
    throw "Models missing. Run tools\fetch_models.py once (see README, 'Building the models')."
}
if (-not (Test-Path "bin\transcribe\transcribe.dll") -or -not (Test-Path "bin\transcribe\ggml-vulkan.dll")) {
    throw "bin\transcribe\ (transcribe.dll, ggml*.dll) missing. See README, 'Building the models'."
}
$bm = Join-Path $build "models"
Remove-Item -Recurse -Force $bm -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$bm\asr", "$bm\diarization" | Out-Null
Copy-Item -Recurse $asr "$bm\asr\"
Copy-Item -Recurse "models\diarization\nemotron3" "$bm\diarization\"
& $py tools\make_manifest.py manifest $bm
if ($LASTEXITCODE) { throw "manifest failed" }

# ------------------------------------------------------------------ tests
if (-not $SkipTests) {
    Step "Tests"
    & $py -m pytest tests -q
    if ($LASTEXITCODE) { throw "Python tests failed" }
}

# ------------------------------------------------------------------ backend (PyInstaller)
Step "Backend sidecar (PyInstaller)"
Remove-Item -Recurse -Force "$build\backend" -ErrorAction SilentlyContinue
& $py -m PyInstaller backend\sabhalekh-backend.spec --distpath $build --workpath "$build\pyinstaller-work" -y --log-level WARN
if ($LASTEXITCODE) { throw "PyInstaller failed" }

# Nemotron ASR runtime: transcribe.cpp + ggml CPU and Vulkan backends (no ggml-cuda: Vulkan drives NVIDIA GPUs too)
$tcd = Join-Path $build "bin\transcribe"
Remove-Item -Recurse -Force $tcd -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $tcd | Out-Null
Copy-Item "bin\transcribe\transcribe.dll", "bin\transcribe\ggml.dll", "bin\transcribe\ggml-base.dll", "bin\transcribe\ggml-cpu.dll", "bin\transcribe\ggml-vulkan.dll" $tcd -Force

# NVIDIA cuBLAS is not shipped: it is proprietary, and only the optional Whisper packs could use it.
Remove-Item -Recurse -Force (Join-Path $build "bin\cuda"), (Join-Path $build "bin\licenses") -ErrorAction SilentlyContinue
Copy-Item licenses (Join-Path $build "bin\licenses") -Recurse -Force

# smoke test: the frozen backend starts, answers /api/health and blocks the network
Step "Backend smoke test"
$token = [guid]::NewGuid().ToString("N")
$env:SABHALEKH_APP_DIR = $build
$env:SABHALEKH_DATA_DIR = Join-Path $build "smoke-data"
$p = Start-Process -FilePath "$build\backend\sabhalekh-backend.exe" -ArgumentList "--token", $token, "--port", "8799" -PassThru -WindowStyle Hidden -RedirectStandardOutput "$build\smoke.out" -RedirectStandardError "$build\smoke.err"
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $h = Invoke-RestMethod -Uri "http://127.0.0.1:8799/api/health" -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 2
        if ($h.ok) { $ok = $true; break }
    } catch { }
}
Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
Remove-Item Env:SABHALEKH_APP_DIR, Env:SABHALEKH_DATA_DIR
if (-not $ok) { Get-Content "$build\smoke.err" -Tail 30; throw "frozen backend did not start" }
Write-Host "frozen backend OK"

# ------------------------------------------------------------------ desktop shell + installer
Step "Desktop shell + NSIS installer (Tauri)"
. (Join-Path $PSScriptRoot "toolchain.ps1")
Push-Location app
if (-not (Test-Path node_modules)) { npm ci }
npm test
if ($LASTEXITCODE) { throw "UI tests failed" }
npx tauri build
if ($LASTEXITCODE) { throw "tauri build failed" }
Pop-Location
$nsis = Get-ChildItem (Join-Path $env:CARGO_TARGET_DIR "release\bundle\nsis") -Filter "*-setup.exe" | Sort-Object LastWriteTime | Select-Object -Last 1
Get-ChildItem $dist -Filter "Sabhalekh-Setup-*.exe" | Remove-Item -Force
Copy-Item $nsis.FullName (Join-Path $dist "Sabhalekh-Setup-$version.exe") -Force

# ------------------------------------------------------------------ optional Offline Model Pack
if (-not $NoModelPack -and (Test-Path "models\asr\whisper-large-v3-int8\model.bin")) {
    Step "Offline Model Pack: Accuracy (Whisper large-v3)"
    $packDir = Join-Path $dist "Sabhalekh-ModelPack-Accuracy"
    Remove-Item -Recurse -Force $packDir -ErrorAction SilentlyContinue
    & $py tools\make_manifest.py pack $packDir "Accuracy" "whisper-large-v3-int8:models\asr\whisper-large-v3-int8"
    if ($LASTEXITCODE) { throw "model pack failed" }
    # one file for the release page (the int8 model barely compresses, so this is mostly packaging)
    $zip = Join-Path $dist "Sabhalekh-ModelPack-Accuracy.zip"
    Remove-Item $zip -ErrorAction SilentlyContinue
    & $py -c "import shutil, sys; shutil.make_archive(sys.argv[1][:-4], 'zip', sys.argv[2], sys.argv[3])" $zip $dist (Split-Path -Leaf $packDir)
    if ($LASTEXITCODE) { throw "zipping the model pack failed" }
}

Step "Checksums"
$sums = Get-ChildItem $dist -File | Where-Object { $_.Name -match '^Sabhalekh-.*\.(exe|zip)$' } | Sort-Object Name |
    ForEach-Object { "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name }
$sums | Set-Content (Join-Path $dist "SHA256SUMS.txt") -Encoding ascii
$sums

Step "Done"
Get-ChildItem $dist | ForEach-Object { "{0,-40} {1,10:N0} MB" -f $_.Name, ((Get-ChildItem $_.FullName -Recurse -File | Measure-Object Length -Sum).Sum / 1MB) }
