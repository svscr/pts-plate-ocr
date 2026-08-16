param(
    [string]$Python = "$PSScriptRoot\..\..\.venv\Scripts\python.exe",
    [string]$OutputDirectory = "$PSScriptRoot\..\..\outputs"
)

$root = (Resolve-Path "$PSScriptRoot\..").Path
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$distPath = (Resolve-Path -LiteralPath $OutputDirectory).Path
$workPath = Join-Path $root "build"
& $Python -m PyInstaller --noconfirm --clean --onedir --windowed --name PTSPlateOCR `
    --distpath $distPath `
    --workpath $workPath `
    --specpath $root `
    --collect-data rapidocr `
    --hidden-import rapidocr `
    --hidden-import onnxruntime `
    --add-data "$root\licenses;licenses" `
    --paths "$root\src" `
    "$root\run_app.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Copy-Item -LiteralPath "$root\README.md" -Destination (Join-Path $distPath "PTSPlateOCR\KULLANIM.md") -Force
Copy-Item -LiteralPath "$root\licenses" -Destination (Join-Path $distPath "PTSPlateOCR\LICENSES") -Recurse -Force
Write-Host "Uygulama klasörü: $distPath\PTSPlateOCR"
