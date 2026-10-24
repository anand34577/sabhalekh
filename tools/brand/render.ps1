# Renders the README banner (1600x600) and the social preview (1280x640) into docs\images with Microsoft Edge
# headless. Re-run after changing the HTML or the screenshots they use.
$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { throw "Microsoft Edge not found" }
$images = (Resolve-Path (Join-Path $PSScriptRoot "..\..\docs\images")).Path

function Render([string]$html, [string]$out, [int]$w, [int]$h) {
    $src = "file:///" + (Resolve-Path (Join-Path $PSScriptRoot $html)).Path.Replace([char]92, [char]47)
    $dst = Join-Path $images $out
    if (Test-Path $dst) { Remove-Item $dst }
    # Edge reports progress on stderr; keep it from being treated as an error
    & $edge --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 --allow-file-access-from-files `
        "--user-data-dir=$env:TEMP\sabhalekh-brand-$w-$h" "--window-size=$w,$h" "--screenshot=$dst" $src 2>&1 | Out-Null
    if (-not (Test-Path $dst)) { throw "Failed to render $out" }
    Write-Host "rendered $out"
}

Render "banner.html" "banner.png" 1600 600
Render "social-preview.html" "social-preview.png" 1280 640
