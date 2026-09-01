param(
    [string]$Python = "$PSScriptRoot\..\..\.venv\Scripts\python.exe",
    [string]$OutputDirectory = "$PSScriptRoot\..\..\outputs",
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Windows portable paketi yalnız Windows üzerinde oluşturulabilir."
}

$root = (Resolve-Path "$PSScriptRoot\..").Path
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$distPath = (Resolve-Path -LiteralPath $OutputDirectory).Path
$workPath = Join-Path $root "build"
$appPath = Join-Path $distPath "PTSPlateOCR"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python bulunamadı: $Python"
}

if (-not $Version) {
    $versionMatch = Select-String -LiteralPath (Join-Path $root "pyproject.toml") `
        -Pattern '^version = "([^"]+)"$'
    if (-not $versionMatch) {
        throw "Sürüm pyproject.toml dosyasından okunamadı."
    }
    $Version = $versionMatch.Matches[0].Groups[1].Value
}

if (Test-Path -LiteralPath $appPath) {
    Remove-Item -LiteralPath $appPath -Recurse -Force
}

& $Python -m PyInstaller --noconfirm --clean --onedir --windowed --name PTSPlateOCR `
    --distpath $distPath `
    --workpath $workPath `
    --specpath $root `
    --collect-data rapidocr `
    --hidden-import rapidocr `
    --hidden-import onnxruntime `
    --exclude-module pytest `
    --exclude-module tests `
    --paths "$root\src" `
    "$root\run_app.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Copy-Item -LiteralPath "$root\README.md" -Destination (Join-Path $appPath "KULLANIM.md") -Force
Copy-Item -LiteralPath "$root\licenses" -Destination (Join-Path $appPath "LICENSES") -Recurse -Force

$archivePath = Join-Path $distPath "PTSPlateOCR-v$Version-win64.zip"
$checksumPath = "$archivePath.sha256"
if (Test-Path -LiteralPath $archivePath) {
    Remove-Item -LiteralPath $archivePath -Force
}
if (Test-Path -LiteralPath $checksumPath) {
    Remove-Item -LiteralPath $checksumPath -Force
}

Compress-Archive -LiteralPath $appPath -DestinationPath $archivePath -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
$checksum = "$hash  $(Split-Path -Leaf $archivePath)`n"
[System.IO.File]::WriteAllText($checksumPath, $checksum, [System.Text.Encoding]::ASCII)

Write-Host "Uygulama klasörü: $appPath"
Write-Host "Portable ZIP: $archivePath"
Write-Host "SHA-256: $checksumPath"
