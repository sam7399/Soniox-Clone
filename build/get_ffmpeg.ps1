# Downloads FFmpeg essentials build (LGPL-friendly gyan.dev build)
# into build/ffmpeg/ for bundling by PyInstaller.
$ErrorActionPreference = "Stop"
$dest = Join-Path $PSScriptRoot "ffmpeg"
if ((Test-Path (Join-Path $dest "ffmpeg.exe")) -and
    (Test-Path (Join-Path $dest "ffprobe.exe"))) {
    Write-Host "FFmpeg already present in build/ffmpeg - skipping."
    exit 0
}
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$zip = Join-Path $env:TEMP "ffmpeg-gva.zip"
Write-Host "Downloading FFmpeg from $url ..."
Invoke-WebRequest -Uri $url -OutFile $zip
$tmp = Join-Path $env:TEMP "ffmpeg-gva-extract"
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
Expand-Archive -Path $zip -DestinationPath $tmp
$bin = Get-ChildItem -Path $tmp -Recurse -Filter "ffmpeg.exe" |
    Select-Object -First 1
Copy-Item (Join-Path $bin.DirectoryName "ffmpeg.exe") $dest
Copy-Item (Join-Path $bin.DirectoryName "ffprobe.exe") $dest
Remove-Item $zip -Force
Remove-Item $tmp -Recurse -Force
Write-Host "FFmpeg ready in build/ffmpeg"
