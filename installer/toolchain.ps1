# Selects a working Rust toolchain for the Tauri shell. Dot-source it: . .\installer\toolchain.ps1
#
# * Visual Studio with the C++ workload (MSVC + Windows SDK) installed -> default MSVC toolchain.
# * Otherwise the GNU toolchain (rustup toolchain install stable-x86_64-pc-windows-gnu) with a MinGW-w64 GCC on PATH
#   (e.g. TDM-GCC-64). Two known GNU pitfalls are handled:
#     - TDM-GCC folds libgcc_eh into libgcc: an empty libgcc_eh.a stub satisfies rustc's -lgcc_eh.
#     - Rust's self-contained dlltool has no assembler next to it, so the system MinGW (with as.exe) is used.
#   Cargo's target dir is put on a path without spaces (binutils dislike spaces).

$ErrorActionPreference = "Stop"
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$msvc = $null
if (Test-Path $vswhere) {
    $msvc = & $vswhere -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
}
if ($msvc) {
    Write-Host "Rust toolchain: MSVC ($msvc)"
    Remove-Item Env:RUSTUP_TOOLCHAIN -ErrorAction SilentlyContinue
} else {
    $gcc = (Get-Command gcc.exe -ErrorAction SilentlyContinue).Source
    if (-not $gcc) {
        throw "No C++ build tools found. Install either Visual Studio Build Tools (Desktop development with C++) or a MinGW-w64 GCC (e.g. TDM-GCC-64) plus 'rustup toolchain install stable-x86_64-pc-windows-gnu'."
    }
    $stub = Join-Path $env:USERPROFILE ".sabhalekh-gccfix"
    New-Item -ItemType Directory -Force $stub | Out-Null
    if (-not (Test-Path (Join-Path $stub "libgcc_eh.a"))) {
        $ar = Join-Path (Split-Path $gcc) "ar.exe"
        Push-Location $stub; & $ar rcs libgcc_eh.a; Pop-Location
    }
    $env:RUSTUP_TOOLCHAIN = "stable-x86_64-pc-windows-gnu"
    $env:RUSTFLAGS = "-L $stub"
    Write-Host "Rust toolchain: GNU with $gcc"
}
$env:CARGO_TARGET_DIR = Join-Path $env:USERPROFILE ".sabhalekh-target"
