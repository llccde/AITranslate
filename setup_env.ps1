# setup_env.ps1 — Create conda env inside project folder and install deps
$ErrorActionPreference = "Stop"

$prefix = "$PSScriptRoot\.conda"
$envName = "aitranslate"

if (Test-Path $prefix) {
    Write-Host "Removing existing env at $prefix..."
    conda env remove --prefix $prefix -y
}

Write-Host "Creating conda env at $prefix (Python 3.10)..."
conda create --prefix $prefix python=3.10 pyqt qtbase pillow -y
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Installing remaining packages via pip..."
conda run --prefix $prefix pip install easyocr deep-translator pywin32 pynput cleantext

Write-Host ""
Write-Host "Done. Activate with: conda activate $prefix"
Write-Host "Then run: python main.py"
